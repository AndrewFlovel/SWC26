"""Data layer: loads the 48-team dataset, venue catalogue and the official
group-stage fixture list (per-match dates and venues from the published
FIFA schedule — see fixtures.json "source"), resolving the December 2025
draw and venue-derived environmental context."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from .core import TeamProfile

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

GROUPS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]


@lru_cache(maxsize=1)
def load_teams() -> Dict[str, TeamProfile]:
    """Parse teams.json into TeamProfile objects keyed by country name."""
    raw = json.loads((DATA_DIR / "teams.json").read_text(encoding="utf-8"))
    profiles: Dict[str, TeamProfile] = {}
    for row in raw:
        profiles[row["name"]] = TeamProfile(
            name=row["name"],
            elo=float(row["elo"]),
            group=row["group"],
            fifa_ranking=int(row["fifa_ranking"]),
            confederation=row["confederation"],
            is_host=bool(row["is_host"]),
            altitude_adapted=bool(row["altitude_adapted"]),
            xg_avg=float(row["xg_avg"]),
            xga_avg=float(row["xga_avg"]),
            form_index=float(row["form_index"]),
            injury_impact=float(row["injury_impact"]),
        )
    if len(profiles) != 48:
        raise ValueError(f"Expected 48 teams, found {len(profiles)}.")
    return profiles


@lru_cache(maxsize=1)
def load_venue_data() -> dict:
    return json.loads((DATA_DIR / "venues.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def venues_by_id() -> Dict[str, dict]:
    return {v["id"]: v for v in load_venue_data()["venues"]}


@lru_cache(maxsize=1)
def get_draw() -> Dict[str, List[TeamProfile]]:
    """Group letter -> ordered list of TeamProfile (seed order from data)."""
    draw: Dict[str, List[TeamProfile]] = {g: [] for g in GROUPS}
    for profile in load_teams().values():
        draw[profile.group].append(profile)
    for g, teams in draw.items():
        if len(teams) != 4:
            raise ValueError(f"Group {g} has {len(teams)} teams, expected 4.")
    return draw


@lru_cache(maxsize=1)
def get_fixtures() -> List[dict]:
    """All 72 group-stage fixtures from the official schedule, enriched with
    venue environmental context and host designation."""
    raw = json.loads((DATA_DIR / "fixtures.json").read_text(encoding="utf-8"))
    teams = load_teams()
    vmap = venues_by_id()

    fixtures: List[dict] = []
    for row in raw["fixtures"]:
        home, away = teams[row["home"]], teams[row["away"]]
        host = None
        if home.is_host ^ away.is_host:
            host = home.name if home.is_host else away.name
        fixtures.append({
            "id": row["id"],
            "group": row["group"],
            "matchday": int(row["matchday"]),
            "date": row["date"],
            "home": home.name,
            "away": away.name,
            "home_team_host": host,
            "venue": vmap[row["venue"]],
        })
    if len(fixtures) != 72:
        raise ValueError(f"Expected 72 fixtures, found {len(fixtures)}.")
    return fixtures
