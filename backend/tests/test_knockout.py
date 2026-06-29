"""Tests for the knockout stage: bracket template integrity, best-thirds
allocation, R32 seeding, the decisive tie resolver, the title-odds Monte Carlo
and the projected-bracket endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.engine import EloPoissonModel, KnockoutSimulator, MonteCarloSimulator, seed_r32
from app.engine.bracket import allocate_thirds, load_bracket, third_receiving_groups
from app.engine.loader import get_draw, load_teams
from app.main import app
from app.services.knockout_store import knockout_store, winner_of

client = TestClient(app)

_MODEL = EloPoissonModel()


@pytest.fixture(autouse=True)
def isolated_knockout_store(tmp_path):
    """Point the singleton knockout store at a temp file and reset afterwards,
    so every test starts with an empty (fully projected) bracket."""
    ks = knockout_store
    original_path, original_records = ks.path, ks._records
    ks.path = tmp_path / "knockout_results.json"
    ks._records = {}
    yield ks
    ks.path = original_path
    ks._records = original_records


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
        assert t["source"] == "projected"  # empty store -> all projected
    # deterministic projection
    again = client.get("/api/bracket/projection").json()["ties"]
    assert again == ties


# ---------------------------------------------------------- persisted overlay

def test_knockout_store_winner_uses_penalties():
    rec = knockout_store.upsert(
        73, "Spain", "France", 1, 1, pens_home=4, pens_away=2, status="final"
    )
    assert winner_of(rec) == "Spain"
    assert winner_of(knockout_store.get(73)) == "Spain"
    # a draw with no shootout recorded is undecidable
    assert winner_of({"status": "final", "home": "A", "away": "B",
                      "goals_home": 0, "goals_away": 0,
                      "pens_home": None, "pens_away": None}) is None


def test_knockout_store_rejects_out_of_range_match():
    with pytest.raises(ValueError):
        knockout_store.upsert(50, "Spain", "France")


def test_play_bracket_respects_fixed_ko():
    """A fixed knockout result overrides the simulated tie, win or lose."""
    sim = KnockoutSimulator(_MODEL, get_draw(), seed=3)
    order = _group_order()
    seeded = seed_r32(order, ["C", "F", "H", "J", "E", "I", "A", "L"])
    home73, away73 = seeded[73]
    winners, losers = sim._play_bracket(seeded, {73: away73})
    assert winners[73] == away73 and losers[73] == home73
    # the forced winner is carried into the R16 tie fed by W73 (match 90)
    assert away73 in (winners[90], losers[90])


def _full_fixed_results():
    """All recorded group results keyed in BOTH orientations, so every group is
    fully conditioned and the seeding becomes deterministic (the production
    endpoint keys a single orientation, which leaves the seeding stochastic)."""
    from app.engine.loader import get_fixtures
    from app.services.results_store import results_store

    by_group: dict = {}
    for f in get_fixtures():
        rec = results_store.get(f["id"])
        if not rec or rec["status"] != "final":
            continue
        gh, ga = rec["goals_home"], rec["goals_away"]
        d = by_group.setdefault(f["group"], {})
        d[(f["home"], f["away"])] = (gh, ga)
        d[(f["away"], f["home"])] = (ga, gh)
    return by_group


def _deterministic_slot(match: int, fixed: dict):
    """The two teams occupying a knockout slot, via the simulator's own ordering."""
    sim = KnockoutSimulator(_MODEL, get_draw(), seed=2026)
    order, thirds = {}, []
    for g, teams in sim.draw.items():
        ranked = sim.mc.simulate_group_once(teams, fixed.get(g) or None)
        order[g] = [r.name for r in ranked]
        thirds.append(ranked[2])
    thirds.sort(key=lambda r: (r.pts, r.gd, r.gf, r.elo), reverse=True)
    qualified = [sim._by_name[r.name].group for r in thirds[:8]]
    return seed_r32(order, qualified)[match]


def test_simulate_conditions_on_fixed_knockout_result():
    """A recorded R32 final eliminates the loser and guarantees the winner."""
    fixed = _full_fixed_results()
    home73, away73 = _deterministic_slot(73, fixed)
    sim = KnockoutSimulator(_MODEL, get_draw(), seed=2026)
    table = sim.simulate(n_sims=200, fixed_results=fixed, fixed_ko={73: home73})
    row = {r["team"]: r for r in table}
    assert row[away73]["reach_qf"] == 0.0       # loser out in R32
    assert row[away73]["reach_r16"] == 0.0
    assert row[home73]["reach_r16"] == 100.0    # winner always through


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
    # a still-undrawn later round stays projected
    assert next(t for t in ties if t["match"] == 104)["source"] == "projected"
