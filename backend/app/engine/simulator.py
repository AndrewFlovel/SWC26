"""Monte Carlo simulation of the 2026 group stage: single groups with FIFA
tiebreakers and the full 12-group tournament with the best-8-thirds rule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .core import MatchContext, TeamProfile
from .predictor import EloPoissonModel


@dataclass
class GroupRecord:
    name: str
    pts: int
    gf: int
    ga: int
    elo: float

    @property
    def gd(self) -> int:
        return self.gf - self.ga


class MonteCarloSimulator:
    """Simulates a 4-team group with FIFA tiebreakers via CDF sampling."""

    def __init__(self, model: EloPoissonModel, seed: int = 2026) -> None:
        self.model = model
        self._rng = np.random.default_rng(seed)
        self._cdf_cache: Dict[Tuple[str, str], Tuple[np.ndarray, int]] = {}

    def _cdf(self, home: TeamProfile, away: TeamProfile) -> Tuple[np.ndarray, int]:
        """Cached cumulative scoreline distribution for O(log n) sampling."""
        key = (home.name, away.name)
        if key not in self._cdf_cache:
            host = None
            if home.is_host ^ away.is_host:
                host = home.name if home.is_host else away.name
            matrix, _, _ = self.model.score_matrix(
                home, away, MatchContext(home_team=host)
            )
            self._cdf_cache[key] = (np.cumsum(matrix.ravel()), matrix.shape[1])
        return self._cdf_cache[key]

    def _sample_score(self, home: TeamProfile, away: TeamProfile) -> Tuple[int, int]:
        cdf, ncols = self._cdf(home, away)
        idx = int(np.searchsorted(cdf, self._rng.random()))
        idx = min(idx, cdf.size - 1)
        return divmod(idx, ncols)

    @staticmethod
    def _rank_records(
        teams: Sequence[TeamProfile],
        results: Dict[Tuple[str, str], Tuple[int, int]],
    ) -> List[GroupRecord]:
        """Rank a group: points -> goal difference -> goals for -> head-to-head -> Elo."""
        stats = {t.name: GroupRecord(t.name, 0, 0, 0, t.elo) for t in teams}
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

        def base_key(r: GroupRecord) -> Tuple[int, int, int]:
            return (r.pts, r.gd, r.gf)

        order = sorted(stats.values(), key=base_key, reverse=True)
        final: List[GroupRecord] = []
        i = 0
        while i < len(order):
            block = [order[i]]
            j = i + 1
            while j < len(order) and base_key(order[j]) == base_key(order[i]):
                block.append(order[j])
                j += 1
            if len(block) > 1:
                names = [r.name for r in block]
                block.sort(key=lambda r: (h2h(r.name, names), r.elo), reverse=True)
            final.extend(block)
            i = j
        return final

    def simulate_group_once(
        self,
        teams: Sequence[TeamProfile],
        fixed_results: Optional[Dict[Tuple[str, str], Tuple[int, int]]] = None,
    ) -> List[GroupRecord]:
        """Pairs present in fixed_results use the recorded score instead of
        sampling, conditioning the simulation on already-played matches."""
        if len(teams) != 4:
            raise ValueError("A 2026 World Cup group has exactly 4 teams.")
        fixed = fixed_results or {}
        pairs = [(teams[i], teams[j]) for i in range(4) for j in range(i + 1, 4)]
        results = {
            (h.name, a.name): fixed.get((h.name, a.name)) or self._sample_score(h, a)
            for h, a in pairs
        }
        return self._rank_records(teams, results)

    def simulate_group(
        self,
        teams: Sequence[TeamProfile],
        n_sims: int = 10_000,
        fixed_results: Optional[Dict[Tuple[str, str], Tuple[int, int]]] = None,
    ) -> List[dict]:
        """Run the group n_sims times; returns per-team qualification stats."""
        if n_sims <= 0:
            raise ValueError("n_sims must be positive.")
        names = [t.name for t in teams]
        tally = {n: {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "pts": 0} for n in names}
        for _ in range(n_sims):
            ranked = self.simulate_group_once(teams, fixed_results)
            for pos, rec in enumerate(ranked, start=1):
                tally[rec.name][f"P{pos}"] += 1
                tally[rec.name]["pts"] += rec.pts
        rows = [
            {
                "team": n,
                "win_group_pct": round(100 * tally[n]["P1"] / n_sims, 1),
                "second_pct": round(100 * tally[n]["P2"] / n_sims, 1),
                "top2_pct": round(100 * (tally[n]["P1"] + tally[n]["P2"]) / n_sims, 1),
                "third_pct": round(100 * tally[n]["P3"] / n_sims, 1),
                "avg_points": round(tally[n]["pts"] / n_sims, 2),
            }
            for n in names
        ]
        rows.sort(key=lambda r: r["top2_pct"], reverse=True)
        return rows


class TournamentSimulator:
    """Simulates all 12 groups and the qualification of the 8 best thirds
    (FIFA criteria: points -> goal difference -> goals for -> Elo proxy)."""

    def __init__(
        self,
        model: EloPoissonModel,
        draw: Dict[str, List[TeamProfile]],
        seed: int = 2026,
    ) -> None:
        if len(draw) != 12:
            raise ValueError("The 2026 World Cup has exactly 12 groups.")
        self.mc = MonteCarloSimulator(model, seed=seed)
        self.draw = draw

    def simulate(self, n_sims: int = 10_000) -> List[dict]:
        if n_sims <= 0:
            raise ValueError("n_sims must be positive.")
        all_names = [t.name for g in self.draw.values() for t in g]
        tally = {
            n: {"P1": 0, "q_top2": 0, "q_third": 0, "qualified": 0}
            for n in all_names
        }

        for _ in range(n_sims):
            thirds: List[GroupRecord] = []
            for teams in self.draw.values():
                ranked = self.mc.simulate_group_once(teams)
                for pos, rec in enumerate(ranked, start=1):
                    if pos == 1:
                        tally[rec.name]["P1"] += 1
                    if pos <= 2:
                        tally[rec.name]["q_top2"] += 1
                        tally[rec.name]["qualified"] += 1
                thirds.append(ranked[2])
            thirds.sort(key=lambda r: (r.pts, r.gd, r.gf, r.elo), reverse=True)
            for rec in thirds[:8]:
                tally[rec.name]["q_third"] += 1
                tally[rec.name]["qualified"] += 1

        rows = []
        for g, teams in self.draw.items():
            for t in teams:
                d = tally[t.name]
                rows.append({
                    "group": g,
                    "team": t.name,
                    "elo": int(t.elo),
                    "win_group_pct": round(100 * d["P1"] / n_sims, 1),
                    "top2_pct": round(100 * d["q_top2"] / n_sims, 1),
                    "best_third_pct": round(100 * d["q_third"] / n_sims, 1),
                    "qualify_r32_pct": round(100 * d["qualified"] / n_sims, 1),
                })
        rows.sort(key=lambda r: r["qualify_r32_pct"], reverse=True)
        return rows
