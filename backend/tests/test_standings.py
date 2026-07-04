"""Tests for the real final group standings (FIFA tiebreakers) and the
standings-derived R32 seeding that fills slots the scraper hasn't provided."""

import pytest

from app.engine.bracket import load_bracket, r32_match_numbers, third_receiving_groups
from app.engine.loader import get_draw, get_fixtures, load_teams
from app.services import standings
from app.services.knockout_store import knockout_store
from app.services.results_store import results_store
from app.services.standings import (
    _rank_group,
    group_standings,
    qualified_thirds,
    real_r32_seeding,
)


@pytest.fixture(autouse=True)
def iso_stores(tmp_path):
    """Isolate both persisted stores and clear the version-keyed standings
    cache (swapping records directly does not bump the store version)."""
    rs, ks = results_store, knockout_store
    saved = (rs.path, rs._records, ks.path, ks._records)
    rs.path = tmp_path / "results.json"
    rs._records = {}
    ks.path = tmp_path / "knockout_results.json"
    ks._records = {}
    standings._computed.cache_clear()
    yield
    rs.path, rs._records, ks.path, ks._records = saved
    standings._computed.cache_clear()


def _finalize_all_groups():
    """Every group match final; the team earlier in draw order always wins 2-0,
    so each group's standings equal its draw order and every third-placed team
    finishes on identical (3 pts, -2 GD, 2 GF) — thirds fall through to Elo."""
    order = {g: [t.name for t in teams] for g, teams in get_draw().items()}
    for f in get_fixtures():
        idx = order[f["group"]]
        gh, ga = (2, 0) if idx.index(f["home"]) < idx.index(f["away"]) else (0, 2)
        results_store.upsert(f["id"], gh, ga, status="final", source="manual")


# ---------------------------------------------------------------- ranking

def test_rank_group_fifa_tiebreakers_head_to_head():
    names = ["T0", "T1", "T2", "T3"]
    elo = {"T0": 1800.0, "T1": 1500.0, "T2": 2000.0, "T3": 1600.0}
    results = {
        ("T1", "T2"): (1, 0),
        ("T1", "T3"): (1, 0),
        ("T0", "T1"): (1, 0),
        ("T2", "T0"): (1, 0),
        ("T2", "T3"): (1, 0),
        ("T0", "T3"): (0, 0),
    }
    ranked = [r.name for r in _rank_group(names, results, elo)]
    # T1 and T2 tie on pts/GD/GF (6, +1, 2); head-to-head puts T1 first even
    # though T2's Elo is far higher.
    assert ranked == ["T1", "T2", "T0", "T3"]


# ---------------------------------------------------------------- gating

def test_standings_none_while_any_match_unplayed():
    assert group_standings() is None
    assert qualified_thirds() is None
    f = get_fixtures()[0]
    results_store.upsert(f["id"], 1, 0, status="final", source="manual")
    assert group_standings() is None
    seeded = real_r32_seeding({})
    assert all(pair == (None, None) for pair in seeded.values())


# ---------------------------------------------------------------- standings

def test_full_results_produce_standings_and_best_thirds():
    _finalize_all_groups()
    st = group_standings()
    draw = get_draw()
    assert st is not None and len(st) == 12
    for g, teams in draw.items():
        assert st[g] == [t.name for t in teams]
    thirds = qualified_thirds()
    assert thirds is not None
    assert len(thirds) == 8 and len(set(thirds)) == 8
    # Every third ties on pts/GD/GF here, so the 8 highest-Elo thirds advance.
    third_elo = {g: draw[g][2].elo for g in draw}
    expected = set(sorted(third_elo, key=third_elo.get, reverse=True)[:8])
    assert set(thirds) == expected


# ---------------------------------------------------------------- seeding

def test_full_results_seed_the_whole_r32():
    _finalize_all_groups()
    seeded = real_r32_seeding({})
    assert set(seeded) == set(r32_match_numbers())
    names = [n for pair in seeded.values() for n in pair]
    assert None not in names
    assert len(set(names)) == 32
    st = group_standings()
    # Non-third slots decode straight from the template: match 73 = 2A vs 2B.
    assert seeded[73] == (st["A"][1], st["B"][1])
    # A third-placed team never faces the winner of its own group.
    teams = load_teams()
    advancing_thirds = {st[g][2] for g in qualified_thirds()}
    for tie in load_bracket()["r32"]:
        if tie["away"] != "3X":
            continue
        g = tie["home"][1]
        home, away = seeded[tie["match"]]
        assert home == st[g][0]
        assert away in advancing_thirds
        assert teams[away].group != g
    assert set(third_receiving_groups()) <= set(st)


def test_scraped_record_overrides_derived_seeding():
    _finalize_all_groups()
    knockout_store.upsert(73, "Spain", "Iraq", status="scheduled", source="scraped")
    seeded = real_r32_seeding(knockout_store.all())
    assert seeded[73] == ("Spain", "Iraq")
    assert all(pair != (None, None) for pair in seeded.values())
