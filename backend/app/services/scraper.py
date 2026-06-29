"""Best-effort fetch of the day's data. Never raises — every entry point
degrades gracefully and `refresh_today` always returns a `ScrapeResponse`.

Match **results** come from the mundial2026.mikeguerra4.com JSON API
(`/api/matches/results`); only finished matches (both scores present) for
known group-stage fixtures are stored, never overwriting manual entries.
Live **Elo** is still pulled (diagnostically) from eloratings.net for the
live-vs-model delta report; it renders client-side so it often yields
nothing, which is fine — Elo is not authoritative here.
"""

from __future__ import annotations

import logging
import os
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

# --- mundial2026.mikeguerra4.com results API ------------------------------- #
# The Blazor front-end reads finished scores from this public JSON endpoint.
# Browser-like headers are sent by default; the host gates some clients, so an
# optional session cookie / bearer token can be supplied via env vars.
MUNDIAL_RESULTS_URL = os.getenv(
    "MUNDIAL_RESULTS_URL",
    "https://mundial2026.mikeguerra4.com/api/matches/results",
)
MUNDIAL_REFERER = os.getenv(
    "MUNDIAL_REFERER", "https://mundial2026.mikeguerra4.com/matches"
)
MUNDIAL_USER_AGENT = os.getenv(
    "MUNDIAL_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
)
MUNDIAL_COOKIE = os.getenv("MUNDIAL_COOKIE")  # optional: raw Cookie header
MUNDIAL_TOKEN = os.getenv("MUNDIAL_TOKEN")    # optional: Bearer token

# JSON field names on a /api/matches/results entry (confirmed from a sample).
_F_HOME_TEAM = "homeTeam"
_F_AWAY_TEAM = "awayTeam"
_F_TEAM_NAME = "name"
_F_HOME_SCORE = "homeScore"
_F_AWAY_SCORE = "awayScore"

