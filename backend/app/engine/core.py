"""Shared mathematical core: the single source of truth mapping team
profiles and match context to expected-goal lambdas, plus the Dixon-Coles
low-score correction in scalar and vectorized form."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .config import ModelConfig


@dataclass
class TeamProfile:
    """Static profile of a qualified team (June 2026 snapshot)."""

    name: str
    elo: float
    group: str = ""
    fifa_ranking: int = 0
    confederation: str = "UEFA"
    is_host: bool = False
    altitude_adapted: bool = False
    xg_avg: float = 1.30
    xga_avg: float = 1.30
    form_index: float = 0.5
    injury_impact: float = 0.1

    def __post_init__(self) -> None:
        if self.elo <= 0:
            raise ValueError(f"Invalid Elo for {self.name}: {self.elo}")
        if not (0.0 <= self.form_index <= 1.0):
            raise ValueError(f"form_index out of [0, 1] for {self.name}")
        if not (0.0 <= self.injury_impact <= 1.0):
            raise ValueError(f"injury_impact out of [0, 1] for {self.name}")


@dataclass
class MatchContext:
    """Environmental and venue context of a single fixture."""

    altitude_m: float = 0.0
    heat_index: float = 0.0
    home_team: Optional[str] = None


@dataclass
class ParameterOverrides:
    """Per-request what-if overrides driven by the frontend sliders.

    Any field left as None falls back to the team's baseline metric.
    """

    home_form: Optional[float] = None
    away_form: Optional[float] = None
    home_injury: Optional[float] = None
    away_injury: Optional[float] = None
    home_fatigue: Optional[float] = None
    away_fatigue: Optional[float] = None
    xg_blend_weight: Optional[float] = None
    rho: Optional[float] = None


def elo_to_lambdas(
    elo_home: float,
    elo_away: float,
    cfg: ModelConfig,
    *,
    home_adv: bool = False,
    away_adv: bool = False,
) -> Tuple[float, float]:
    """Convert Elo ratings into expected goals via a bounded tanh supremacy."""
    eh = elo_home + (cfg.home_advantage_elo if home_adv else 0.0)
    ea = elo_away + (cfg.home_advantage_elo if away_adv else 0.0)
    supremacy = cfg.max_supremacy * math.tanh(cfg.supremacy_beta * (eh - ea))
    lam_h = max((cfg.avg_total_goals + supremacy) / 2.0, cfg.min_lambda)
    lam_a = max((cfg.avg_total_goals - supremacy) / 2.0, cfg.min_lambda)
    return lam_h, lam_a


def _team_factors(
    profile: TeamProfile,
    cfg: ModelConfig,
    form_override: Optional[float],
    injury_override: Optional[float],
    fatigue: float = 0.0,
) -> Tuple[float, float]:
    """Attack and defense multipliers from form momentum, injury attrition
    and accumulated fatigue (fatigue = 0 is an exact no-op).

    Returns:
        (attack_factor, defense_factor) where defense_factor > 1 means the
        team concedes more than its baseline xGA.
    """
    form = profile.form_index if form_override is None else form_override
    injury = profile.injury_impact if injury_override is None else injury_override
    form = min(max(form, 0.0), 1.0)
    injury = min(max(injury, 0.0), 1.0)
    fatigue = min(max(fatigue, 0.0), 1.0)

    form_mult = 1.0 + (form - 0.5) * cfg.form_swing
    attack = form_mult * (1.0 - injury * cfg.injury_attack_weight)
    defense = (2.0 - form_mult) * (1.0 + injury * cfg.injury_defense_weight)
    attack *= 1.0 - fatigue * cfg.fatigue_attack_weight
    defense *= 1.0 + fatigue * cfg.fatigue_defense_weight
    return max(attack, 0.05), max(defense, 0.05)


def compute_lambdas(
    home: TeamProfile,
    away: TeamProfile,
    cfg: ModelConfig,
    ctx: Optional[MatchContext] = None,
    overrides: Optional[ParameterOverrides] = None,
) -> Tuple[float, float]:
    """Compute the final expected goals (lambda) for both sides of a fixture.

    The Elo-supremacy lambda is blended with an xG-cross lambda
    (own attack vs opposing defense), both modulated by form and injury
    factors, then penalized for altitude hypoxia and WBGT heat burden.
    """
    ctx = ctx or MatchContext()
    ov = overrides or ParameterOverrides()

    att_h, def_h = _team_factors(
        home, cfg, ov.home_form, ov.home_injury, ov.home_fatigue or 0.0
    )
    att_a, def_a = _team_factors(
        away, cfg, ov.away_form, ov.away_injury, ov.away_fatigue or 0.0
    )

    elo_h, elo_a = elo_to_lambdas(
        home.elo, away.elo, cfg,
        home_adv=(ctx.home_team == home.name),
        away_adv=(ctx.home_team == away.name),
    )
    elo_h *= att_h
    elo_a *= att_a

    xg_h = (home.xg_avg * att_h + away.xga_avg * def_a) / 2.0
    xg_a = (away.xg_avg * att_a + home.xga_avg * def_h) / 2.0

    w = cfg.xg_blend_weight if ov.xg_blend_weight is None else ov.xg_blend_weight
    w = min(max(w, 0.0), 1.0)
    lam_h = (1.0 - w) * elo_h + w * xg_h
    lam_a = (1.0 - w) * elo_a + w * xg_a

    if ctx.altitude_m > cfg.altitude_threshold_m:
        excess = (ctx.altitude_m - cfg.altitude_threshold_m) / cfg.altitude_threshold_m
        penalty = min(excess, 1.0) * cfg.altitude_max_penalty
        if not home.altitude_adapted:
            lam_h *= 1.0 - penalty
        if not away.altitude_adapted:
            lam_a *= 1.0 - penalty

    if ctx.heat_index > 0:
        heat_factor = max(1.0 - cfg.heat_penalty_per_index * ctx.heat_index, 0.5)
        lam_h *= heat_factor
        lam_a *= heat_factor

    return max(lam_h, cfg.min_lambda), max(lam_a, cfg.min_lambda)


def dc_tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Scalar Dixon-Coles low-score correction factor."""
    if x == 0 and y == 0:
        return 1.0 - lam * mu * rho
    if x == 0 and y == 1:
        return 1.0 + lam * rho
    if x == 1 and y == 0:
        return 1.0 + mu * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def dc_tau_vec(
    gh: np.ndarray, ga: np.ndarray, lam: np.ndarray, mu: np.ndarray, rho: float
) -> np.ndarray:
    """Vectorized Dixon-Coles correction used by the MLE calibrator."""
    tau = np.ones_like(lam, dtype=float)
    m00 = (gh == 0) & (ga == 0)
    m01 = (gh == 0) & (ga == 1)
    m10 = (gh == 1) & (ga == 0)
    m11 = (gh == 1) & (ga == 1)
    tau[m00] = 1.0 - lam[m00] * mu[m00] * rho
    tau[m01] = 1.0 + lam[m01] * rho
    tau[m10] = 1.0 + mu[m10] * rho
    tau[m11] = 1.0 - rho
    return np.clip(tau, 1e-6, None)
