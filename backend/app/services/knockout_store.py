"""Persisted store of knockout-stage matches, keyed by match number (73-104).

Unlike the group-stage `results_store` (which only records goals against fixed
fixtures), knockout slots are filled dynamically, so each record carries the two
team names alongside the score and any penalty-shootout result. A match absent
from the store is "not yet drawn"; the bracket projection falls back to the model
for those. This store is intentionally kept separate from the group results so the
Elo/xG metrics replay is never fed knockout games.

Single-process only; for multi-worker deployments key caches on the file mtime.
"""

from __future__ import annotations

import json
import os
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

VALID_STATUSES = ("scheduled", "final")
VALID_SOURCES = ("manual", "scraped")

# Official bracket match numbers (see data/knockout_bracket.json).
MIN_MATCH, MAX_MATCH = 73, 104


class KnockoutStore:
    def __init__(self, path: Path = DATA_DIR / "knockout_results.json") -> None:
        self.path = path
        self._version = 0
        self._records: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _persist(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._records, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(tmp, self.path)
        self._version += 1

    @property
    def version(self) -> int:
        return self._version

    def all(self) -> Dict[str, dict]:
        return dict(self._records)

    def get(self, match: int) -> Optional[dict]:
        return self._records.get(str(match))

    def upsert(
        self,
        match: int,
        home: str,
        away: str,
        goals_home: Optional[int] = None,
        goals_away: Optional[int] = None,
        pens_home: Optional[int] = None,
        pens_away: Optional[int] = None,
        status: str = "scheduled",
        source: str = "scraped",
        date: Optional[str] = None,
    ) -> dict:
        if not MIN_MATCH <= match <= MAX_MATCH:
            raise ValueError(f"Knockout match must be {MIN_MATCH}-{MAX_MATCH}.")
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'.")
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source '{source}'.")
        if not home or not away:
            raise ValueError("Both team names are required.")
        if status == "final" and (goals_home is None or goals_away is None):
            raise ValueError("A final knockout match needs both scores.")
        for g in (goals_home, goals_away, pens_home, pens_away):
            if g is not None and g < 0:
                raise ValueError("Goals/penalties must be non-negative.")
        if date is not None:
            try:
                _date.fromisoformat(str(date)[:10])
                date = str(date)[:10]
            except ValueError:
                date = None  # a bad scraped date must not block the record
        record = {
            "home": home,
            "away": away,
            "goals_home": None if goals_home is None else int(goals_home),
            "goals_away": None if goals_away is None else int(goals_away),
            "pens_home": None if pens_home is None else int(pens_home),
            "pens_away": None if pens_away is None else int(pens_away),
            "status": status,
            "source": source,
            "date": date,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._records[str(match)] = record
        self._persist()
        return record

    def delete(self, match: int) -> None:
        if str(match) in self._records:
            del self._records[str(match)]
            self._persist()


def winner_of(record: dict) -> Optional[str]:
    """The actual winner of a finished knockout match (goals, penalties as the
    tie-break). Returns None for unfinished or undecidable records."""
    if record.get("status") != "final":
        return None
    gh, ga = record.get("goals_home"), record.get("goals_away")
    if gh is None or ga is None:
        return None
    if gh != ga:
        return record["home"] if gh > ga else record["away"]
    ph, pa = record.get("pens_home"), record.get("pens_away")
    if ph is not None and pa is not None and ph != pa:
        return record["home"] if ph > pa else record["away"]
    return None  # level with no shootout result recorded


knockout_store = KnockoutStore()
