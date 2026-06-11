"""Model hyperparameters for the WC2026 prediction engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    """Calibratable hyperparameters of the predictive engine.

    Attributes:
        avg_total_goals: Baseline total goals per match in international play.
        max_supremacy: Bound on the Elo-derived expected-goal supremacy (tanh cap).
        supremacy_beta: Slope of the Elo difference -> supremacy mapping.
        home_advantage_elo: Elo bonus granted to a designated home side.
        dixon_coles_rho: Low-score dependency parameter (negative inflates draws).
        min_lambda: Floor on expected goals to avoid degenerate distributions.
        max_goals: Maximum goals per side in the score matrix (matrix is
            (max_goals + 1) x (max_goals + 1)).
        xg_blend_weight: Weight of the xG-cross lambda vs the Elo lambda (0..1).
        form_swing: Amplitude of the form multiplier; form index 0..1 maps to
            a multiplier in [1 - swing/2, 1 + swing/2].
        injury_attack_weight: Attack output lost at injury_impact = 1.0.
        injury_defense_weight: Defensive vulnerability gained at injury_impact = 1.0.
        altitude_threshold_m: Altitude above which hypoxic penalties apply.
        altitude_max_penalty: Maximum attacking penalty from altitude strain.
        heat_penalty_per_index: Attacking penalty per unit of heat index (0..2).
    """

    avg_total_goals: float = 2.72
    max_supremacy: float = 3.00
    supremacy_beta: float = 0.0018
    home_advantage_elo: float = 65.0
    dixon_coles_rho: float = -0.13
    min_lambda: float = 0.15
    max_goals: int = 8
    xg_blend_weight: float = 0.45
    form_swing: float = 0.20
    injury_attack_weight: float = 0.30
    injury_defense_weight: float = 0.30
    altitude_threshold_m: float = 1500.0
    altitude_max_penalty: float = 0.08
    heat_penalty_per_index: float = 0.05

    def __post_init__(self) -> None:
        if not (-1.0 < self.dixon_coles_rho < 1.0):
            raise ValueError("dixon_coles_rho must lie in (-1, 1).")
        if self.max_goals < 4:
            raise ValueError("max_goals too low for a useful score matrix.")
        if not (0.0 <= self.xg_blend_weight <= 1.0):
            raise ValueError("xg_blend_weight must lie in [0, 1].")
        if self.min_lambda <= 0:
            raise ValueError("min_lambda must be strictly positive.")
