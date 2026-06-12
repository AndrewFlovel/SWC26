"""Best-effort scraping of the day's data, ported from the research
script (monteCarlo.py DataGenerator._scrape_elo).

eloratings.net renders client-side, so the static-HTML parse may find
nothing — every entry point degrades gracefully and `refresh_today`
never raises. Manual entry through the results-control view is the
reliable path; scraped Elo is diagnostic (live-vs-model deltas), not
authoritative, to avoid double-counting results the replay already
prices in.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from ..engine.loader import get_fixtures, load_teams
from .results_store import results_store

logger = logging.getLogger("wc2026.scraper")

ELO_URL = "https://www.eloratings.net/2026_World_Cup"
USER_AGENT = "Mozilla/5.0 (compatible; wc2026-bot/1.0)"

# eloratings.net spelling -> teams.json spelling. Unknown names are
# dropped and reported in the response messages.
NAME_ALIASES: Dict[str, str] = {
    "Czech Republic": "Czechia",
    "USA": "United States",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo",
    "Curaçao": "Curacao",
    "Korea Republic": "South Korea",
    "Bosnia": "Bosnia and Herzegovina",
    "Türkiye": "Turkey",
    "Cabo Verde": "Cape Verde",
}

_SCORE_RE = re.compile(r"^(\d{1,2})\s*[-:–]\s*(\d{1,2})$")


def _canonical(name: str) -> str:
    return NAME_ALIASES.get(name, name)


def _get_soup(url: str, timeout: float) -> BeautifulSoup:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def fetch_live_elo(timeout: float = 8.0) -> Dict[str, float]:
    """Scrape current Elo ratings; keys are canonical team names. May raise."""
    soup = _get_soup(ELO_URL, timeout)
    parsed: Dict[str, float] = {}
    for row in soup.select("table tr"):
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) >= 2:
            try:
                parsed[_canonical(cols[0])] = float(cols[1].replace(",", ""))
            except ValueError:
                continue
    return parsed


def parse_results_rows(soup: BeautifulSoup) -> List[Tuple[str, str, int, int]]:
    """Extract (home, away, goals_home, goals_away) tuples from rows shaped
    like `home | score | away`; tolerant of unrelated rows."""
    found: List[Tuple[str, str, int, int]] = []
    for row in soup.select("table tr"):
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) < 3:
            continue
        m = _SCORE_RE.match(cols[1])
        if not m:
            continue
        found.append(
            (_canonical(cols[0]), _canonical(cols[2]), int(m.group(1)), int(m.group(2)))
        )
    return found


def fetch_today_results(timeout: float = 8.0) -> List[Tuple[str, str, int, int]]:
    """Best-effort scrape of finished scorelines. May raise."""
    return parse_results_rows(_get_soup(ELO_URL, timeout))


def _store_scraped_results(
    scraped: List[Tuple[str, str, int, int]], messages: List[str]
) -> int:
    """Persist scraped finals for known fixtures without overwriting manual
    entries. Returns the number of results stored."""
    by_pair = {(f["home"], f["away"]): f["id"] for f in get_fixtures()}
    stored = 0
    for home, away, gh, ga in scraped:
        fixture_id = by_pair.get((home, away)) or by_pair.get((away, home))
        if fixture_id is None:
            messages.append(f"Unmatched scraped result: {home} {gh}-{ga} {away}")
            continue
        if by_pair.get((home, away)) is None:  # reversed orientation
            home, away, gh, ga = away, home, ga, gh
        existing = results_store.get(fixture_id)
        if existing and existing["source"] == "manual":
            continue
        results_store.upsert(fixture_id, gh, ga, status="final", source="scraped")
        stored += 1
    return stored


def refresh_today(adjusted_elo: Optional[Dict[str, float]] = None) -> dict:
    """Fetch the day's data (live Elo + finished results). Never raises.

    `adjusted_elo` maps team name -> current model Elo (post-replay) for
    the diagnostic delta report; defaults to the base dataset.
    """
    if adjusted_elo is None:
        adjusted_elo = {name: t.elo for name, t in load_teams().items()}

    messages: List[str] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        live = fetch_live_elo()
        scraped_results = fetch_today_results()
    except Exception as exc:  # noqa: BLE001 — scrape must never crash the API
        logger.warning("Scrape failed: %s", exc)
        return {
            "status": "error",
            "fetched_at": fetched_at,
            "elo_updates": [],
            "results_found": 0,
            "messages": [f"Scrape failed: {exc}"],
        }

    elo_updates = [
        {
            "team": name,
            "live_elo": round(live_elo, 1),
            "model_elo": round(adjusted_elo[name], 1),
            "delta": round(live_elo - adjusted_elo[name], 1),
        }
        for name, live_elo in sorted(live.items())
        if name in adjusted_elo
    ]
    unknown = sorted(set(live) - set(adjusted_elo))
    if unknown:
        messages.append(f"Ignored {len(unknown)} non-tournament names: "
                        + ", ".join(unknown[:5]) + ("…" if len(unknown) > 5 else ""))

    results_found = _store_scraped_results(scraped_results, messages)

    status = "ok" if (elo_updates or results_found) else "fallback"
    if status == "fallback":
        messages.append("Page fetched but no parsable data found "
                        "(eloratings.net renders client-side); use manual entry.")
    return {
        "status": status,
        "fetched_at": fetched_at,
        "elo_updates": elo_updates,
        "results_found": results_found,
        "messages": messages,
    }
