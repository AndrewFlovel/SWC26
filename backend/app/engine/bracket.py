"""Official FIFA 2026 knockout bracket: the Round-of-32 slot template, the
R16 -> final progression tree, and best-thirds allocation.

The R32 pairings and the tree are loaded verbatim from
``data/knockout_bracket.json`` (the published FIFA template, matches 73-104).
The only piece resolved at runtime is which of the eight qualifying
third-placed teams fills each ``3X`` slot: FIFA publishes a 495-row combination
table for this, but its governing rule — a third-placed team is never drawn
against the winner of its own group — is reproduced here with a deterministic,
constraint-respecting assignment so the bracket is always seedable.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

_DATA = Path(__file__).resolve().parent.parent / "data" / "knockout_bracket.json"


@lru_cache(maxsize=1)
def load_bracket() -> dict:
    """Parse the knockout bracket template (cached)."""
    return json.loads(_DATA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def third_receiving_groups() -> Tuple[str, ...]:
    """Winner-group letters whose R32 slot faces a third-placed team, in match
    order (e.g. ``('E', 'I', 'A', 'L', 'D', 'G', 'B', 'K')``)."""
    return tuple(
        tie["home"][1] for tie in load_bracket()["r32"] if tie["away"] == "3X"
    )


def allocate_thirds(
    qualified: Sequence[str], opp_groups: Sequence[str]
) -> Dict[str, str]:
    """Assign the qualifying third-place *groups* to the third-slots.

    ``opp_groups`` is the ordered list of winner-groups whose slot needs a
    third (see :func:`third_receiving_groups`). A third-placed team is never
    placed against the winner of its own group. Deterministic: candidates are
    tried in sorted order via backtracking; the first complete assignment wins.

    Returns a mapping ``winner_group -> third_group``.
    """
    thirds = sorted(qualified)
    if len(thirds) != len(opp_groups):
        raise ValueError(
            f"Need {len(opp_groups)} thirds to fill the bracket, got {len(thirds)}."
        )
    assignment: Dict[str, str] = {}
    used = [False] * len(thirds)

    def backtrack(i: int) -> bool:
        if i == len(opp_groups):
            return True
        opp = opp_groups[i]
        for k, g in enumerate(thirds):
            if used[k] or g == opp:
                continue
            used[k] = True
            assignment[opp] = g
            if backtrack(i + 1):
                return True
            used[k] = False
        return False

    if not backtrack(0):
        # No clash-free matching exists (degenerate input): assign in order.
        for opp, g in zip(opp_groups, thirds):
            assignment[opp] = g
    return assignment


def seed_r32(
    group_order: Dict[str, List[str]], qualified_thirds: Sequence[str]
) -> Dict[int, Tuple[str, str]]:
    """Resolve every R32 slot to a concrete team.

    Args:
        group_order: group letter -> the four team names in final standings
            order (index 0 = winner, 1 = runner-up, 2 = third).
        qualified_thirds: the eight group letters whose third-placed team
            advanced as a best third.

    Returns:
        match number -> (home_team, away_team).
    """
    bracket = load_bracket()
    alloc = allocate_thirds(qualified_thirds, third_receiving_groups())

    def slot(code: str) -> str:
        return group_order[code[1]][int(code[0]) - 1]

    seeded: Dict[int, Tuple[str, str]] = {}
    for tie in bracket["r32"]:
        home = slot(tie["home"])
        if tie["away"] == "3X":
            third_group = alloc[tie["home"][1]]
            away = group_order[third_group][2]
        else:
            away = slot(tie["away"])
        seeded[tie["match"]] = (home, away)
    return seeded
