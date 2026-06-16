"""Hybrid resolver of FBref national-team squad-stats URLs for all 48 teams.

The runtime source of truth is a committed JSON map, data/fbref_squads.json
(`{canonical team name: squad-stats URL}`), so the player scraper can find any
team's page offline and reviewers can see the mapping in git. `discover_squad_urls`
refreshes that map from FBref's World Cup competition index; `squad_url` reads the
map and falls back to a single targeted discovery on a miss (the "hybrid" path).

Mirrors services.scraper conventions: a module-level USER_AGENT/`_get_soup`, a
canonical alias dict (FBref spelling -> teams.json spelling), and the never-the-
authoritative-path contract — discovery never raises, returning a partial/empty
map on any failure. The committed map is the reliable input.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from ..engine.loader import load_teams

logger = logging.getLogger("wc2026.fbref_index")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAP_PATH = DATA_DIR / "fbref_squads.json"

# FBref men's World Cup competition hub; lists participating squads with links to
# their per-team stats pages. Overridable for a specific edition if FBref moves it.
INDEX_URL = "https://fbref.com/en/comps/1/World-Cup-Stats"
USER_AGENT = "Mozilla/5.0 (compatible; swc26-analytics/1.0; +per-game player analyzer)"
REQUEST_TIMEOUT = (4.0, 8.0)  # (connect, read)

# FBref spelling -> teams.json spelling. Unknown names are dropped (a squad link
# whose canonical name is not one of the 48 teams is ignored). Mirrors the role of
# scraper.NAME_ALIASES; targets match the canonical names in teams.json exactly.
FBREF_NAME_ALIASES: Dict[str, str] = {
    "Czech Republic": "Czechia",
    "USA": "United States",
    "United States of America": "United States",
    "IR Iran": "Iran",
    "Iran IR": "Iran",
    "Korea Republic": "South Korea",
    "Korea DPR": "North Korea",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo",
    "Congo Kinshasa": "DR Congo",
    "Curaçao": "Curacao",
    "Bosnia": "Bosnia and Herzegovina",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Türkiye": "Turkey",
    "Cabo Verde": "Cape Verde",
}

# Squad-stats page hrefs look like /en/squads/<8-hex-id>/Spain-Men-Stats.
_SQUAD_HREF_RE = re.compile(r"^/en/squads/[0-9a-f]{8}/")


def canonical(name: str) -> str:
    """Map an FBref team spelling to its teams.json canonical name."""
    return FBREF_NAME_ALIASES.get(name.strip(), name.strip())


def _absolute(href: str) -> str:
    return href if href.startswith("http") else f"https://fbref.com{href}"


def _get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def load_map() -> Dict[str, str]:
    """The committed team -> squad-URL map, or {} if not yet generated."""
    if not MAP_PATH.exists():
        return {}
    try:
        return json.loads(MAP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s: %s", MAP_PATH, exc)
        return {}


def _save_map(mapping: Dict[str, str]) -> None:
    """Atomically persist the url-map (mirrors player_store.save_doc)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MAP_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, MAP_PATH)


def parse_index(soup: BeautifulSoup) -> Dict[str, str]:
    """Extract {canonical team -> absolute squad URL} from an FBref index page.

    Keeps only squad links whose canonical name is one of the 48 tournament teams;
    the first link wins if a team appears more than once.
    """
    teams = set(load_teams().keys())
    found: Dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _SQUAD_HREF_RE.match(href):
            continue
        name = canonical(a.get_text(strip=True))
        if name in teams and name not in found:
            found[name] = _absolute(href)
    return found


def discover_squad_urls(persist: bool = True) -> Dict[str, str]:
    """Resolve squad URLs from FBref's WC index, merging into the committed map.

    Never raises: on any network/parse failure it logs and returns the existing
    map unchanged. Newly discovered URLs are merged over (and persisted with) it,
    so previously-known hand-mapped teams are preserved.
    """
    existing = load_map()
    try:
        discovered = parse_index(_get_soup(INDEX_URL))
    except Exception as exc:  # noqa: BLE001 — discovery must never crash callers
        logger.warning("FBref index discovery failed: %s", exc)
        return existing

    merged = {**existing, **discovered}
    if persist and merged != existing:
        _save_map(merged)
    return merged


def squad_url(team: str) -> Optional[str]:
    """Hybrid lookup: committed map first, then a single targeted discovery.

    Returns the FBref squad-stats URL for `team`, or None if it cannot be
    resolved (the player scraper then falls back to seed/cached data).
    """
    mapped = load_map().get(team)
    if mapped:
        return mapped
    return discover_squad_urls().get(team)
