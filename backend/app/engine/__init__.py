"""World Cup 2026 prediction engine.

Elo-grounded bivariate Poisson model with Dixon-Coles low-score correction,
blended with xG/xGA tactical profiles, form momentum, injury attrition and
2026-specific environmental context (altitude, WBGT heat burden).
"""

from .adjuster import AdjustmentConfig, apply_results, elo_delta, update_form
from .config import ModelConfig
from .core import MatchContext, ParameterOverrides, TeamProfile, compute_lambdas
from .lineup_analyzer import (
    analyze_lineups,
    build_lineup,
    formation_strength_index,
    optimal_xi,
    positional_battles,
    pressing_intensity,
)
from .player_models import FORMATIONS, POSITIONS, PlayerProfile, Slot
from .player_scorer import player_performance_score, score_squad
from .bracket import (
    feeder_matches,
    knockout_dates,
    load_bracket,
    seeded_r32_from_store,
)
from .predictor import EloPoissonModel, MatchPredictor, MatchPrediction
from .simulator import KnockoutSimulator

__all__ = [
    "AdjustmentConfig",
    "apply_results",
    "elo_delta",
    "update_form",
    "ModelConfig",
    "MatchContext",
    "ParameterOverrides",
    "TeamProfile",
    "compute_lambdas",
    "EloPoissonModel",
    "MatchPredictor",
    "MatchPrediction",
    "KnockoutSimulator",
    "load_bracket",
    "seeded_r32_from_store",
    "knockout_dates",
    "feeder_matches",
    # Player analyzer
    "PlayerProfile",
    "Slot",
    "POSITIONS",
    "FORMATIONS",
    "player_performance_score",
    "score_squad",
    "build_lineup",
    "analyze_lineups",
    "formation_strength_index",
    "positional_battles",
    "pressing_intensity",
    "optimal_xi",
]
