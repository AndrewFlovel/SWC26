"""Persisted store of manual per-team availability adjustments.

Records real squad attrition the results feed cannot provide (suspensions
after an expulsion, confirmed injuries): a signed ``injury_delta`` added on
top of the team's baseline ``injury_impact`` (clamped to [0, 1]) plus a short
free-text note. Applied inside services.metrics so every prediction and
simulation sees it. The in-memory ``version`` counter is bumped on every
write so cached derivations invalidate immediately. Single-process only;
for multi-worker deployments key caches on the file mtime instead.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MAX_NOTE_LEN = 280


class TeamAdjustStore:
    def __init__(self, path: Path = DATA_DIR / "team_adjustments.json") -> None:
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

    def get(self, team: str) -> Optional[dict]:
        return self._records.get(team)

    def upsert(self, team: str, injury_delta: float, note: str = "") -> dict:
        if not team:
            raise ValueError("A team name is required.")
        if not -1.0 <= injury_delta <= 1.0:
            raise ValueError("injury_delta must lie in [-1, 1].")
        if len(note) > MAX_NOTE_LEN:
            raise ValueError(f"Note must be at most {MAX_NOTE_LEN} characters.")
        record = {
            "injury_delta": float(injury_delta),
            "note": note,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._records[team] = record
        self._persist()
        return record

    def delete(self, team: str) -> None:
        if team in self._records:
            del self._records[team]
            self._persist()


team_adjust_store = TeamAdjustStore()
