"""Adjusted-metrics provider: base profiles + replayed final results.

Base loaders in engine.loader stay immutably lru_cached; all mutability
lives in results_store.version, which keys the cache here, so every
write to the store invalidates the derivation on the next request
(replaying <= 72 matches is microseconds).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List

from ..engine.adjuster import AdjustmentConfig, apply_results
from ..engine.core import TeamProfile
from ..engine.loader import GROUPS, get_fixtures, load_teams
from .results_store import results_store

ADJ_CFG = AdjustmentConfig()


@lru_cache(maxsize=4)
def _adjusted(version: int) -> Dict[str, TeamProfile]:
    return apply_results(load_teams(), get_fixtures(), results_store.all(), ADJ_CFG)


def get_adjusted_teams() -> Dict[str, TeamProfile]:
    return _adjusted(results_store.version)


def get_adjusted_draw() -> Dict[str, List[TeamProfile]]:
    draw: Dict[str, List[TeamProfile]] = {g: [] for g in GROUPS}
    for profile in get_adjusted_teams().values():
        draw[profile.group].append(profile)
    return draw


def _matches_played() -> Dict[str, int]:
    finals = {
        fid for fid, r in results_store.all().items() if r["status"] == "final"
    }
    counts: Dict[str, int] = {}
    for fixture in get_fixtures():
        if fixture["id"] in finals:
            for side in ("home", "away"):
                counts[fixture[side]] = counts.get(fixture[side], 0) + 1
    return counts


def metrics_report() -> List[dict]:
    """Per-team base vs adjusted Elo/form, sorted by |elo delta| desc."""
    base = load_teams()
    adjusted = get_adjusted_teams()
    played = _matches_played()
    rows = [
        {
            "team": name,
            "group": base[name].group,
            "base_elo": round(base[name].elo, 1),
            "adjusted_elo": round(adj.elo, 1),
            "elo_delta": round(adj.elo - base[name].elo, 1),
            "base_form": round(base[name].form_index, 3),
            "adjusted_form": round(adj.form_index, 3),
            "form_delta": round(adj.form_index - base[name].form_index, 3),
            "matches_played": played.get(name, 0),
        }
        for name, adj in adjusted.items()
    ]
    rows.sort(key=lambda r: abs(r["elo_delta"]), reverse=True)
    return rows
