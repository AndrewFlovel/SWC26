"""One-time CLI that gives every one of the 48 teams a reference squad on disk.

Run from the backend/ directory:

    python -m scripts.bootstrap_squads              # all teams
    python -m scripts.bootstrap_squads --team Brazil
    python -m scripts.bootstrap_squads --discover-only
    python -m scripts.bootstrap_squads --force      # re-scrape existing files

For each team it resolves an FBref URL (via fbref_index, discovering first if the
committed map is incomplete) and calls player_scraper.scrape_squad, which persists
the result through player_store. Teams FBref cannot supply (sparse 2026 pages) get
a deterministic synthetic baseline derived from teams.json strength, tagged
`source="synthetic"`, so coverage is a true 48/48 even offline. The four
hand-curated seed files are preserved unless --force is given.

The output JSON files are committed to the repo as the analyzer's reference
backbone — this script is a generator, not a runtime dependency.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Dict, List

from app.engine.loader import load_teams
from app.engine.player_models import GROUP_OF
from app.services import player_scraper
from app.services.fbref_index import discover_squad_urls, load_map
from app.services.player_store import player_store, squad_index, squad_source, team_slug

# Standard 23-man composition by taxonomy position (sums to 23).
SQUAD_TEMPLATE: List[tuple[str, int]] = [
    ("GK", 3), ("CB", 4), ("LB", 2), ("RB", 2), ("CDM", 2),
    ("CM", 3), ("CAM", 1), ("LW", 2), ("RW", 2), ("ST", 2),
]

# Per-90 attacking profile of an average international starter, by position.
_ATT_TEMPLATE: Dict[str, Dict[str, float]] = {
    "GK":  dict(xg90=0.0, xa90=0.0, shots90=0.0, progressive_passes90=1.0, shot_creating_actions90=0.2, dribbles_completed90=0.1),
    "CB":  dict(xg90=0.03, xa90=0.02, shots90=0.2, progressive_passes90=0.9, shot_creating_actions90=0.4, dribbles_completed90=0.1),
    "LB":  dict(xg90=0.05, xa90=0.12, shots90=0.4, progressive_passes90=3.5, shot_creating_actions90=1.4, dribbles_completed90=0.6),
    "RB":  dict(xg90=0.05, xa90=0.12, shots90=0.4, progressive_passes90=3.5, shot_creating_actions90=1.4, dribbles_completed90=0.6),
    "CDM": dict(xg90=0.05, xa90=0.08, shots90=0.5, progressive_passes90=5.0, shot_creating_actions90=1.2, dribbles_completed90=0.4),
    "CM":  dict(xg90=0.10, xa90=0.15, shots90=1.0, progressive_passes90=5.5, shot_creating_actions90=2.5, dribbles_completed90=0.8),
    "CAM": dict(xg90=0.20, xa90=0.25, shots90=1.8, progressive_passes90=4.0, shot_creating_actions90=3.5, dribbles_completed90=1.5),
    "LW":  dict(xg90=0.30, xa90=0.25, shots90=2.2, progressive_passes90=3.0, shot_creating_actions90=3.5, dribbles_completed90=2.0),
    "RW":  dict(xg90=0.30, xa90=0.25, shots90=2.2, progressive_passes90=3.0, shot_creating_actions90=3.5, dribbles_completed90=2.0),
    "ST":  dict(xg90=0.50, xa90=0.15, shots90=3.0, progressive_passes90=1.5, shot_creating_actions90=2.0, dribbles_completed90=1.0),
}


def _strength_factor(elo: float) -> float:
    """Map team Elo onto a [0.80, 1.20] attacking scaling factor."""
    s = max(0.0, min(1.0, (elo - 1500.0) / (2100.0 - 1500.0)))
    return round(0.80 + 0.40 * s, 3)


def synthesize_squad(team: str) -> dict:
    """Deterministic baseline squad from teams.json strength signals."""
    profile = load_teams()[team]
    factor = _strength_factor(profile.elo)
    players: List[dict] = []
    for pos, count in SQUAD_TEMPLATE:
        att = _ATT_TEMPLATE[pos]
        dfn = player_scraper._DEF_DEFAULTS.get(pos, player_scraper._DEF_DEFAULTS["CM"])
        for n in range(1, count + 1):
            players.append({
                "name": f"{team} {pos}{n}",
                "team": team,
                "position": pos,
                "position_group": GROUP_OF[pos],
                "age": 26,
                "caps": 20,
                "starts": 15,
                "international_goals": 0,
                "assists": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "club": "",
                "minutes_played": 1800,
                "is_starter": n == 1,
                "xg90": round(att["xg90"] * factor, 3),
                "xa90": round(att["xa90"] * factor, 3),
                "shots90": round(att["shots90"] * factor, 3),
                "progressive_passes90": round(att["progressive_passes90"] * factor, 3),
                "shot_creating_actions90": round(att["shot_creating_actions90"] * factor, 3),
                "dribbles_completed90": round(att["dribbles_completed90"] * factor, 3),
                "tackles_won_pct": dfn["tackles_won_pct"],
                "interceptions90": round(dfn["interceptions90"] * factor, 3),
                "clearances90": dfn["clearances90"],
                "pressures90": dfn["pressures90"],
                "pressures_won_pct": dfn["pressures_won_pct"],
                "aerial_won_pct": dfn["aerial_won_pct"],
            })
    return {
        "team": team,
        "slug": team_slug(team),
        "source": "synthetic",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "players": players,
    }


def bootstrap_team(team: str, *, force: bool) -> str:
    """Ensure `team` has a squad file; returns the resulting source label."""
    slug = team_slug(team)
    existing = squad_source(slug)
    if existing == "seed" and not force:
        return "seed (kept)"
    if existing and existing != "synthetic" and not force:
        return f"{existing} (kept)"

    doc, source, _ = player_scraper.scrape_squad(team)
    if source == "scraped" and doc and doc.get("players"):
        return "scraped"

    # FBref had nothing usable -> deterministic synthetic baseline.
    player_store.save_doc(slug, synthesize_squad(team))
    return "synthetic"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Populate reference squads for all 48 teams.")
    parser.add_argument("--team", help="Only bootstrap this team (canonical name).")
    parser.add_argument("--force", action="store_true", help="Re-scrape teams that already have a file.")
    parser.add_argument("--discover-only", action="store_true", help="Only refresh the FBref url-map and exit.")
    args = parser.parse_args(argv)

    refreshed = discover_squad_urls()
    print(f"FBref url-map: {len(refreshed)} teams resolved ({len(load_map())} committed).")
    if args.discover_only:
        return 0

    teams = [args.team] if args.team else sorted(load_teams().keys())
    for team in teams:
        if team not in load_teams():
            print(f"  ! unknown team '{team}', skipping")
            continue
        label = bootstrap_team(team, force=args.force)
        print(f"  {team:<28} -> {label}")

    index = squad_index()
    print(f"\nCoverage: {len(index)}/48 teams have squad files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
