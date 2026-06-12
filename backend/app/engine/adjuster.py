"""Deterministic metric adjustment from played results.

Adjusted profiles are always recomputed by replaying the ordered list of
final results over the immutable base dataset (never by mutating stored
team data), so the derivation is idempotent and trivially cacheable.
Elo follows the standard update with the eloratings.net goal-difference
multiplier; form_index follows an exponential moving average of results.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Sequence

from .config import ModelConfig
from .core import TeamProfile


@dataclass(frozen=True)
class AdjustmentConfig:
    """K-factor 40 is the continental-championship tier; eloratings.net
    uses 60 for World Cup finals but our base Elos already price in the
    pre-tournament window, so the softer update avoids overshooting."""

    k_factor: float = 40.0
    form_alpha: float = 0.30
    home_advantage_elo: float = ModelConfig().home_advantage_elo


def _goal_diff_multiplier(gd: int) -> float:
    gd = abs(gd)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0


def _result_score(goals_for: int, goals_against: int) -> float:
    if goals_for > goals_against:
        return 1.0
    if goals_for < goals_against:
        return 0.0
    return 0.5


def elo_delta(
    elo_home: float,
    elo_away: float,
    goals_home: int,
    goals_away: int,
    *,
    home_adv_elo: float = 0.0,
    cfg: AdjustmentConfig = AdjustmentConfig(),
) -> float:
    """Home side's Elo change (away side gets the negation)."""
    expected = 1.0 / (1.0 + 10.0 ** (-(elo_home + home_adv_elo - elo_away) / 400.0))
    actual = _result_score(goals_home, goals_away)
    g = _goal_diff_multiplier(goals_home - goals_away)
    return cfg.k_factor * g * (actual - expected)


def update_form(
    form_old: float, result_score: float, cfg: AdjustmentConfig = AdjustmentConfig()
) -> float:
    blended = cfg.form_alpha * result_score + (1.0 - cfg.form_alpha) * form_old
    return min(max(blended, 0.0), 1.0)


def apply_results(
    base: Dict[str, TeamProfile],
    fixtures: Sequence[dict],
    results: Dict[str, dict],
    cfg: AdjustmentConfig = AdjustmentConfig(),
) -> Dict[str, TeamProfile]:
    """Replay final results in (matchday, id) order onto fresh copies of the
    base profiles, using the running Elo for sequential matches."""
    adjusted = {name: replace(profile) for name, profile in base.items()}

    ordered: List[dict] = sorted(fixtures, key=lambda f: (f["matchday"], f["id"]))
    for fixture in ordered:
        record = results.get(fixture["id"])
        if record is None or record.get("status") != "final":
            continue
        home = adjusted.get(fixture["home"])
        away = adjusted.get(fixture["away"])
        if home is None or away is None:
            continue
        gh, ga = int(record["goals_home"]), int(record["goals_away"])

        host = fixture.get("home_team_host")
        adv = 0.0
        if host == home.name:
            adv = cfg.home_advantage_elo
        elif host == away.name:
            adv = -cfg.home_advantage_elo

        delta = elo_delta(home.elo, away.elo, gh, ga, home_adv_elo=adv, cfg=cfg)
        home.elo += delta
        away.elo -= delta
        home.form_index = update_form(home.form_index, _result_score(gh, ga), cfg)
        away.form_index = update_form(away.form_index, _result_score(ga, gh), cfg)
    return adjusted
