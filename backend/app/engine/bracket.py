"""Official FIFA 2026 knockout bracket: the Round-of-32 match list and the
R16 -> final progression tree.

The R32 match numbers and the tree are loaded verbatim from
``data/knockout_bracket.json`` (the published FIFA template, matches 73-104).
The group phase has been retired, so the R32 pairings are no longer derived by
seeding group standings into slot codes; instead each R32 tie's two teams come
straight from scraped real results (the knockout store). An R32 match with no
scraped record yet is *pending* — its teams are unknown and it (plus everything
downstream of it) is left unresolved.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

_DATA = Path(__file__).resolve().parent.parent / "data" / "knockout_bracket.json"


@lru_cache(maxsize=1)
def load_bracket() -> dict:
    """Parse the knockout bracket template (cached)."""
    return json.loads(_DATA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def r32_match_numbers() -> Tuple[int, ...]:
    """The 16 Round-of-32 match numbers (73-88), in template order."""
    return tuple(tie["match"] for tie in load_bracket()["r32"])


def seeded_r32_from_store(
    store_records: Dict[str, dict],
) -> Dict[int, Tuple[Optional[str], Optional[str]]]:
    """Resolve every R32 tie's teams from scraped knockout results.

    Args:
        store_records: the knockout store payload — match-number string ->
            record carrying ``home``/``away`` team names (and, once played,
            scores/penalties). This is ``knockout_store.all()``.

    Returns:
        match number -> ``(home, away)``; ``(None, None)`` when no record has
        been scraped for that R32 slot yet (pending).
    """
    seeded: Dict[int, Tuple[Optional[str], Optional[str]]] = {}
    for match in r32_match_numbers():
        rec = store_records.get(str(match))
        if rec and rec.get("home") and rec.get("away"):
            seeded[match] = (rec["home"], rec["away"])
        else:
            seeded[match] = (None, None)
    return seeded
