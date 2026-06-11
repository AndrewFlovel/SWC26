"""Data layer: loads the 48-team dataset and venue catalogue, resolves the
official December 2025 draw, and generates the 72 group-stage fixtures with
venue-derived environmental context."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from .core import TeamProfile

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

GROUPS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]

# Round-robin pairings by index within a group [t0, t1, t2, t3].
_MATCHDAY_PAIRS = {
    1: [(0, 1), (2, 3)],
    2: [(0, 2), (3, 1)],
    3: [(3, 0), (1, 2)],
}


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
    """All 72 group-stage fixtures with venue and environmental context."""
    venue_data = load_venue_data()
    clusters = venue_data["group_clusters"]
    dates = venue_data["matchday_dates"]
    vmap = venues_by_id()

    fixtures: List[dict] = []
    for group, teams in get_draw().items():
        cluster = clusters[group]
        match_no = 0
        for matchday, pairs in _MATCHDAY_PAIRS.items():
            for hi, ai in pairs:
                home, away = teams[hi], teams[ai]
                venue = vmap[cluster[match_no % len(cluster)]]
                host = None
                if home.is_host ^ away.is_host:
                    host = home.name if home.is_host else away.name
                fixtures.append({
                    "id": f"{group}{match_no + 1}",
                    "group": group,
                    "matchday": matchday,
                    "date": dates[str(matchday)],
                    "home": home.name,
                    "away": away.name,
                    "home_team_host": host,
                    "venue": venue,
                })
                match_no += 1
    return fixtures
