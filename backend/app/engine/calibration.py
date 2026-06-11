"""Maximum-likelihood calibration of the model hyperparameters against
historical results, with Dixon-Coles style exponential time decay."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

from .config import ModelConfig
from .core import MatchContext, TeamProfile, dc_tau_vec
from .predictor import EloPoissonModel

logger = logging.getLogger("wc2026.calibration")


@dataclass
class HistoricalMatch:
    """A historical result with the Elo ratings in force on match day."""

    elo_home: float
    elo_away: float
    goals_home: int
    goals_away: int
    home_advantage: bool = False
    weight: float = 1.0


class ModelCalibrator:
    """Fits (avg_total_goals, supremacy_beta, dixon_coles_rho,
    home_advantage_elo) by maximizing the log-likelihood of observed
    scorelines given Elo. Reuses the exact model math, so the fitted
    config is plug-and-play."""

    _PARAM_NAMES = ("avg_total_goals", "supremacy_beta", "dixon_coles_rho",
                    "home_advantage_elo")
    _BOUNDS = [(1.5, 4.0), (1e-4, 1e-2), (-0.5, 0.3), (0.0, 150.0)]

    def __init__(self, base: Optional[ModelConfig] = None) -> None:
        self.base = base or ModelConfig()

    def _config_from_theta(self, theta: Sequence[float]) -> ModelConfig:
        total, beta, rho, home_elo = theta
        return replace(
            self.base, avg_total_goals=float(total), supremacy_beta=float(beta),
            dixon_coles_rho=float(rho), home_advantage_elo=float(home_elo),
        )

    def _neg_log_likelihood(
        self, theta: np.ndarray, eh: np.ndarray, ea: np.ndarray,
        gh: np.ndarray, ga: np.ndarray, hadv: np.ndarray, w: np.ndarray,
    ) -> float:
        total, beta, rho, home_elo = theta
        eh_eff = eh + np.where(hadv, home_elo, 0.0)
        supremacy = self.base.max_supremacy * np.tanh(beta * (eh_eff - ea))
        lam_h = np.clip((total + supremacy) / 2.0, self.base.min_lambda, None)
        lam_a = np.clip((total - supremacy) / 2.0, self.base.min_lambda, None)
        p = (poisson.pmf(gh, lam_h) * poisson.pmf(ga, lam_a)
             * dc_tau_vec(gh, ga, lam_h, lam_a, rho))
        return float(-np.sum(w * np.log(np.clip(p, 1e-12, None))))

    @staticmethod
    def time_decay_weights(
        ages_days: Sequence[float], half_life_days: float = 365.0
    ) -> np.ndarray:
        """exp(-xi * age) Dixon-Coles weights; older matches count less."""
        if half_life_days <= 0:
            raise ValueError("half_life_days must be positive.")
        xi = math.log(2) / half_life_days
        return np.exp(-xi * np.asarray(ages_days, dtype=float))

    def fit(self, matches: Sequence[HistoricalMatch]) -> Tuple[ModelConfig, object]:
        if len(matches) < 50:
            logger.warning("Few matches (%d): calibration will be unstable.",
                           len(matches))
        eh = np.array([m.elo_home for m in matches], dtype=float)
        ea = np.array([m.elo_away for m in matches], dtype=float)
        gh = np.array([m.goals_home for m in matches], dtype=int)
        ga = np.array([m.goals_away for m in matches], dtype=int)
        hadv = np.array([m.home_advantage for m in matches], dtype=bool)
        w = np.array([m.weight for m in matches], dtype=float)

        x0 = np.array([getattr(self.base, n) for n in self._PARAM_NAMES], dtype=float)
        res = minimize(
            self._neg_log_likelihood, x0, args=(eh, ea, gh, ga, hadv, w),
            method="L-BFGS-B", bounds=self._BOUNDS,
        )
        if not res.success:
            logger.warning("Optimization did not converge: %s", res.message)
        else:
            logger.info("Calibration OK | -logL=%.1f in %d evaluations.",
                        res.fun, res.nfev)
        return self._config_from_theta(res.x), res


def synthesize_history(
    true_cfg: ModelConfig, elo_pool: Sequence[float],
    n_matches: int = 3000, seed: int = 7,
) -> List[HistoricalMatch]:
    """Sample a synthetic history from the model itself with known parameters,
    to validate that the calibrator recovers the truth. In production this is
    replaced by real results (date, teams, goals, Elo at the time)."""
    rng = np.random.default_rng(seed)
    model = EloPoissonModel(true_cfg)
    pool = np.asarray(elo_pool, dtype=float)

    matches: List[HistoricalMatch] = []
    for _ in range(n_matches):
        eh, ea = rng.choice(pool, size=2, replace=False)
        hadv = bool(rng.random() < 0.55)
        home = TeamProfile("H", float(eh))
        away = TeamProfile("A", float(ea))
        ctx = MatchContext(home_team="H" if hadv else None)
        matrix, _, _ = model.score_matrix(home, away, ctx)
        idx = int(rng.choice(matrix.size, p=matrix.ravel()))
        x, y = divmod(idx, matrix.shape[1])
        matches.append(HistoricalMatch(float(eh), float(ea), x, y, hadv))
    return matches
