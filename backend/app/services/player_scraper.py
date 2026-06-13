"""Hybrid, best-effort per-team squad scraper for the player analyzer.

FBref renders its squad stat tables server-side, so `requests` + BeautifulSoup
is sufficient — Selenium is reserved for the JS-rendered confirmed-lineup page
in a later phase. Parsing keys off FBref's stable `data-stat` attributes
(`player`, `position`, `xg_per90`, `tackles_won`, ...). Following the existing
scraper.py contract, this module **never raises**: on any network error, empty
parse, or unknown team it falls back to the seed/cached squad in player_store,
tagging the `source` accordingly. Scraped squads are diagnostic; the seed data
is the reliable path (FBref rate-limits aggressively and 2026 pages may be
sparse).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from ..engine.player_models import GROUP_OF, POSITIONS
from .player_store import player_store, team_slug

logger = logging.getLogger("wc2026.player_scraper")

USER_AGENT = "Mozilla/5.0 (compatible; swc26-analytics/1.0; +per-game player analyzer)"
REQUEST_DELAY_S = 3.0          # FBref tolerates ~10 req/min; stay well under
REQUEST_TIMEOUT = (4.0, 8.0)   # (connect, read)

# FBref national-team stats pages, keyed by canonical team name. Extend as the
# tournament squads get published; unknown teams fall back to seed data.
FBREF_TEAMS: Dict[str, str] = {
    "Spain": "https://fbref.com/en/squads/697ed4de/Spain-Men-Stats",
    "Uruguay": "https://fbref.com/en/squads/3372b561/Uruguay-Men-Stats",
    "Argentina": "https://fbref.com/en/squads/8a5d1402/Argentina-Men-Stats",
    "Austria": "https://fbref.com/en/squads/1e290e7f/Austria-Men-Stats",
}

# FBref spelling -> teams.json spelling (mirrors NAME_ALIASES in scraper.py).
PLAYER_ALIASES: Dict[str, str] = {}

# FBref position tokens -> our taxonomy. Coarse DF/MF/FW default within the
# group; detailed tokens (when present) map precisely.
_POS_MAP: Dict[str, str] = {
    "GK": "GK",
    "DF": "CB", "CB": "CB", "LB": "LB", "RB": "RB", "WB": "RB", "LWB": "LB", "RWB": "RB",
    "DM": "CDM", "CDM": "CDM", "MF": "CM", "CM": "CM", "AM": "CAM", "CAM": "CAM",
    "FW": "ST", "ST": "ST", "CF": "ST", "LW": "LW", "RW": "RW", "LM": "LW", "RM": "RW",
}

# Defensive per-90 / % backfill when a table lacks them, by taxonomy position.
_DEF_DEFAULTS: Dict[str, Dict[str, float]] = {
    "GK": dict(tackles_won_pct=50, interceptions90=0.1, clearances90=1.0,
               pressures90=1.5, pressures_won_pct=25, aerial_won_pct=42),
    "CB": dict(tackles_won_pct=66, interceptions90=1.5, clearances90=4.4,
               pressures90=8, pressures_won_pct=30, aerial_won_pct=68),
    "LB": dict(tackles_won_pct=61, interceptions90=1.2, clearances90=2.3,
               pressures90=14, pressures_won_pct=30, aerial_won_pct=48),
    "RB": dict(tackles_won_pct=61, interceptions90=1.2, clearances90=2.3,
               pressures90=14, pressures_won_pct=30, aerial_won_pct=48),
    "CDM": dict(tackles_won_pct=64, interceptions90=1.6, clearances90=2.0,
                pressures90=16, pressures_won_pct=32, aerial_won_pct=57),
    "CM": dict(tackles_won_pct=57, interceptions90=1.0, clearances90=1.0,
               pressures90=17, pressures_won_pct=31, aerial_won_pct=47),
    "CAM": dict(tackles_won_pct=49, interceptions90=0.7, clearances90=0.5,
                pressures90=16, pressures_won_pct=30, aerial_won_pct=40),
    "LW": dict(tackles_won_pct=47, interceptions90=0.6, clearances90=0.4,
               pressures90=15, pressures_won_pct=29, aerial_won_pct=35),
    "RW": dict(tackles_won_pct=47, interceptions90=0.6, clearances90=0.4,
               pressures90=15, pressures_won_pct=29, aerial_won_pct=35),
    "ST": dict(tackles_won_pct=45, interceptions90=0.4, clearances90=0.6,
               pressures90=13, pressures_won_pct=30, aerial_won_pct=55),
}


def normalize_position(fbref_pos: str) -> str:
    """Map an FBref position string (e.g. 'DF', 'MF,FW', 'AM') to our taxonomy."""
    if not fbref_pos:
        return "CM"
    for token in fbref_pos.replace("/", ",").split(","):
        token = token.strip().upper()
        if token in _POS_MAP:
            return _POS_MAP[token]
    return "CM"


def _canonical_name(name: str) -> str:
    return PLAYER_ALIASES.get(name, name)


def _cell(row, stat: str) -> Optional[str]:
    el = row.find(attrs={"data-stat": stat})
    if el is None:
        return None
    text = el.get_text(strip=True)
    return text or None


def _f(row, stat: str, default: float = 0.0) -> float:
    raw = _cell(row, stat)
    if raw is None:
        return default
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return default


def _i(row, stat: str, default: int = 0) -> int:
    return int(_f(row, stat, default))


def _get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_standard_table(soup: BeautifulSoup, team: str) -> List[dict]:
    """Extract player rows from an FBref standard-stats table via data-stat keys.

    Per-90 attacking metrics are read directly; defensive metrics not present in
    the standard table are backfilled from position defaults so PPS stays
    meaningful. Returns a list of PlayerProfile-shaped dicts.
    """
    players: List[dict] = []
    for row in soup.select("table tbody tr"):
        if row.get("class") and "thead" in row.get("class"):
            continue
        name = _cell(row, "player")
        if not name:
            continue
        pos = normalize_position(_cell(row, "position") or "")
        defaults = _DEF_DEFAULTS.get(pos, _DEF_DEFAULTS["CM"])
        player = {
            "name": _canonical_name(name),
            "team": team,
            "position": pos,
            "position_group": GROUP_OF[pos],
            "age": _i(row, "age"),
            "caps": _i(row, "games"),
            "international_goals": _i(row, "goals"),
            "club": _cell(row, "team") or "",
            "minutes_played": _i(row, "minutes"),
            "xg90": _f(row, "xg_per90"),
            "xa90": _f(row, "xg_assist_per90"),
            "shots90": _f(row, "shots_per90"),
            "progressive_passes90": _f(row, "progressive_passes_per90"),
            "shot_creating_actions90": _f(row, "sca_per90"),
            "dribbles_completed90": _f(row, "take_ons_won_per90"),
            "tackles_won_pct": defaults["tackles_won_pct"],
            "interceptions90": defaults["interceptions90"],
            "clearances90": defaults["clearances90"],
            "pressures90": defaults["pressures90"],
            "pressures_won_pct": defaults["pressures_won_pct"],
            "aerial_won_pct": defaults["aerial_won_pct"],
            "is_starter": False,
            "source": "scraped",
        }
        if player["position"] in POSITIONS:
            players.append(player)
    return players


def scrape_squad(team: str) -> Tuple[Optional[dict], str, List[str]]:
    """Fetch a team's squad from FBref, persisting it through player_store.

    Returns (doc, source, messages). On any failure it falls back to the existing
    seed/cached document; if none exists, doc is None and source is 'unavailable'.
    Never raises.
    """
    slug = team_slug(team)
    messages: List[str] = []
    url = FBREF_TEAMS.get(team)

    if url is not None:
        try:
            time.sleep(REQUEST_DELAY_S)
            soup = _get_soup(url)
            rows = parse_standard_table(soup, team)
            if rows:
                doc = {
                    "team": team,
                    "slug": slug,
                    "source": "scraped",
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "players": rows,
                }
                player_store.save_doc(slug, doc)
                messages.append(f"Scraped {len(rows)} players for {team} from FBref.")
                return doc, "scraped", messages
            messages.append(f"FBref page for {team} had no parsable player rows.")
        except Exception as exc:  # noqa: BLE001 — scrape must never crash the API
            logger.warning("Player scrape failed for %s: %s", team, exc)
            messages.append(f"Scrape failed for {team}: {exc}")
    else:
        messages.append(f"No FBref source mapped for {team}; using seed data.")

    fallback = player_store.get_doc(slug)
    if fallback is not None:
        source = fallback.get("source", "seed")
        messages.append(f"Using {source} squad for {team}.")
        return fallback, "cached" if source == "scraped" else source, messages

    messages.append(f"No squad data available for {team}.")
    return None, "unavailable", messages
