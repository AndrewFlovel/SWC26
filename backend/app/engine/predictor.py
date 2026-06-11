"""Analytic match prediction: score matrix, outcome probabilities and
most probable scorelines for a single fixture."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple

import numpy as np
from scipy.stats import poisson

from .config import ModelConfig
from .core import MatchContext, ParameterOverrides, TeamProfile, compute_lambdas, dc_tau


class EloPoissonModel:
    """Bivariate Poisson + Dixon-Coles score-matrix generator."""

    def __init__(self, config: Optional[ModelConfig] = None) -> None:
        self.cfg = config or ModelConfig()

    def score_matrix(
        self,
        home: TeamProfile,
        away: TeamProfile,
        ctx: Optional[MatchContext] = None,
        overrides: Optional[ParameterOverrides] = None,
    ) -> Tuple[np.ndarray, float, float]:
        """Return the normalized joint scoreline probability matrix.

        Returns:
            (matrix, lambda_home, lambda_away) where matrix[i, j] is the
            probability of a home i - j away final score.
        """
        cfg = self.cfg
        if overrides is not None and overrides.rho is not None:
            rho = min(max(overrides.rho, -0.99), 0.99)
            cfg = replace(cfg, dixon_coles_rho=rho)

        lam_h, lam_a = compute_lambdas(home, away, cfg, ctx, overrides)
        n = cfg.max_goals + 1
        goals = np.arange(n)
        matrix = np.outer(poisson.pmf(goals, lam_h), poisson.pmf(goals, lam_a))
        for x in (0, 1):
            for y in (0, 1):
                matrix[x, y] *= dc_tau(x, y, lam_h, lam_a, cfg.dixon_coles_rho)
        matrix = np.clip(matrix, 0.0, None)
        total = matrix.sum()
        if total <= 0:
            raise RuntimeError("Degenerate score matrix (sum <= 0).")
        return matrix / total, lam_h, lam_a


@dataclass
class MatchPrediction:
    home: str
    away: str
    lambda_home: float
    lambda_away: float
    p_home: float
    p_draw: float
    p_away: float
    top_scorelines: List[Tuple[str, float]]
    matrix: np.ndarray = field(repr=False)


class MatchPredictor:
    """High-level wrapper producing user-facing prediction summaries."""

    def __init__(self, model: EloPoissonModel) -> None:
        self.model = model

    def predict(
        self,
        home: TeamProfile,
        away: TeamProfile,
        ctx: Optional[MatchContext] = None,
        overrides: Optional[ParameterOverrides] = None,
        top_n: int = 5,
    ) -> MatchPrediction:
        matrix, lam_h, lam_a = self.model.score_matrix(home, away, ctx, overrides)
        flat = [
            (f"{i}-{j}", float(matrix[i, j]))
            for i in range(matrix.shape[0])
            for j in range(matrix.shape[1])
        ]
        flat.sort(key=lambda kv: kv[1], reverse=True)
        return MatchPrediction(
            home=home.name,
            away=away.name,
            lambda_home=round(lam_h, 3),
            lambda_away=round(lam_a, 3),
            p_home=round(float(np.tril(matrix, -1).sum()), 4),
            p_draw=round(float(np.trace(matrix)), 4),
            p_away=round(float(np.triu(matrix, 1).sum()), 4),
            top_scorelines=[(s, round(p, 4)) for s, p in flat[:top_n]],
            matrix=matrix,
        )
