"""Persisted per-team squad cache for the player analyzer.

One JSON document per team lives in data/players/<slug>.json (seed squads ship
with the repo; scraped squads overwrite them). Mirrors results_store: atomic
.tmp -> os.replace writes and an in-memory `version` counter bumped on every
write, which keys the scored-squad lru_cache (same invalidation pattern as
services.metrics) so a fresh scrape is reflected on the next request.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..engine.player_models import PlayerProfile
from ..engine.player_scorer import score_squad

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "players"


def team_slug(team: str) -> str:
    """Canonical filename stem for a team (e.g. 'United States' -> 'united-states')."""
    return team.strip().lower().replace(" ", "-")


class PlayerStore:
    def __init__(self, directory: Path = DATA_DIR) -> None:
        self.dir = directory
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    def path(self, slug: str) -> Path:
        return self.dir / f"{slug}.json"

    def get_doc(self, slug: str) -> Optional[dict]:
        """Raw squad document (team, slug, source, scraped_at, players) or None."""
        p = self.path(slug)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def save_doc(self, slug: str, doc: dict) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path(slug).with_suffix(".tmp")
        tmp.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(tmp, self.path(slug))
        self._version += 1
        return doc


player_store = PlayerStore()


@lru_cache(maxsize=128)
def _scored(version: int, slug: str) -> Tuple[PlayerProfile, ...]:
    doc = player_store.get_doc(slug)
    if doc is None:
        return ()
    team = doc.get("team", slug)
    source = doc.get("source", "seed")
    players = [
        PlayerProfile.from_dict(row, team=team, source=source)
        for row in doc.get("players", [])
    ]
    return tuple(score_squad(players))


def get_squad(slug: str) -> Optional[List[PlayerProfile]]:
    """Scored squad for a slug (cached by store version), or None if unknown."""
    scored = _scored(player_store.version, slug)
    return list(scored) if scored else None


def squad_source(slug: str) -> Optional[str]:
    doc = player_store.get_doc(slug)
    return doc.get("source") if doc else None


def squad_index() -> Dict[str, int]:
    """Map of available slug -> player count (seed + scraped files on disk)."""
    if not player_store.dir.exists():
        return {}
    out: Dict[str, int] = {}
    for f in sorted(player_store.dir.glob("*.json")):
        try:
            out[f.stem] = len(json.loads(f.read_text(encoding="utf-8")).get("players", []))
        except (json.JSONDecodeError, OSError):
            continue
    return out
