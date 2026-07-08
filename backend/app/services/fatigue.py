"""Heuristic fatigue/attrition state derived from played games.

Observable inputs only: match dates (group fixture dates plus the static
knockout schedule, or a per-record scraped date), penalty shootouts (recorded
pens => the game ran 120 minutes) and cumulative match load. The output is a
bounded score in [0, 1] consumed by the engine as
``ParameterOverrides.home_fatigue`` / ``away_fatigue``.

Fatigue is *as-of* a target match date: only games strictly before it count,
so the same computation is correct for already-played ties (the pre-kickoff
view) and future ones. Limitations, by construction: extra time without a
shootout is indistinguishable from 90 minutes (the feed has no minutes
played), and simulated future ties contribute no extra-time burden.

Same caching scheme as metrics.py: the stores' version counters key the
lru_cache, so every write invalidates the derivation on the next request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from ..engine.bracket import feeder_matches, knockout_dates
from ..engine.core import ParameterOverrides
from ..engine.loader import get_fixtures
from .knockout_store import knockout_store
from .results_store import results_store


@dataclass(frozen=True)
class FatigueConfig:
    """Weights of the fatigue heuristic (components sum to at most 1.0)."""

    full_rest_days: float = 5.0     # >= this many rest days => no deficit
    min_rest_days: float = 2.0      # <= this floor => maximal deficit
    rest_weight: float = 0.60       # share of the score from missing rest
    extra_time_weight: float = 0.25  # last game ran 120 minutes (+ pens)
    load_weight: float = 0.15       # cumulative-matches component
    baseline_matches: int = 3       # every team plays 3 group games
    max_extra_matches: int = 4      # deepest knockout run before the final


FATIGUE_CFG = FatigueConfig()

# Match number -> knockout depth (R32=0 .. SF/3P/F deepest).
_ROUND_DEPTH: Dict[int, int] = {
    **{m: 0 for m in range(73, 89)},
    **{m: 1 for m in range(89, 97)},
    **{m: 2 for m in range(97, 101)},
    101: 3, 102: 3, 103: 4, 104: 4,
}


def _clamp(x: float) -> float:
    return min(max(x, 0.0), 1.0)


@lru_cache(maxsize=8)
def _histories(
    rs_version: int, ks_version: int
) -> Dict[str, List[Tuple[date, bool]]]:
    """team -> date-sorted [(match_date, went_extra_time)] over all FINAL
    group results and FINAL knockout records."""
    histories: Dict[str, List[Tuple[date, bool]]] = {}
    stored = results_store.all()
    for f in get_fixtures():
        rec = stored.get(f["id"])
        if not rec or rec["status"] != "final":
            continue
        played = date.fromisoformat(f["date"])
        for side in ("home", "away"):
            histories.setdefault(f[side], []).append((played, False))
    schedule = knockout_dates()
    for key, rec in knockout_store.all().items():
        if rec["status"] != "final":
            continue
        iso = rec.get("date") or schedule[int(key)]
        played = date.fromisoformat(iso)
        went_et = rec["pens_home"] is not None and rec["pens_away"] is not None
        for side in ("home", "away"):
            histories.setdefault(rec[side], []).append((played, went_et))
    for games in histories.values():
        games.sort()
    return histories


def team_histories() -> Dict[str, List[Tuple[date, bool]]]:
    return _histories(results_store.version, knockout_store.version)


def fatigue_index(
    history: List[Tuple[date, bool]],
    match_date: date,
    feeder_date: Optional[date],
    round_depth: int,
    cfg: FatigueConfig = FATIGUE_CFG,
) -> float:
    """Fatigue in [0, 1] for one team going into a match on `match_date`.

    Only games strictly before the match count. The previous outing is the
    later of the team's last real game and its feeder tie's scheduled date
    (a team reaching this round must have played the feeder, even when that
    result is not recorded yet); the extra-time surcharge applies only when
    the most recent REAL game is that immediately preceding outing.
    """
    played = [(d, et) for d, et in history if d < match_date]

    last_real: Optional[date] = played[-1][0] if played else None
    prev = max(
        (d for d in (last_real, feeder_date) if d is not None), default=None
    )
    if prev is None:
        rest_deficit = 0.0
    else:
        rest_days = (match_date - prev).days
        rest_deficit = _clamp(
            (cfg.full_rest_days - rest_days)
            / (cfg.full_rest_days - cfg.min_rest_days)
        )

    et_flag = 1.0 if played and played[-1][1] and played[-1][0] == prev else 0.0

    # max(...) gives deep simulated rounds an implied load before results exist.
    extra = max(len(played), cfg.baseline_matches + round_depth) - cfg.baseline_matches
    load = _clamp(extra / cfg.max_extra_matches)

    return round(
        _clamp(
            cfg.rest_weight * rest_deficit
            + cfg.extra_time_weight * et_flag
            + cfg.load_weight * load
        ),
        3,
    )


def knockout_fatigue(match: int, home: str, away: str) -> ParameterOverrides:
    """Fatigue overrides for one knockout tie, as-of its scheduled date.

    The match date is the scraped record's own date when present, else the
    static schedule. Feeder dates cover teams whose qualifying tie is not
    recorded yet (simulated brackets)."""
    rec = knockout_store.get(match)
    iso = (rec.get("date") if rec else None) or knockout_dates()[match]
    match_date = date.fromisoformat(iso)
    depth = _ROUND_DEPTH.get(match, 0)

    schedule = knockout_dates()
    feeders = feeder_matches().get(match, (None, None))
    histories = team_histories()

    def side(team: str, feeder: Optional[int]) -> float:
        feeder_date = (
            date.fromisoformat(schedule[feeder]) if feeder is not None else None
        )
        return fatigue_index(
            histories.get(team, []), match_date, feeder_date, depth
        )

    return ParameterOverrides(
        home_fatigue=side(home, feeders[0]),
        away_fatigue=side(away, feeders[1]),
    )
