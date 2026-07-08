"""Monte Carlo simulation of the 2026 knockout bracket (R32 -> final).

The group stage has been retired: the Round of 32 is seeded directly from
scraped real results (the knockout store) rather than from simulated group
standings. This module plays the published bracket many times over the *known*
R32 ties, resolving undecided ties decisively (extra time / penalties via a
strength-weighted coin flip) and locking already-played ties to their recorded
winners, to tally how deep each team runs.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

import numpy as np

from . import bracket
from .core import ParameterOverrides, TeamProfile
from .predictor import EloPoissonModel

# Per-round flag: which match-number block a winner of that block has reached.
_ROUND_OF = {
    "reach_qf": range(89, 97),       # won an R16 tie
    "reach_sf": range(97, 101),      # won a quarterfinal
    "reach_final": range(101, 103),  # won a semifinal
}


class KnockoutSimulator:
    """Plays the official FIFA 2026 bracket (R32 -> final) every iteration and
    tallies how deep each team runs: reach R16/QF/SF/final and win the title.

    The R32 is seeded from scraped results; ties with no scraped matchup yet are
    *pending* and are skipped (they and everything downstream of them stay
    unresolved until the real draw is scraped). Undecided ties are resolved on a
    neutral context; ties present in ``fixed_ko`` are locked to their recorded
    winner.

    ``fatigue_fn`` (match number, home, away) -> ParameterOverrides optionally
    shapes each tie's score distribution with per-team fatigue (rest days from
    the schedule, real extra-time/shootout burden from the stores). Extra time
    arising in *simulated* ties is deliberately not fed back. ``None`` keeps
    every tie on the neutral baseline.
    """

    def __init__(
        self,
        model: EloPoissonModel,
        teams: Dict[str, TeamProfile],
        seed: int = 2026,
        fatigue_fn: Optional[
            Callable[[int, str, str], ParameterOverrides]
        ] = None,
    ) -> None:
        self.model = model
        self._by_name = dict(teams)
        self._rng = np.random.default_rng(seed)
        self._fatigue_fn = fatigue_fn
        # Per-tie CDF plus the home win-share conditional on a decisive
        # result; keyed by match so per-match fatigue never bleeds across ties.
        self._ko_cache: Dict[
            Tuple[int, str, str], Tuple[np.ndarray, int, float]
        ] = {}

    def _ko_cdf(
        self, home: TeamProfile, away: TeamProfile, match: int
    ) -> Tuple[np.ndarray, int, float]:
        """Neutral-venue CDF plus the home team's win probability conditional on
        a decisive result (used to settle level knockout ties)."""
        key = (match, home.name, away.name)
        if key not in self._ko_cache:
            overrides = (
                self._fatigue_fn(match, home.name, away.name)
                if self._fatigue_fn
                else None
            )
            matrix, _, _ = self.model.score_matrix(home, away, overrides=overrides)
            p_home = float(np.tril(matrix, -1).sum())
            p_away = float(np.triu(matrix, 1).sum())
            decisive = p_home + p_away
            split = p_home / decisive if decisive > 0 else 0.5
            self._ko_cache[key] = (np.cumsum(matrix.ravel()), matrix.shape[1], split)
        return self._ko_cache[key]

    def _resolve_knockout(self, home: str, away: str, match: int) -> Tuple[str, str]:
        """Play a single-elimination tie to a decisive (winner, loser).

        A level scoreline is settled as extra time / penalties: a coin flip
        weighted by each side's strength (its win share given the match was
        decided), so the stronger team is favoured but upsets remain possible.
        """
        cdf, ncols, split = self._ko_cdf(
            self._by_name[home], self._by_name[away], match
        )
        idx = min(int(np.searchsorted(cdf, self._rng.random())), cdf.size - 1)
        gh, ga = divmod(idx, ncols)
        if gh > ga:
            return home, away
        if ga > gh:
            return away, home
        if self._rng.random() < split:
            return home, away
        return away, home

    def _settle(
        self,
        match: int,
        home: Optional[str],
        away: Optional[str],
        fixed_ko: Dict[int, str],
    ) -> Optional[Tuple[str, str]]:
        """Winner/loser of one tie, or ``None`` when a team is still unknown
        (pending R32 slot, or an unresolved upstream tie). A recorded winner in
        ``fixed_ko`` locks the result; otherwise the tie is simulated."""
        if home is None or away is None:
            return None
        forced = fixed_ko.get(match)
        if forced in (home, away):
            return forced, (away if forced == home else home)
        return self._resolve_knockout(home, away, match)

    def _play_bracket(
        self,
        seeded: Dict[int, Tuple[Optional[str], Optional[str]]],
        fixed_ko: Optional[Dict[int, str]] = None,
        fixed_ties: Optional[Dict[int, Tuple[str, str]]] = None,
    ) -> Tuple[Dict[int, str], Dict[int, str]]:
        """Resolve the known R32 ties then walk the tree; return winners and
        losers by match. Pending ties (unknown teams) are simply absent from the
        returned maps, so downstream ties that reference them stay unresolved.

        ``fixed_ties`` pins a tree tie's real matchup (from a scraped record),
        overriding the template's ``W##``/``L##`` derivation — the source may
        number its round-of-16 ties differently from the FIFA template, so a
        recorded winner can only be locked onto the tie it was scraped for.
        """
        fixed_ko = fixed_ko or {}
        fixed_ties = fixed_ties or {}
        winners: Dict[int, str] = {}
        losers: Dict[int, str] = {}
        for match, (home, away) in seeded.items():
            settled = self._settle(match, home, away, fixed_ko)
            if settled is not None:
                winners[match], losers[match] = settled

        def team(ref: str) -> Optional[str]:
            src = winners if ref[0] == "W" else losers
            return src.get(int(ref[1:]))

        for tie in bracket.load_bracket()["tree"]:
            match = tie["match"]
            home, away = fixed_ties.get(
                match, (team(tie["home"]), team(tie["away"]))
            )
            settled = self._settle(match, home, away, fixed_ko)
            if settled is not None:
                winners[match], losers[match] = settled
        return winners, losers

    def simulate(
        self,
        seeded: Dict[int, Tuple[Optional[str], Optional[str]]],
        n_sims: int = 4_000,
        fixed_ko: Optional[Dict[int, str]] = None,
        fixed_ties: Optional[Dict[int, Tuple[str, str]]] = None,
    ) -> list[dict]:
        if n_sims <= 0:
            raise ValueError("n_sims must be positive.")
        fixed_ko = fixed_ko or {}
        # Only teams that appear in a known R32 tie can accrue deep-run odds.
        seeded_names = {
            name for pair in seeded.values() for name in pair if name is not None
        }
        if not seeded_names:
            return []
        tally = {
            n: {"reach_r16": 0, "reach_qf": 0, "reach_sf": 0,
                "reach_final": 0, "champion": 0}
            for n in seeded_names
        }

        for _ in range(n_sims):
            winners, _ = self._play_bracket(seeded, fixed_ko, fixed_ties)
            for match, name in winners.items():
                if name not in tally:
                    continue
                if match <= 88:
                    tally[name]["reach_r16"] += 1
                elif match in _ROUND_OF["reach_qf"]:
                    tally[name]["reach_qf"] += 1
                elif match in _ROUND_OF["reach_sf"]:
                    tally[name]["reach_sf"] += 1
                elif match in _ROUND_OF["reach_final"]:
                    tally[name]["reach_final"] += 1
            champ = winners.get(104)
            if champ in tally:
                tally[champ]["champion"] += 1

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
