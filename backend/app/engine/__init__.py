"""World Cup 2026 prediction engine.

Elo-grounded bivariate Poisson model with Dixon-Coles low-score correction,
blended with xG/xGA tactical profiles, form momentum, injury attrition and
2026-specific environmental context (altitude, WBGT heat burden).
"""

from .config import ModelConfig
from .core import MatchContext, ParameterOverrides, TeamProfile, compute_lambdas
from .predictor import EloPoissonModel, MatchPredictor, MatchPrediction
from .simulator import MonteCarloSimulator, TournamentSimulator

__all__ = [
    "ModelConfig",
    "MatchContext",
    "ParameterOverrides",
    "TeamProfile",
    "compute_lambdas",
    "EloPoissonModel",
    "MatchPredictor",
    "MatchPrediction",
    "MonteCarloSimulator",
    "TournamentSimulator",
]
