"""Tests for the knockout stage: bracket template integrity, store-seeded R32,
the decisive tie resolver, the title-odds Monte Carlo and the projected-bracket
endpoint (now driven entirely by scraped results, no group simulation)."""

import pytest
from fastapi.testclient import TestClient

from app.engine import EloPoissonModel, KnockoutSimulator, seeded_r32_from_store
from app.engine.bracket import load_bracket, r32_match_numbers
from app.engine.loader import get_draw, get_fixtures, load_teams
from app.main import app
from app.services import standings
from app.services.knockout_store import knockout_store, winner_of
from app.services.results_store import results_store

client = TestClient(app)

_MODEL = EloPoissonModel()


@pytest.fixture(autouse=True)
def isolated_knockout_store(tmp_path):
    """Point both singleton stores at temp files and reset afterwards, so every
    test starts with an empty (fully pending) bracket — an empty results store
    matters too, since complete group results now imply an R32 seeding. The
    standings cache is version-keyed and swapping records does not bump the
    version, so it must be cleared explicitly."""
    ks, rs = knockout_store, results_store
    saved = (ks.path, ks._records, rs.path, rs._records)
    ks.path = tmp_path / "knockout_results.json"
    ks._records = {}
    rs.path = tmp_path / "results.json"
    rs._records = {}
    standings._computed.cache_clear()
    yield ks
    ks.path, ks._records, rs.path, rs._records = saved
    standings._computed.cache_clear()


def _distinct_r32():
    """A full R32 seeding of 32 distinct real teams: match -> (home, away)."""
    names = list(load_teams())[:32]
    return {
        match: (names[2 * i], names[2 * i + 1])
        for i, match in enumerate(r32_match_numbers())
    }


def _seed_store_full():
    """Persist a full, scheduled R32 draw of 32 distinct teams into the store."""
    seeded = _distinct_r32()
    for match, (home, away) in seeded.items():
        knockout_store.upsert(match, home, away, status="scheduled", source="scraped")
    return seeded


def _finalize_all_groups():
    """Every group match final (earlier draw-order team wins 2-0), so the full
    R32 draw becomes derivable from the real standings."""
    order = {g: [t.name for t in teams] for g, teams in get_draw().items()}
    for f in get_fixtures():
        idx = order[f["group"]]
        gh, ga = (2, 0) if idx.index(f["home"]) < idx.index(f["away"]) else (0, 2)
        results_store.upsert(f["id"], gh, ga, status="final", source="manual")


# ---------------------------------------------------------------- template

def test_bracket_template_integrity():
    b = load_bracket()
    assert len(b["r32"]) == 16
    assert {t["match"] for t in b["r32"]} == set(range(73, 89))
    assert {t["match"] for t in b["tree"]} == set(range(89, 105))
    rounds = {t["match"]: t["round"] for t in b["tree"]}
    assert rounds[104] == "F" and rounds[103] == "3P"
    assert r32_match_numbers() == tuple(range(73, 89))


# ---------------------------------------------------------------- store seeding

def test_seeded_r32_empty_store_is_all_pending():
    seeded = seeded_r32_from_store({})
    assert set(seeded.keys()) == set(range(73, 89))
    assert all(pair == (None, None) for pair in seeded.values())


def test_seeded_r32_reads_scraped_matchups():
    _seed_store_full()
    seeded = seeded_r32_from_store(knockout_store.all())
    names = [n for pair in seeded.values() for n in pair]
    assert len(names) == 32 and len(set(names)) == 32
    assert set(names) <= set(load_teams())


def test_seeded_r32_partial_leaves_rest_pending():
    knockout_store.upsert(73, "Spain", "France", status="scheduled", source="scraped")
    seeded = seeded_r32_from_store(knockout_store.all())
    assert seeded[73] == ("Spain", "France")
    assert seeded[74] == (None, None)


# ---------------------------------------------------------------- resolver

def test_resolve_knockout_is_always_decisive():
    sim = KnockoutSimulator(_MODEL, load_teams(), seed=7)
    for _ in range(200):
        winner, loser = sim._resolve_knockout("Spain", "Haiti")
        assert {winner, loser} == {"Spain", "Haiti"}
        assert winner != loser