# Source spelling -> teams.json spelling. Unknown names are dropped/ignored.
NAME_ALIASES: Dict[str, str] = {
    # eloratings.net (English) spellings
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
    # mundial2026 (Spanish) spellings
    "Sudáfrica": "South Africa",
    "Canadá": "Canada",
    "España": "Spain",
    "Marruecos": "Morocco",
    "Países Bajos": "Netherlands",
    "Alemania": "Germany",
    "Bélgica": "Belgium",
    "Brasil": "Brazil",
    "Croacia": "Croatia",
    "Túnez": "Tunisia",
    "Egipto": "Egypt",
    "Catar": "Qatar",
    "Arabia Saudí": "Saudi Arabia",
    "Arabia Saudita": "Saudi Arabia",
    "Corea del Sur": "South Korea",
    "Estados Unidos": "United States",
    "Japón": "Japan",
    "Irán": "Iran",
    "Irak": "Iraq",
    "Nueva Zelanda": "New Zealand",
    "Noruega": "Norway",
    "Suecia": "Sweden",
    "Suiza": "Switzerland",
    "Escocia": "Scotland",
    "Inglaterra": "England",
    "Francia": "France",
    "Argelia": "Algeria",
    "Jordania": "Jordan",
    "Uzbekistán": "Uzbekistan",
    "Panamá": "Panama",
    "Haití": "Haiti",
    "Curazao": "Curacao",
    "Costa de Marfil": "Ivory Coast",
    "México": "Mexico",
    "Turquía": "Turkey",
    "Chequia": "Czechia",
    "República Checa": "Czechia",
    "RD Congo": "DR Congo",
    "R.D. Congo": "DR Congo",
    "República Democrática del Congo": "DR Congo",
    "Bosnia y Herzegovina": "Bosnia and Herzegovina",
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
    """Legacy eloratings.net result scrape (HTML). May raise. Kept for
    back-compat; `refresh_today` now sources results from mundial2026."""
    return parse_results_rows(_get_soup(ELO_URL, timeout))


def _as_match_list(payload: object) -> List[dict]:
    """Normalize the results payload to a list of match dicts (the API returns
    a JSON array; tolerate a single object or a wrapped list)."""
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, dict)]
    if isinstance(payload, dict):
        if _F_HOME_TEAM in payload:
            return [payload]
        for key in ("results", "matches", "data", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return [m for m in val if isinstance(m, dict)]
    return []


def _team_name(side: object) -> Optional[str]:
    """A match's team field is an object with a `name`; tolerate a bare string."""
    if isinstance(side, dict):
        name = side.get(_F_TEAM_NAME)
        return name if isinstance(name, str) else None
    return side if isinstance(side, str) else None


def _parse_matches(payload: object) -> List[Tuple[str, str, int, int]]:
    """(home, away, goals_home, goals_away) for every FINISHED match.

    A match counts as finished when both scores are present; scheduled/in-play
    entries (null scores) are skipped. Team names are canonicalized, so the
    Spanish source spellings map onto the teams.json names.
    """
    found: List[Tuple[str, str, int, int]] = []
    for match in _as_match_list(payload):
        home = _team_name(match.get(_F_HOME_TEAM))
        away = _team_name(match.get(_F_AWAY_TEAM))
        gh = match.get(_F_HOME_SCORE)
        ga = match.get(_F_AWAY_SCORE)
        if not home or not away or gh is None or ga is None:
            continue
        try:
            found.append(
                (_canonical(home.strip()), _canonical(away.strip()), int(gh), int(ga))
            )
        except (TypeError, ValueError):
            continue
    return found


def fetch_match_results(timeout: float = 10.0) -> List[Tuple[str, str, int, int]]:
    """Fetch finished results from the mundial2026 JSON API. May raise."""
    headers = {
        "User-Agent": MUNDIAL_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": MUNDIAL_REFERER,
    }
    if MUNDIAL_TOKEN:
        headers["Authorization"] = f"Bearer {MUNDIAL_TOKEN}"
    if MUNDIAL_COOKIE:
        headers["Cookie"] = MUNDIAL_COOKIE
    resp = requests.get(MUNDIAL_RESULTS_URL, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return _parse_matches(resp.json())


def _store_scraped_results(
    scraped: List[Tuple[str, str, int, int]], messages: List[str]
) -> int:
    """Persist scraped finals for known fixtures without overwriting manual
    entries. Returns the number of results stored."""
    by_pair = {(f["home"], f["away"]): f["id"] for f in get_fixtures()}
    stored = 0
    unmatched = 0
    for home, away, gh, ga in scraped:
        fixture_id = by_pair.get((home, away)) or by_pair.get((away, home))
        if fixture_id is None:
            unmatched += 1  # knockout ties / unknown teams have no group fixture
            continue
        if by_pair.get((home, away)) is None:  # reversed orientation
            home, away, gh, ga = away, home, ga, gh
        existing = results_store.get(fixture_id)
        if existing and existing["source"] == "manual":
            continue
        results_store.upsert(fixture_id, gh, ga, status="final", source="scraped")
        stored += 1
    if unmatched:
        messages.append(
            f"Ignored {unmatched} finished matches with no group-stage fixture "
            "(knockouts or unknown teams)."
        )
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

    # Live Elo (eloratings.net) is diagnostic only and best-effort.
    try:
        live = fetch_live_elo()
    except Exception as exc:  # noqa: BLE001 — must never crash the API
        live = {}
        messages.append(f"Live Elo unavailable: {exc}")

    # Match results come from the mundial2026 JSON API; best-effort.
    results_failed = False
    try:
        scraped_results = fetch_match_results()
    except Exception as exc:  # noqa: BLE001 — must never crash the API
        scraped_results = []
        results_failed = True
        logger.warning("Results fetch failed: %s", exc)
        messages.append(f"Results fetch failed: {exc}")

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

    if elo_updates or results_found:
        status = "ok"
    elif results_failed:
        status = "error"
    else:
        status = "fallback"
        messages.append("No finished results available from mundial2026 yet; "
                        "use manual entry if needed.")
    return {
        "status": status,
        "fetched_at": fetched_at,
        "elo_updates": elo_updates,
        "results_found": results_found,
        "messages": messages,
    }
