"""Real final group standings from stored results, and the R32 seeding they
imply.

Once every group's six matches are final in the results store, the final
standings are fully determined (FIFA tiebreakers: points -> goal difference ->
goals for -> head-to-head among the tied block -> Elo as a deterministic
last resort) and the bracket template's slot codes can be decoded into the
real Round-of-32 draw. Scraped knockout records always take precedence — the
derived seeding only fills slots the scraper hasn't provided.

Same caching scheme as metrics.py: results_store.version keys the lru_cache,
so every write to the store invalidates the derivation on the next request.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from ..engine.bracket import seed_r32, seeded_r32_from_store
from ..engine.loader import get_fixtures, load_teams
from .results_store import results_store

_PairResults = Dict[Tuple[str, str], Tuple[int, int]]


@dataclass
class _Record:
    name: str
    elo: float
    pts: int = 0
    gf: int = 0
    ga: int = 0

    @property
    def gd(self) -> int:
        return self.gf - self.ga


def _rank_group(
    names: List[str], results: _PairResults, elo: Dict[str, float]
) -> List[_Record]:
    """Rank a group: points -> goal difference -> goals for -> head-to-head -> Elo."""
    stats = {n: _Record(n, elo=elo[n]) for n in names}
    for (h, a), (gh, ga) in results.items():
        stats[h].gf += gh
        stats[h].ga += ga
        stats[a].gf += ga
        stats[a].ga += gh
        if gh > ga:
            stats[h].pts += 3
        elif gh < ga:
            stats[a].pts += 3
        else:
            stats[h].pts += 1
            stats[a].pts += 1

    def h2h(name: str, tied: List[str]) -> int:
        pts = 0
        for (h, a), (gh, ga) in results.items():
            if h == name and a in tied:
                pts += 3 if gh > ga else (1 if gh == ga else 0)
            elif a == name and h in tied:
                pts += 3 if ga > gh else (1 if gh == ga else 0)
        return pts

    def base_key(r: _Record) -> Tuple[int, int, int]:
        return (r.pts, r.gd, r.gf)

    order = sorted(stats.values(), key=base_key, reverse=True)
    final: List[_Record] = []
    i = 0
    while i < len(order):
        block = [order[i]]
        j = i + 1
        while j < len(order) and base_key(order[j]) == base_key(order[i]):
            block.append(order[j])
            j += 1
        if len(block) > 1:
            names_tied = [r.name for r in block]
            block.sort(key=lambda r: (h2h(r.name, names_tied), r.elo), reverse=True)
        final.extend(block)
        i = j
    return final


@lru_cache(maxsize=4)
def _computed(version: int) -> Optional[Tuple[Dict[str, List[str]], Tuple[str, ...]]]:
    """(group -> ranked team names, the 8 best-third group letters), or None
    while any group match is still unplayed — the best-thirds comparison is
    only meaningful once all 12 groups are complete."""
    stored = results_store.all()
    names: Dict[str, List[str]] = {}
    by_group: Dict[str, _PairResults] = {}
    for f in get_fixtures():
        rec = stored.get(f["id"])
        if not rec or rec["status"] != "final":
            return None
        by_group.setdefault(f["group"], {})[(f["home"], f["away"])] = (
            rec["goals_home"], rec["goals_away"],
        )
        group_names = names.setdefault(f["group"], [])
        for side in ("home", "away"):
            if f[side] not in group_names:
                group_names.append(f[side])

    elo = {name: t.elo for name, t in load_teams().items()}
    ranked = {g: _rank_group(names[g], by_group[g], elo) for g in sorted(by_group)}
    # FIFA best-thirds criteria: points -> goal difference -> goals for -> Elo proxy.
    thirds = sorted(
        ranked, key=lambda g: (
            ranked[g][2].pts, ranked[g][2].gd, ranked[g][2].gf, ranked[g][2].elo,
        ),
        reverse=True,
    )
    standings = {g: [r.name for r in recs] for g, recs in ranked.items()}
    return standings, tuple(thirds[:8])


def group_standings() -> Optional[Dict[str, List[str]]]:
    """group letter -> final standings order, or None while incomplete."""
    computed = _computed(results_store.version)
    return computed[0] if computed else None


def qualified_thirds() -> Optional[Tuple[str, ...]]:
    """The 8 group letters whose third-placed team advances, best first."""
    computed = _computed(results_store.version)
    return computed[1] if computed else None


def real_r32_seeding(
    store_records: Dict[str, dict],
) -> Dict[int, Tuple[Optional[str], Optional[str]]]:
    """R32 seeding from scraped knockout records, falling back to the draw
    implied by the real group standings for any slot not scraped yet. Slots
    resolvable by neither source stay ``(None, None)`` (pending)."""
    seeded = seeded_r32_from_store(store_records)
    if all(pair != (None, None) for pair in seeded.values()):
        return seeded
    computed = _computed(results_store.version)
    if computed is None:
        return seeded
    derived = seed_r32(*computed)
    return {
        match: pair if pair != (None, None) else derived[match]
        for match, pair in seeded.items()
    }