def test_resolve_knockout_favours_the_stronger_side():
    teams = load_teams()
    sim = KnockoutSimulator(_MODEL, teams, seed=11)
    strong = max(teams.values(), key=lambda t: t.elo).name
    weak = min(teams.values(), key=lambda t: t.elo).name
    wins = sum(sim._resolve_knockout(strong, weak)[0] == strong for _ in range(400))
    assert wins > 280  # heavy favourite clears 70%


# ---------------------------------------------------------------- title MC

def test_knockout_sim_probabilities_are_coherent():
    seeded = _distinct_r32()
    sim = KnockoutSimulator(_MODEL, load_teams(), seed=2026)
    table = sim.simulate(seeded, n_sims=600)
    assert len(table) == 32  # only the seeded teams accrue odds
    assert abs(sum(r["champion"] for r in table) - 100) < 5
    assert abs(sum(r["reach_final"] for r in table) - 200) < 6
    assert abs(sum(r["reach_r16"] for r in table) - 1600) < 1e-6
    for r in table:
        assert r["reach_r16"] >= r["reach_qf"] >= r["reach_sf"] >= r["reach_final"]
        assert r["reach_final"] >= r["champion"] >= 0


def test_knockout_sim_empty_seed_returns_no_rows():
    sim = KnockoutSimulator(_MODEL, load_teams(), seed=1)
    assert sim.simulate(seeded_r32_from_store({}), n_sims=100) == []


def test_knockout_sim_is_deterministic_and_ranks_favourites():
    seeded = _distinct_r32()
    a = KnockoutSimulator(_MODEL, load_teams(), seed=2026).simulate(seeded, n_sims=400)
    b = KnockoutSimulator(_MODEL, load_teams(), seed=2026).simulate(seeded, n_sims=400)
    assert a == b  # same seed -> identical
    champ = {r["team"]: r["champion"] for r in a}
    teams = load_teams()
    seeded_names = [n for pair in seeded.values() for n in pair]
    strong = max(seeded_names, key=lambda n: teams[n].elo)
    weak = min(seeded_names, key=lambda n: teams[n].elo)
    assert champ[strong] > champ[weak]


def test_play_bracket_respects_fixed_ko():
    """A fixed knockout result overrides the simulated tie, win or lose."""
    seeded = _distinct_r32()
    sim = KnockoutSimulator(_MODEL, load_teams(), seed=3)
    home73, away73 = seeded[73]
    winners, losers = sim._play_bracket(seeded, {73: away73})
    assert winners[73] == away73 and losers[73] == home73
    # the forced winner is carried into the R16 tie fed by W73 (match 90)
    assert away73 in (winners[90], losers[90])


def test_play_bracket_pending_slot_stops_progression():
    """A pending R32 tie leaves its slot — and everything downstream — unresolved."""
    seeded = _distinct_r32()
    seeded[73] = (None, None)  # match 90 is fed by W73
    sim = KnockoutSimulator(_MODEL, load_teams(), seed=5)
    winners, _ = sim._play_bracket(seeded)
    assert 73 not in winners
    assert 90 not in winners  # depends on W73


# ---------------------------------------------------------------- endpoints

def test_simulate_knockout_endpoint_empty_store():
    resp = client.post("/api/simulate/knockout", json={"n_sims": 300})
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_sims"] == 300
    assert body["table"] == []  # nothing drawn yet


def test_simulate_knockout_endpoint_seeded():
    _seed_store_full()
    resp = client.post("/api/simulate/knockout", json={"n_sims": 300})
    assert resp.status_code == 200
    table = resp.json()["table"]
    assert len(table) == 32
    champs = [r["champion"] for r in table]
    assert champs == sorted(champs, reverse=True)  # sorted by title odds


def test_bracket_projection_empty_store_is_all_pending():
    resp = client.get("/api/bracket/projection")
    assert resp.status_code == 200
    ties = resp.json()["ties"]
    assert len(ties) == 32  # 16 + 8 + 4 + 2 + 1 + 1
    assert [t["match"] for t in ties] == list(range(73, 105))
    for t in ties:
        assert t["status"] == "pending"
        assert t["home"] is None and t["away"] is None and t["winner"] is None


