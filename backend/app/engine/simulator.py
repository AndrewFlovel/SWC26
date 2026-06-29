"""Monte Carlo simulation of the 2026 group stage: single groups with FIFA
tiebreakers and the full 12-group tournament with the best-8-thirds rule, plus
the knockout bracket (R32 -> final) with decisive single-elimination ties."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import bracket
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
        # Knockout ties run on a neutral context (no host edge); cache holds the
        # neutral CDF plus the home win-share conditional on a decisive result.
        self._ko_cache: Dict[Tuple[str, str], Tuple[np.ndarray, int, float]] = {}

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

    def _ko_cdf(
        self, home: TeamProfile, away: TeamProfile
    ) -> Tuple[np.ndarray, int, float]:
        """Neutral-venue CDF plus the home team's win probability conditional on
        a decisive result (used to settle level knockout ties)."""
        key = (home.name, away.name)
        if key not in self._ko_cache:
            matrix, _, _ = self.model.score_matrix(home, away)
            p_home = float(np.tril(matrix, -1).sum())
            p_away = float(np.triu(matrix, 1).sum())
            decisive = p_home + p_away
            split = p_home / decisive if decisive > 0 else 0.5
            self._ko_cache[key] = (np.cumsum(matrix.ravel()), matrix.shape[1], split)
        return self._ko_cache[key]

    def _resolve_knockout(
        self, home: TeamProfile, away: TeamProfile
    ) -> Tuple[str, str]:
        """Play a single-elimination tie to a decisive (winner, loser).

        A level scoreline is settled as extra time / penalties: a coin flip
        weighted by each side's strength (its win share given the match was
        decided), so the stronger team is favoured but upsets remain possible.
        """
        cdf, ncols, split = self._ko_cdf(home, away)
        idx = min(int(np.searchsorted(cdf, self._rng.random())), cdf.size - 1)
        gh, ga = divmod(idx, ncols)
        if gh > ga:
            return home.name, away.name
        if ga > gh:
            return away.name, home.name
        if self._rng.random() < split:
            return home.name, away.name
        return away.name, home.name

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


# Per-round flag: which match-number block a winner of that block has reached.
_ROUND_OF = {
    "reach_qf": range(89, 97),    # won an R16 tie
    "reach_sf": range(97, 101),   # won a quarterfinal
    "reach_final": range(101, 103),  # won a semifinal
}


class KnockoutSimulator:
    """Plays the official FIFA 2026 bracket (R32 -> final) every iteration and
    tallies how deep each team runs: reach R16/QF/SF/final and win the title.

    Each run simulates the 12 groups (optionally conditioned on already-played
    results), qualifies the 12 winners, 12 runners-up and 8 best thirds, seeds
    them into the published bracket and resolves every tie decisively.
    """

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
        self._by_name = {t.name: t for teams in draw.values() for t in teams}

    def _settle(
        self, match: int, home: str, away: str, fixed_ko: Dict[int, str]
    ) -> Tuple[str, str]:
        """Winner/loser of one tie: the actual result when the match is in
        `fixed_ko` (and its winner is one of these two teams), else simulated."""
        forced = fixed_ko.get(match)
        if forced in (home, away):
            return forced, (away if forced == home else home)
        return self.mc._resolve_knockout(self._by_name[home], self._by_name[away])

    def _play_bracket(
        self,
        seeded: Dict[int, Tuple[str, str]],
        fixed_ko: Optional[Dict[int, str]] = None,
    ) -> Tuple[Dict[int, str], Dict[int, str]]:
        """Resolve R32 then the tree; return winners and losers by match.
        Matches present in `fixed_ko` are locked to their recorded winner."""
        fixed_ko = fixed_ko or {}
        winners: Dict[int, str] = {}
        losers: Dict[int, str] = {}
        for match, (home, away) in seeded.items():
            winners[match], losers[match] = self._settle(match, home, away, fixed_ko)

        def team(ref: str) -> str:
            src = winners if ref[0] == "W" else losers
            return src[int(ref[1:])]

        for tie in bracket.load_bracket()["tree"]:
            home, away = team(tie["home"]), team(tie["away"])
            winners[tie["match"]], losers[tie["match"]] = self._settle(
                tie["match"], home, away, fixed_ko
            )
        return winners, losers

    def simulate(
        self,
        n_sims: int = 5_000,
        fixed_results: Optional[Dict[str, Dict[Tuple[str, str], Tuple[int, int]]]] = None,
        fixed_ko: Optional[Dict[int, str]] = None,
    ) -> List[dict]:
        if n_sims <= 0:
            raise ValueError("n_sims must be positive.")
        fixed = fixed_results or {}
        fixed_ko = fixed_ko or {}
        tally = {
            n: {"reach_r16": 0, "reach_qf": 0, "reach_sf": 0,
                "reach_final": 0, "champion": 0}
            for n in self._by_name
        }

        for _ in range(n_sims):
            group_order: Dict[str, List[str]] = {}
            thirds: List[GroupRecord] = []
            for g, teams in self.draw.items():
                ranked = self.mc.simulate_group_once(teams, fixed.get(g) or None)
                group_order[g] = [r.name for r in ranked]
                thirds.append(ranked[2])
            thirds.sort(key=lambda r: (r.pts, r.gd, r.gf, r.elo), reverse=True)
            qualified = [self._by_name[r.name].group for r in thirds[:8]]

            seeded = bracket.seed_r32(group_order, qualified)
            winners, _ = self._play_bracket(seeded, fixed_ko)

            for match, name in winners.items():
                if match <= 88:
                    tally[name]["reach_r16"] += 1
                elif match in _ROUND_OF["reach_qf"]:
                    tally[name]["reach_qf"] += 1
                elif match in _ROUND_OF["reach_sf"]:
                    tally[name]["reach_sf"] += 1
                elif match in _ROUND_OF["reach_final"]:
                    tally[name]["reach_final"] += 1
            tally[winners[104]]["champion"] += 1

        rows = [
            {
                "team": name,
                "group": self._by_name[name].group,
                "elo": int(self._by_name[name].elo),
                "reach_r16": round(100 * d["reach_r16"] / n_sims, 1),
                "reach_qf": round(100 * d["reach_qf"] / n_sims, 1),
                "reach_sf": round(100 * d["reach_sf"] / n_sims, 1),
                "reach_final": round(100 * d["reach_final"] / n_sims, 1),
                "champion": round(100 * d["champion"] / n_sims, 1),
            }
            for name, d in tally.items()
        ]
        rows.sort(key=lambda r: (r["champion"], r["reach_final"]), reverse=True)
        return rows
