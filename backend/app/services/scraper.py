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
from .knockout_store import knockout_store
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
# The results endpoint may list only played games, so upcoming knockout matchups
# (real teams, no score yet) are fetched separately from the all-matches feed.
MUNDIAL_FIXTURES_URL = os.getenv(
    "MUNDIAL_FIXTURES_URL",
    "https://mundial2026.mikeguerra4.com/api/matches",
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
_F_MATCH_ID = "id"
_F_STAGE = "stage"
_F_HOME_PENS = "homePenalties"
_F_AWAY_PENS = "awayPenalties"

# Knockout matches share the official bracket numbering (data/knockout_bracket.json):
# the source `id` IS the bracket match number. Stage names (Spanish) map to the
# round and are only used to validate that an id sits in the expected range.
# Spellings confirmed against a live payload (2026-07-02).
_KO_MIN, _KO_MAX = 73, 104
_KO_STAGES: Dict[str, Tuple[int, int]] = {
    "Dieciseisavos de Final": (73, 88),   # Round of 32
    "Octavos de Final": (89, 96),         # Round of 16
    "Cuartos de Final": (97, 100),        # Quarter-finals
    "Semifinal": (101, 102),              # Semi-finals
    "Tercer Lugar": (103, 103),           # Third-place play-off
    "Final": (104, 104),                  # Final
}

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


def _fetch_mundial_json(url: str, timeout: float) -> object:
    """GET a mundial2026 JSON endpoint with browser-like headers. May raise."""
    headers = {
        "User-Agent": MUNDIAL_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": MUNDIAL_REFERER,
    }
    if MUNDIAL_TOKEN:
        headers["Authorization"] = f"Bearer {MUNDIAL_TOKEN}"
    if MUNDIAL_COOKIE:
        headers["Cookie"] = MUNDIAL_COOKIE
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_results_payload(timeout: float = 10.0) -> object:
    """Fetch the raw mundial2026 results payload (played matches). May raise."""
    return _fetch_mundial_json(MUNDIAL_RESULTS_URL, timeout)


def fetch_fixtures_payload(timeout: float = 10.0) -> object:
    """Fetch the all-matches feed, incl. upcoming fixtures (real teams, no score
    yet) for knockout games not present in the results payload. May raise."""
    return _fetch_mundial_json(MUNDIAL_FIXTURES_URL, timeout)


def _merge_knockout(*parsed_lists: List[dict]) -> List[dict]:
    """Combine knockout parses from several payloads, keyed by match number.
    A finished entry for a match wins over a scheduled one (so a played result
    is never masked by the same game appearing unplayed in another feed)."""
    merged: Dict[int, dict] = {}
    for parsed in parsed_lists:
        for ko in parsed:
            cur = merged.get(ko["match"])
            if cur is None or (ko["finished"] and not cur["finished"]):
                merged[ko["match"]] = ko
    return list(merged.values())


def _expected_round(match_id: int, stage: Optional[str]) -> bool:
    """True if `stage` (when present) agrees with the id's bracket round."""
    if not stage:
        return True  # no stage to check against; trust the id
    rng = _KO_STAGES.get(stage.strip())
    return rng is None or rng[0] <= match_id <= rng[1]


def _parse_knockout(payload: object) -> List[dict]:
    """Knockout games keyed by their bracket match number (73-104).

    Returns one dict per match in range with the canonicalized team names,
    scores and penalties, and a `finished` flag (both scores present). Teams
    that are still placeholders (no resolvable name) come back as None and are
    filtered out downstream. Stage-vs-id mismatches are dropped.
    """
    parsed: List[dict] = []
    for match in _as_match_list(payload):
        mid = match.get(_F_MATCH_ID)
        if not isinstance(mid, int) or not _KO_MIN <= mid <= _KO_MAX:
            continue
        stage = match.get(_F_STAGE)
        if not _expected_round(mid, stage if isinstance(stage, str) else None):
            logger.warning("Knockout id %s has unexpected stage %r; skipping.", mid, stage)
            continue
        home = _team_name(match.get(_F_HOME_TEAM))
        away = _team_name(match.get(_F_AWAY_TEAM))
        gh, ga = match.get(_F_HOME_SCORE), match.get(_F_AWAY_SCORE)
        ph, pa = match.get(_F_HOME_PENS), match.get(_F_AWAY_PENS)
        parsed.append(
            {
                "match": mid,
                "home": _canonical(home.strip()) if home else None,
                "away": _canonical(away.strip()) if away else None,
                "goals_home": gh if isinstance(gh, int) else None,
                "goals_away": ga if isinstance(ga, int) else None,
                "pens_home": ph if isinstance(ph, int) else None,
                "pens_away": pa if isinstance(pa, int) else None,
                "finished": isinstance(gh, int) and isinstance(ga, int),
            }
        )
    return parsed


def fetch_match_results(timeout: float = 10.0) -> List[Tuple[str, str, int, int]]:
    """Finished group-stage results from the mundial2026 API. May raise."""
    return _parse_matches(fetch_results_payload(timeout))


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
            "(unknown teams)."
        )
    return stored


def _store_scraped_knockout(parsed: List[dict], messages: List[str]) -> int:
    """Persist scraped knockout games (matchups + results) by bracket match
    number. Only games whose BOTH teams resolve to real tournament teams are
    stored, so placeholder/undrawn slots are skipped. Manual records are never
    overwritten. Returns the number of knockout games stored."""
    known = set(load_teams().keys())
    stored = 0
    pending = 0
    for ko in parsed:
        home, away = ko["home"], ko["away"]
        if home not in known or away not in known:
            pending += 1  # slot not drawn yet (placeholder/null teams)
            continue
        existing = knockout_store.get(ko["match"])
        if existing and existing["source"] == "manual":
            continue
        status = "final" if ko["finished"] else "scheduled"
        if existing and existing["status"] == "final" and status == "scheduled":
            continue  # never downgrade a recorded result back to a fixture
        knockout_store.upsert(
            ko["match"], home, away,
            goals_home=ko["goals_home"], goals_away=ko["goals_away"],
            pens_home=ko["pens_home"], pens_away=ko["pens_away"],
            status=status, source="scraped",
        )
        stored += 1
    if pending:
        messages.append(f"{pending} knockout slot(s) not yet drawn; left to projection.")
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

    # Played group results AND knockout results come from the results payload.
    results_failed = False
    scraped_knockout: List[dict] = []
    try:
        payload = fetch_results_payload()
        scraped_results = _parse_matches(payload)
        scraped_knockout = _parse_knockout(payload)
    except Exception as exc:  # noqa: BLE001 — must never crash the API
        scraped_results = []
        results_failed = True
        logger.warning("Results fetch failed: %s", exc)
        messages.append(f"Results fetch failed: {exc}")

    # Upcoming knockout fixtures (real teams, not yet played) come from the
    # all-matches feed, which the results endpoint may omit. Best-effort: this
    # endpoint can be gated, and a failure must not block the played results.
    try:
        fixtures_payload = fetch_fixtures_payload()
        scraped_knockout = _merge_knockout(scraped_knockout, _parse_knockout(fixtures_payload))
    except Exception as exc:  # noqa: BLE001 — must never crash the API
        logger.info("Upcoming fixtures unavailable: %s", exc)
        messages.append(f"Upcoming fixtures unavailable: {exc}")

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
    knockout_found = _store_scraped_knockout(scraped_knockout, messages)
    if knockout_found:
        messages.append(f"Stored {knockout_found} knockout game(s) from mundial2026.")

    if elo_updates or results_found or knockout_found:
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
