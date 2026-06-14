"""In-memory job registry + worker for the confirmed-lineup scrape.

The confirmed-XI scrape drives a headless browser (slow, ~10-30s) so it runs off
the request thread: `POST /api/scrape/lineups` launches `run_lineup_job` in a
daemon `threading.Thread`, and clients poll `GET /api/scrape/players/status/...`.
Jobs are ephemeral (no persistence) and tracked here. The store is guarded by a
lock — the worker thread writes while poller requests read — and TTL-evicts
finished jobs so it never leaks. The worker wraps everything so an exception can
never crash the thread; failures land in the job as status="error".
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..engine.lineup_analyzer import order_to_formation
from ..engine.player_models import FORMATIONS
from . import lineup_scraper
from .player_store import get_squad, team_slug

logger = logging.getLogger("wc2026.lineup_jobs")

JOB_TTL_S = 900  # evict finished jobs after 15 minutes
DEFAULT_FORMATION = "4-3-3"

_TERMINAL = ("done", "error")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LineupJob:
    fixture_id: str
    status: str  # "pending" | "running" | "done" | "error"
    home: Optional[dict] = None
    away: Optional[dict] = None
    messages: List[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: Optional[str] = None
    _touched: float = field(default_factory=time.monotonic, repr=False)

    def to_status(self) -> dict:
        """Serialize to the LineupJobStatus shape (drops internal bookkeeping)."""
        return {
            "fixture_id": self.fixture_id,
            "status": self.status,
            "home": self.home,
            "away": self.away,
            "messages": list(self.messages),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class LineupJobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, LineupJob] = {}

    def _evict_locked(self) -> None:
        now = time.monotonic()
        stale = [
            fid
            for fid, job in self._jobs.items()
            if job.status in _TERMINAL and now - job._touched > JOB_TTL_S
        ]
        for fid in stale:
            del self._jobs[fid]

    def start(self, fixture_id: str) -> Tuple[LineupJob, bool]:
        """Return (job, created). If a job is already pending/running, reuse it
        (created=False) so concurrent POSTs don't launch duplicate workers."""
        with self._lock:
            self._evict_locked()
            existing = self._jobs.get(fixture_id)
            if existing is not None and existing.status not in _TERMINAL:
                return existing, False
            job = LineupJob(fixture_id=fixture_id, status="pending", started_at=_now())
            self._jobs[fixture_id] = job
            return job, True

    def set_running(self, fixture_id: str) -> None:
        with self._lock:
            job = self._jobs.get(fixture_id)
            if job is not None:
                job.status = "running"
                job._touched = time.monotonic()

    def complete(
        self, fixture_id: str, home: dict, away: dict, messages: List[str]
    ) -> None:
        with self._lock:
            job = self._jobs.get(fixture_id)
            if job is not None:
                job.status = "done"
                job.home = home
                job.away = away
                job.messages = list(messages)
                job.finished_at = _now()
                job._touched = time.monotonic()

    def fail(self, fixture_id: str, messages: List[str]) -> None:
        with self._lock:
            job = self._jobs.get(fixture_id)
            if job is not None:
                job.status = "error"
                job.messages = list(messages)
                job.finished_at = _now()
                job._touched = time.monotonic()

    def get(self, fixture_id: str) -> Optional[LineupJob]:
        with self._lock:
            self._evict_locked()
            return self._jobs.get(fixture_id)


lineup_jobs = LineupJobStore()


def _build_side(team: str, scraped_side: dict, announced: bool) -> dict:
    """Resolve one scraped side into a ConfirmedSideOut-shaped dict.

    Matches scraped starters to the team's squad, and — when all 11 map and the
    XI is announced — orders them into the formation's slots so the lineup is
    ready for `analyze_lineups`. Otherwise `lineup` is empty and `unmatched`
    explains why, leaving the UI to keep the optimal XI.
    """
    squad = get_squad(team_slug(team)) or []
    squad_names = [p.name for p in squad]
    starters = scraped_side.get("starters", [])
    side_announced = announced and len(starters) >= 11

    matched, unmatched = lineup_scraper._match_names(starters, squad_names)
    formation = scraped_side.get("formation") or ""
    chosen = formation if formation in FORMATIONS else DEFAULT_FORMATION

    lineup: List[str] = []
    if side_announced and len(matched) >= 11:
        by_name = {p.name: p for p in squad}
        players = [by_name[n] for n in matched[:11]]
        try:
            ordered = order_to_formation(players, chosen)
            lineup = [p.name for p in ordered]
        except Exception as exc:  # noqa: BLE001 — fall back to scrape order
            logger.warning("Could not order confirmed XI for %s: %s", team, exc)
            lineup = [p.name for p in players]

    return {
        "team": team,
        "formation": chosen,
        "lineup": lineup,
        "unmatched": unmatched,
        "announced": side_announced,
    }


def run_lineup_job(fixture_id: str, home_team: str, away_team: str) -> None:
    """Threaded worker: scrape confirmed lineups, resolve both sides, record
    the result. Never propagates exceptions (would crash the daemon thread)."""
    lineup_jobs.set_running(fixture_id)
    try:
        scraped = lineup_scraper.scrape_confirmed(fixture_id, home_team, away_team)
        announced = scraped.get("announced", False)
        home = _build_side(home_team, scraped.get("home", {}), announced)
        away = _build_side(away_team, scraped.get("away", {}), announced)
        lineup_jobs.complete(fixture_id, home, away, scraped.get("messages", []))
    except Exception as exc:  # noqa: BLE001 — surface as an error status, don't crash
        logger.exception("Lineup job crashed for %s", fixture_id)
        lineup_jobs.fail(fixture_id, [f"Lineup job failed: {exc}"])
