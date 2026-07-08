"""Best-effort confirmed starting-XI scraper for the player analyzer.

Sofascore renders match lineups client-side (JS), so — unlike the FBref squad
scrape in `player_scraper.py` — `requests` is not enough and a real browser is
needed. We drive headless Chrome via Selenium to fetch Sofascore's lineups
endpoint (`/api/v1/event/{id}/lineups`), which returns plain JSON, and parse the
confirmed XI + formation per side.

Following the existing scraper contract this module **never raises**: `selenium`
is imported lazily inside `_make_driver`, so the module (and the test suite)
imports cleanly even when selenium/Chrome are absent, and any failure (missing
browser, network/Cloudflare block, lineups not yet posted) degrades to an
"unannounced" result. The seed/optimal-XI path stays the reliable default; a
confirmed scrape only enhances it.

Driver binaries: in Docker we point at the system Chromium via the CHROME_BIN /
CHROMEDRIVER env vars; locally Selenium Manager (Selenium >= 4.6) resolves the
driver automatically.
"""

from __future__ import annotations

import json
import logging
import os
import unicodedata
from collections import Counter
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("wc2026.lineup_scraper")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SOFASCORE_API = "https://api.sofascore.com/api/v1"
PAGE_LOAD_TIMEOUT = 20  # seconds

# fixture_id -> Sofascore event id. Populated as event pages go live; unmapped
# fixtures fall back gracefully (mirrors the partial FBREF_TEAMS map). Example:
#   "H1": 13624891,
SOFASCORE_EVENTS: Dict[str, int] = {}

# Sofascore spelling -> seed/squad spelling (same idea as PLAYER_ALIASES).
LINEUP_ALIASES: Dict[str, str] = {}


# --------------------------------------------------------------------------- #
# Name matching
# --------------------------------------------------------------------------- #

def _norm(name: str) -> str:
    """Accent-stripped, lower-cased, alias-resolved key for fuzzy matching."""
    name = LINEUP_ALIASES.get(name, name)
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(stripped.lower().replace(".", " ").split())


def _match_names(
    scraped: List[str], squad_names: List[str]
) -> Tuple[List[str], List[str]]:
    """Map scraped starter names onto canonical squad names.

    Matches on the normalized full name first, then on an *unambiguous* surname
    (handles "L. Yamal" vs "Lamine Yamal"). Returns (matched canonical names with
    duplicates removed, unmatched scraped names).
    """
    by_full: Dict[str, str] = {}
    for sn in squad_names:
        by_full.setdefault(_norm(sn), sn)

    surname_counts = Counter(
        _norm(sn).split()[-1] for sn in squad_names if _norm(sn).split()
    )
    by_surname: Dict[str, str] = {}
    for sn in squad_names:
        parts = _norm(sn).split()
        if parts and surname_counts[parts[-1]] == 1:
            by_surname[parts[-1]] = sn

    matched: List[str] = []
    unmatched: List[str] = []
    seen: set = set()
    for raw in scraped:
        key = _norm(raw)
        parts = key.split()
        canonical: Optional[str] = None
        if key in by_full:
            canonical = by_full[key]
        elif parts and parts[-1] in by_surname:
            canonical = by_surname[parts[-1]]
        if canonical is None:
            unmatched.append(raw)
        elif canonical not in seen:
            seen.add(canonical)
            matched.append(canonical)
    return matched, unmatched


# --------------------------------------------------------------------------- #
# Selenium driver + fetch
# --------------------------------------------------------------------------- #

def _make_driver():
    """Create a headless Chrome driver. Raises if selenium/Chrome are absent;
    the caller treats that as a graceful 'lineups unavailable' outcome."""
    from selenium import webdriver  # lazy: keeps the module importable without selenium
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument(f"--user-agent={USER_AGENT}")

    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        opts.binary_location = chrome_bin

    driver_path = os.environ.get("CHROMEDRIVER")
    if driver_path:
        return webdriver.Chrome(service=Service(executable_path=driver_path), options=opts)
    return webdriver.Chrome(options=opts)  # Selenium Manager resolves the driver


def _fetch_lineups_json(event_id: int) -> Optional[dict]:
    """Load the Sofascore lineups JSON for an event via headless Chrome."""
    url = f"{SOFASCORE_API}/event/{event_id}/lineups"
    driver = _make_driver()
    try:
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        driver.get(url)
        body = driver.find_element("tag name", "body").text
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001 — teardown must not mask the real result
            pass

    body = (body or "").strip()
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start, end = body.find("{"), body.rfind("}")
        if 0 <= start < end:
            return json.loads(body[start : end + 1])
        return None


def _parse_side(side: Optional[dict], team: str) -> dict:
    side = side or {}
    starters = [
        ((pl.get("player") or {}).get("name") or "").strip()
        for pl in side.get("players", [])
        if not pl.get("substitute", False)
    ]
    return {
        "team": team,
        "formation": side.get("formation") or "",
        "starters": [s for s in starters if s],
    }


def scrape_confirmed(fixture_id: str, home_team: str, away_team: str) -> dict:
    """Fetch confirmed lineups for a fixture's two teams from Sofascore.

    Returns {"announced", "home": {team, formation, starters[]}, "away": {...},
    "messages": [...]}. Never raises; on any failure or unmapped fixture it
    returns announced=False with empty starters.
    """
    messages: List[str] = []
    blank = {
        "announced": False,
        "home": {"team": home_team, "formation": "", "starters": []},
        "away": {"team": away_team, "formation": "", "starters": []},
        "messages": messages,
    }

    event_id = SOFASCORE_EVENTS.get(fixture_id)
    if event_id is None:
        messages.append(f"No Sofascore event mapped for fixture {fixture_id}.")
        return blank

    try:
        data = _fetch_lineups_json(event_id)
    except Exception as exc:  # noqa: BLE001 — scrape must never crash the worker
        logger.warning("Confirmed-lineup scrape failed for %s: %s", fixture_id, exc)
        messages.append(f"Confirmed-lineup scrape failed for {fixture_id}: {exc}")
        return blank

    if not data:
        messages.append(f"No lineup data returned for {fixture_id}.")
        return blank

    announced = bool(data.get("confirmed"))
    messages.append(
        f"Sofascore lineups for {fixture_id} "
        + ("confirmed." if announced else "not yet confirmed.")
    )
    return {
        "announced": announced,
        "home": _parse_side(data.get("home"), home_team),
        "away": _parse_side(data.get("away"), away_team),
        "messages": messages,
    }
