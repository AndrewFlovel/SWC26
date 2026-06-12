"""Persisted store of group-stage match results, keyed by fixture id.

A fixture absent from the store is "scheduled". Only results with
status == "final" feed the metric adjustment replay. The in-memory
`version` counter is bumped on every write so cached derivations
(see services.metrics) invalidate immediately. Single-process only;
for multi-worker deployments key caches on the file mtime instead.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

VALID_STATUSES = ("live", "final")
VALID_SOURCES = ("manual", "scraped")


class ResultsStore:
    def __init__(self, path: Path = DATA_DIR / "results.json") -> None:
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

    def get(self, fixture_id: str) -> Optional[dict]:
        return self._records.get(fixture_id)

    def upsert(
        self,
        fixture_id: str,
        goals_home: int,
        goals_away: int,
        status: str = "final",
        source: str = "manual",
    ) -> dict:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'.")
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source '{source}'.")
        if goals_home < 0 or goals_away < 0:
            raise ValueError("Goals must be non-negative.")
        record = {
            "goals_home": int(goals_home),
            "goals_away": int(goals_away),
            "status": status,
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._records[fixture_id] = record
        self._persist()
        return record

    def delete(self, fixture_id: str) -> None:
        if fixture_id in self._records:
            del self._records[fixture_id]
            self._persist()


results_store = ResultsStore()