def test_bracket_projection_resolves_seeded_r32():
    _seed_store_full()
    ties = {t["match"]: t for t in client.get("/api/bracket/projection").json()["ties"]}
    valid = set(load_teams())
    # R32 ties carry the scraped matchup; the final is now projectable.
    for match in range(73, 89):
        t = ties[match]
        assert t["source"] == "scraped" and t["status"] == "scheduled"
        assert t["home"] in valid and t["away"] in valid
        assert t["winner"] in (t["home"], t["away"])
    final = ties[104]
    assert final["status"] == "scheduled" and final["winner"] in valid
    # deterministic
    again = {t["match"]: t for t in client.get("/api/bracket/projection").json()["ties"]}
    assert again == ties


def test_bracket_projection_falls_back_to_group_standings():
    """Complete group results + empty knockout store => the whole bracket is
    derivable: no pending ties, R32 seeded from the real standings."""
    _finalize_all_groups()
    ties = client.get("/api/bracket/projection").json()["ties"]
    assert len(ties) == 32
    assert all(t["status"] == "scheduled" for t in ties)
    r32 = [t for t in ties if t["round"] == "R32"]
    valid = set(load_teams())
    assert len(r32) == 16 and all(t["source"] == "projected" for t in r32)
    seeded_names = [n for t in r32 for n in (t["home"], t["away"])]
    assert len(set(seeded_names)) == 32 and set(seeded_names) <= valid
    assert next(t for t in ties if t["match"] == 104)["winner"] in valid


def test_bracket_projection_use_results_false_stays_pending():
    """use_results=False must ignore both stores and the derived standings."""
    _finalize_all_groups()
    _seed_store_full()
    ties = client.get("/api/bracket/projection?use_results=false").json()["ties"]
    assert all(t["status"] == "pending" for t in ties)


def test_simulate_knockout_endpoint_standings_fallback():
    _finalize_all_groups()
    resp = client.post("/api/simulate/knockout", json={"n_sims": 200})
    assert resp.status_code == 200
    table = resp.json()["table"]
    assert len(table) == 32
    assert abs(sum(r["champion"] for r in table) - 100) < 5


# ---------------------------------------------------------- persisted overlay

def test_knockout_store_winner_uses_penalties():
    rec = knockout_store.upsert(
        73, "Spain", "France", 1, 1, pens_home=4, pens_away=2, status="final"
    )
    assert winner_of(rec) == "Spain"
    assert winner_of(knockout_store.get(73)) == "Spain"
    assert winner_of({"status": "final", "home": "A", "away": "B",
                      "goals_home": 0, "goals_away": 0,
                      "pens_home": None, "pens_away": None}) is None


def test_knockout_store_rejects_out_of_range_match():
    with pytest.raises(ValueError):
        knockout_store.upsert(50, "Spain", "France")


def test_fixed_knockout_helper_uses_penalty_winner():
    """main._fixed_knockout maps each final to its real winner (pens tie-break)."""
    from app.main import _fixed_knockout

    knockout_store.upsert(73, "Spain", "France", 1, 1, pens_home=2, pens_away=4,
                          status="final", source="scraped")
    knockout_store.upsert(85, "Brazil", "Croatia", 3, 0, status="final", source="scraped")
    knockout_store.upsert(86, "Portugal", "Belgium", status="scheduled")  # not final
    assert _fixed_knockout() == {73: "France", 85: "Brazil"}


def test_bracket_projection_overlays_scraped_final():
    knockout_store.upsert(73, "Spain", "France", 2, 1, status="final", source="scraped")
    ties = client.get("/api/bracket/projection").json()["ties"]
    t73 = next(t for t in ties if t["match"] == 73)
    assert t73["source"] == "scraped" and t73["status"] == "final"
    assert (t73["home"], t73["away"]) == ("Spain", "France")
    assert (t73["goals_home"], t73["goals_away"]) == (2, 1)
    assert t73["winner"] == "Spain"
    # with the rest of the R32 undrawn, downstream ties stay pending
    assert next(t for t in ties if t["match"] == 104)["status"] == "pending"
