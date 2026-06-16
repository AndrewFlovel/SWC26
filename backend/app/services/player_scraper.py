"""Hybrid, best-effort per-team squad scraper for the player analyzer.

FBref renders its squad stat tables server-side, so `requests` + BeautifulSoup
is sufficient — Selenium is reserved for the JS-rendered confirmed-lineup page
in a later phase. Parsing keys off FBref's stable `data-stat` attributes
(`player`, `position`, `xg_per90`, `tackles_won`, ...). Squad URLs are resolved
for any of the 48 teams through services.fbref_index (committed url-map with a
discovery fallback). Following the existing scraper.py contract, this module
**never raises**: on any network error, empty parse, or unknown team it falls
back to the seed/cached squad in player_store, tagging the `source` accordingly.
Scraped squads are diagnostic; the seed data is the reliable path (FBref rate-
limits aggressively and 2026 pages may be sparse).

Defensive depth: FBref publishes the Defensive-Actions and Misc tables on the
same squad page but wraps them in HTML comments. `_uncomment_tables` exposes
them so tackles/interceptions/clearances/aerials are read for real and
per-90-normalized via the standard table's `minutes_90s`. Pressures
(`pressures90`, `pressures_won_pct`) were discontinued by FBref, so those two
fields alone remain backfilled from `_DEF_DEFAULTS`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Comment

from ..engine.player_models import GROUP_OF, POSITIONS
from .fbref_index import squad_url
from .player_store import player_store, team_slug

logger = logging.getLogger("wc2026.player_scraper")

USER_AGENT = "Mozilla/5.0 (compatible; swc26-analytics/1.0; +per-game player analyzer)"
REQUEST_DELAY_S = 3.0          # FBref tolerates ~10 req/min; stay well under
REQUEST_TIMEOUT = (4.0, 8.0)   # (connect, read)

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

# Defensive per-90 / % values by taxonomy position. Used as the baseline before
# real values are merged in from the Defensive-Actions / Misc tables, and as the
# permanent source for `pressures90` / `pressures_won_pct` (which FBref no longer
# publishes) and for any player missing from the secondary tables.
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


def _per90(total: float, nineties: float) -> float:
    """Per-90 rate from a season total and a count of 90-minute units; the
    `minutes_90s` denominator guards a zero-minutes player (returns 0.0)."""
    return round(total / nineties, 3) if nineties > 0 else 0.0


def _pct(value: float) -> float:
    """Clamp a computed percentage into the [0, 100] range PlayerProfile expects."""
    return min(max(value, 0.0), 100.0)


def _get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _uncomment_tables(soup: BeautifulSoup) -> List[BeautifulSoup]:
    """Re-parse FBref's comment-wrapped secondary tables (defense, misc, ...).

    FBref hides every table after the first inside an HTML comment; this returns
    the parsed `<table>` fragments so their `data-stat` cells become queryable.
    """
    out: List[BeautifulSoup] = []
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if "<table" not in comment:
            continue
        out.append(BeautifulSoup(comment, "html.parser"))
    return out


def _index_rows_by_player(table_soup: BeautifulSoup) -> Dict[str, "BeautifulSoup"]:
    """Map canonical player name -> its row within a table soup."""
    rows: Dict[str, BeautifulSoup] = {}
    for row in table_soup.select("table tbody tr"):
        if row.get("class") and "thead" in row.get("class"):
            continue
        name = _cell(row, "player")
        if name:
            rows.setdefault(_canonical_name(name), row)
    return rows


def _find_table(tables: List[BeautifulSoup], stat: str) -> Optional[BeautifulSoup]:
    """First un-commented table that exposes a given data-stat column."""
    for t in tables:
        if t.find(attrs={"data-stat": stat}) is not None:
            return t
    return None


def parse_squad(soup: BeautifulSoup, team: str) -> List[dict]:
    """Extract player rows from an FBref squad page via stable data-stat keys.

    Attacking per-90s come straight from the standard table. Defensive metrics are
    read from the (comment-wrapped) Defensive-Actions and Misc tables and
    normalized to per-90 using the standard table's `minutes_90s`; pressures and
    any player absent from the secondary tables fall back to position defaults.
    Returns a list of PlayerProfile-shaped dicts.
    """
    secondary = _uncomment_tables(soup)
    def_table = _find_table(secondary, "interceptions")
    misc_table = _find_table(secondary, "aerials_won_pct")
    def_rows = _index_rows_by_player(def_table) if def_table else {}
    misc_rows = _index_rows_by_player(misc_table) if misc_table else {}

    players: List[dict] = []
    for row in soup.select("table tbody tr"):
        if row.get("class") and "thead" in row.get("class"):
            continue
        name = _cell(row, "player")
        if not name:
            continue
        canon = _canonical_name(name)
        pos = normalize_position(_cell(row, "position") or "")
        if pos not in POSITIONS:
            continue
        defaults = _DEF_DEFAULTS.get(pos, _DEF_DEFAULTS["CM"])
        nineties = _f(row, "minutes_90s")

        # Defensive metrics: real where the secondary tables have this player.
        drow = def_rows.get(canon)
        mrow = misc_rows.get(canon)
        if drow is not None:
            tackles = _f(drow, "tackles")
            tackles_won = _f(drow, "tackles_won")
            tackles_won_pct = (
                _f(drow, "challenge_tackles_pct")
                or (_pct(100.0 * tackles_won / tackles) if tackles > 0 else defaults["tackles_won_pct"])
            )
            interceptions90 = _per90(_f(drow, "interceptions"), nineties)
            clearances90 = _per90(_f(drow, "clearances"), nineties)
        else:
            tackles_won_pct = defaults["tackles_won_pct"]
            interceptions90 = defaults["interceptions90"]
            clearances90 = defaults["clearances90"]
        aerial_won_pct = _pct(_f(mrow, "aerials_won_pct")) if mrow is not None \
            else defaults["aerial_won_pct"]

        players.append({
            "name": canon,
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
            "tackles_won_pct": _pct(tackles_won_pct),
            "interceptions90": interceptions90,
            "clearances90": clearances90,
            "pressures90": defaults["pressures90"],          # discontinued by FBref
            "pressures_won_pct": defaults["pressures_won_pct"],  # discontinued by FBref
            "aerial_won_pct": aerial_won_pct,
            "is_starter": False,
            "source": "scraped",
        })
    return players


def scrape_squad(team: str) -> Tuple[Optional[dict], str, List[str]]:
    """Fetch a team's squad from FBref, persisting it through player_store.

    Returns (doc, source, messages). On any failure it falls back to the existing
    seed/cached document; if none exists, doc is None and source is 'unavailable'.
    Never raises.
    """
    slug = team_slug(team)
    messages: List[str] = []
    url = squad_url(team)

    if url is not None:
        try:
            time.sleep(REQUEST_DELAY_S)
            soup = _get_soup(url)
            rows = parse_squad(soup, team)
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
