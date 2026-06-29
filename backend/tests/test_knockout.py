"""Tests for the knockout stage: bracket template integrity, best-thirds
allocation, R32 seeding, the decisive tie resolver, the title-odds Monte Carlo
and the projected-bracket endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.engine import EloPoissonModel, KnockoutSimulator, MonteCarloSimulator, seed_r32
from app.engine.bracket import allocate_thirds, load_bracket, third_receiving_groups
from app.engine.loader import get_draw, load_teams
from app.main import app

client = TestClient(app)

_MODEL = EloPoissonModel()


def _group_order():
    """group -> 4 team names in seed order (a deterministic stand-in standings)."""
    return {g: [t.name for t in teams] for g, teams in get_draw().items()}


# ---------------------------------------------------------------- template

def test_bracket_template_integrity():
    b = load_bracket()
    assert len(b["r32"]) == 16
    assert {t["match"] for t in b["r32"]} == set(range(73, 89))
    assert {t["match"] for t in b["tree"]} == set(range(89, 105))
    third_slots = [t for t in b["r32"] if t["away"] == "3X"]
    assert len(third_slots) == 8
    # final is match 104, third-place play-off is 103
    rounds = {t["match"]: t["round"] for t in b["tree"]}
    assert rounds[104] == "F" and rounds[103] == "3P"


def test_third_receiving_groups():
    assert third_receiving_groups() == ("E", "I", "A", "L", "D", "G", "B", "K")


# ---------------------------------------------------------------- allocation

def test_allocate_thirds_avoids_own_group_and_is_bijection():
    opp = third_receiving_groups()
    qualified = ["A", "B", "C", "D", "E", "F", "G", "H"]  # overlaps A,B,D,E,G
    alloc = allocate_thirds(qualified, opp)
    assert set(alloc.keys()) == set(opp)
    assert sorted(alloc.values()) == sorted(qualified)  # bijection
    for winner_group, third_group in alloc.items():
        assert winner_group != third_group  # no own-group clash


def test_allocate_thirds_wrong_count_raises():
    with pytest.raises(ValueError):
        allocate_thirds(["A", "B"], third_receiving_groups())


# ---------------------------------------------------------------- seeding

def test_seed_r32_fills_32_distinct_real_teams():
    order = _group_order()
    qualified = ["C", "F", "H", "J", "E", "I", "A", "L"]
    seeded = seed_r32(order, qualified)
    assert set(seeded.keys()) == set(range(73, 89))
    names = [n for tie in seeded.values() for n in tie]
    assert len(names) == 32
    assert len(set(names)) == 32  # all distinct
    valid = set(load_teams())
    assert set(names) <= valid
    # no third-placed team faces the winner of its own group
    for grp in qualified:
        winner = order[grp][0]
        third = order[grp][2]
        for home, away in seeded.values():
            if third in (home, away):
                assert winner not in (home, away)


# ---------------------------------------------------------------- resolver

def test_resolve_knockout_is_always_decisive():
    mc = MonteCarloSimulator(_MODEL, seed=7)
    teams = load_teams()
    a, b = teams["Spain"], teams["Haiti"]
    for _ in range(200):
        winner, loser = mc._resolve_knockout(a, b)
        assert {winner, loser} == {a.name, b.name}
        assert winner != loser


def test_resolve_knockout_favours_the_stronger_side():
    mc = MonteCarloSimulator(_MODEL, seed=11)
    teams = load_teams()
    strong = max(teams.values(), key=lambda t: t.elo)
    weak = min(teams.values(), key=lambda t: t.elo)
    wins = sum(
        mc._resolve_knockout(strong, weak)[0] == strong.name for _ in range(400)
    )
    assert wins > 280  # heavy favourite clears 70%


# ---------------------------------------------------------------- title MC

def test_knockout_sim_probabilities_are_coherent():
    sim = KnockoutSimulator(_MODEL, get_draw(), seed=2026)
    table = sim.simulate(n_sims=600)
    assert len(table) == 48
    # exactly one champion, two finalists, four semifinalists per run
    assert abs(sum(r["champion"] for r in table) - 100) < 5
    assert abs(sum(r["reach_final"] for r in table) - 200) < 6
    assert abs(sum(r["reach_r16"] for r in table) - 1600) < 12
    # monotyped: reaching an earlier round is at least as likely as a later one
    for r in table:
        assert r["reach_r16"] >= r["reach_qf"] >= r["reach_sf"] >= r["champion"]
        assert r["champion"] >= 0


def test_knockout_sim_is_deterministic_and_ranks_favourites():
    a = KnockoutSimulator(_MODEL, get_draw(), seed=2026).simulate(n_sims=400)
    b = KnockoutSimulator(_MODEL, get_draw(), seed=2026).simulate(n_sims=400)
    assert a == b  # same seed -> identical
    champ = {r["team"]: r["champion"] for r in a}
    teams = load_teams()
    strong = max(teams.values(), key=lambda t: t.elo).name
    weak = min(teams.values(), key=lambda t: t.elo).name
    assert champ[strong] > champ[weak]


# ---------------------------------------------------------------- endpoints

def test_simulate_knockout_endpoint():
    resp = client.post("/api/simulate/knockout", json={"n_sims": 300})
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_sims"] == 300
    assert len(body["table"]) == 48
    champs = [r["champion"] for r in body["table"]]
    assert champs == sorted(champs, reverse=True)  # sorted by title odds


def test_bracket_projection_endpoint():
    resp = client.get("/api/bracket/projection")
    assert resp.status_code == 200
    ties = resp.json()["ties"]
    assert len(ties) == 32  # 16 + 8 + 4 + 2 + 1 + 1
    assert [t["match"] for t in ties] == list(range(73, 105))
    valid = set(load_teams())
    for t in ties:
        assert t["home"] in valid and t["away"] in valid
        assert t["winner"] in (t["home"], t["away"])
    # deterministic projection
    again = client.get("/api/bracket/projection").json()["ties"]
    assert again == ties
