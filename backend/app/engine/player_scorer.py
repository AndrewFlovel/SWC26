"""Player Performance Score (PPS): a single role-weighted rating in [0, 1].

Each raw statistic is normalized against a fixed reference distribution (elite-
football per-90 / percentage anchors) rather than against the current sample, so
a player's score is absolute and stable even when only the two squads of one
fixture have been scraped. Component scores use weighted arithmetic means (not
geometric) so a single zero input — e.g. a defender's xG — never collapses the
whole score, avoiding the degenerate outputs the project guards against.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from .player_models import PlayerProfile

# metric -> (value mapped to 0.0, value mapped to 1.0); clamped to [0, 1].
REFERENCE_RANGES: Dict[str, Tuple[float, float]] = {
    "xg90": (0.0, 0.80),
    "xa90": (0.0, 0.50),
    "shots90": (0.0, 4.0),
    "progressive_passes90": (0.0, 8.0),
    "shot_creating_actions90": (0.0, 5.0),
    "dribbles_completed90": (0.0, 3.0),
    "tackles_won_pct": (40.0, 75.0),
    "interceptions90": (0.0, 2.5),
    "clearances90": (0.0, 6.0),
    "pressures90": (0.0, 25.0),
    "pressures_won_pct": (20.0, 40.0),
    "aerial_won_pct": (30.0, 75.0),
}

# Sub-weights within each facet (need not sum to 1; the mean normalizes).
ATT_WEIGHTS: Dict[str, float] = {
    "xg90": 0.28, "xa90": 0.22, "shot_creating_actions90": 0.20,
    "progressive_passes90": 0.15, "shots90": 0.08, "dribbles_completed90": 0.07,
}
DEF_WEIGHTS: Dict[str, float] = {
    "tackles_won_pct": 0.26, "interceptions90": 0.24, "clearances90": 0.18,
    "pressures_won_pct": 0.18, "aerial_won_pct": 0.14,
}
PHYS_WEIGHTS: Dict[str, float] = {
    "pressures90": 0.6, "dribbles_completed90": 0.4,
}

# Role weighting of the three facets: (w_att, w_def, w_phys), each summing to 1.
ROLE_WEIGHTS: Dict[str, Tuple[float, float, float]] = {
    "GK": (0.05, 0.85, 0.10),
    "CB": (0.10, 0.80, 0.10),
    "LB": (0.25, 0.55, 0.20),
    "RB": (0.25, 0.55, 0.20),
    "CDM": (0.20, 0.65, 0.15),
    "CM": (0.40, 0.40, 0.20),
    "CAM": (0.65, 0.20, 0.15),
    "LW": (0.75, 0.10, 0.15),
    "RW": (0.75, 0.10, 0.15),
    "ST": (0.85, 0.05, 0.10),
}


def normalize(metric: str, value: float) -> float:
    """Map a raw metric onto [0, 1] via its reference anchors."""
    lo, hi = REFERENCE_RANGES[metric]
    if hi <= lo:  # defensive guard; the table never violates this
        return 0.0
    z = (value - lo) / (hi - lo)
    return min(max(z, 0.0), 1.0)


def _weighted_mean(player: PlayerProfile, weights: Dict[str, float]) -> float:
    """Weighted arithmetic mean of normalized metrics; guards sum(weights) > 0."""
    total_w = 0.0
    acc = 0.0
    for metric, w in weights.items():
        if w <= 0:
            continue
        acc += w * normalize(metric, getattr(player, metric))
        total_w += w
    return acc / total_w if total_w > 0 else 0.0


def facet_scores(player: PlayerProfile) -> Tuple[float, float, float]:
    """(attack, defense, physical) facet scores, each in [0, 1]."""
    return (
        _weighted_mean(player, ATT_WEIGHTS),
        _weighted_mean(player, DEF_WEIGHTS),
        _weighted_mean(player, PHYS_WEIGHTS),
    )


def player_performance_score(player: PlayerProfile) -> float:
    """Role-weighted composite rating in [0, 1]."""
    att, dfn, phys = facet_scores(player)
    w_att, w_def, w_phys = ROLE_WEIGHTS[player.position]
    pps = w_att * att + w_def * dfn + w_phys * phys
    return min(max(pps, 0.0), 1.0)


def score_squad(players: Iterable[PlayerProfile]) -> List[PlayerProfile]:
    """Fill `pps` on each player in place and return them as a list."""
    out: List[PlayerProfile] = []
    for p in players:
        p.pps = round(player_performance_score(p), 4)
        out.append(p)
    return out
