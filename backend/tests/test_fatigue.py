"""Tests for the heuristic fatigue model: the index math (rest deficit,
extra-time surcharge, cumulative load), history derivation from the stores,
the engine no-op guarantee at fatigue = 0, and its effect on the knockout
simulator and the bracket projection."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.engine import EloPoissonModel, KnockoutSimulator
from app.engine.bracket import r32_match_numbers
from app.engine.config import ModelConfig
from app.engine.core import ParameterOverrides, compute_lambdas
from app.engine.loader import load_teams
from app.main import app
from app.services import fatigue, metrics, standings
from app.services.fatigue import FatigueConfig, fatigue_index, knockout_fatigue
from app.services.knockout_store import knockout_store
from app.services.results_store import results_store
from app.services.team_adjust_store import team_adjust_store

client = TestClient(app)

_MODEL = EloPoissonModel()
_CFG = FatigueConfig()


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path):
    """Temp-path all three singleton stores and clear the derivation caches
    (record swapping does not bump the version counters)."""
    ks, rs, ta = knockout_store, results_store, team_adjust_store
    saved = (ks.path, ks._records, rs.path, rs._records, ta.path, ta._records)
    ks.path = tmp_path / "knockout_results.json"
    ks._records = {}
    rs.path = tmp_path / "results.json"
    rs._records = {}
    ta.path = tmp_path / "team_adjustments.json"
    ta._records = {}
    standings._computed.cache_clear()
    fatigue._histories.cache_clear()
    metrics._adjusted.cache_clear()
    yield
    ks.path, ks._records, rs.path, rs._records, ta.path, ta._records = saved
    standings._computed.cache_clear()
    fatigue._histories.cache_clear()
    metrics._adjusted.cache_clear()


# ---------------------------------------------------------------- index math

def test_fatigue_index_rest_deficit_bounds():
    history = [(date(2026, 7, 1), False)]
    target = date(2026, 7, 6)  # 5 rest days -> no deficit
    assert fatigue_index(history, target, None, 0) == 0.0
    # 2 rest days -> maximal deficit (0.6 rest weight only; no ET, no load)
    assert fatigue_index(history, date(2026, 7, 3), None, 0) == pytest.approx(0.6)
    # 3 rest days sits on the ramp: (5 - 3) / 3 -> 2/3 of the rest weight
    mid = _CFG.rest_weight * ((5.0 - 3.0) / 3.0)
    assert fatigue_index(history, date(2026, 7, 4), None, 0) == pytest.approx(
        mid, abs=1e-3
    )
    # no history and no feeder -> fully fresh
    assert fatigue_index([], date(2026, 7, 6), None, 0) == 0.0


def test_fatigue_index_extra_time_flag():
    base = [(date(2026, 7, 1), False)]
    pens = [(date(2026, 7, 1), True)]
    target = date(2026, 7, 6)  # full rest either way
    assert fatigue_index(pens, target, None, 0) - fatigue_index(
        base, target, None, 0
    ) == pytest.approx(_CFG.extra_time_weight)
    # ET on an older game (not the immediately preceding outing) does not count
    older_et = [(date(2026, 6, 25), True), (date(2026, 7, 1), False)]
    assert fatigue_index(older_et, target, None, 0) == fatigue_index(
        base, target, None, 0
    )
    # a feeder later than the real ET game also suppresses the surcharge
    assert fatigue_index(pens, target, date(2026, 7, 3), 0) == pytest.approx(
        _CFG.rest_weight * (2.0 / 3.0), abs=1e-3
    )


def test_fatigue_index_load_component_and_clamp():
    # 5 real games before a QF (depth 2): extra = max(5, 3+2) - 3 = 2 -> 0.5 load
    history = [(date(2026, 6, 11 + 3 * i), False) for i in range(5)]
    target = date(2026, 7, 20)
    assert fatigue_index(history, target, None, 2) == pytest.approx(
        round(_CFG.load_weight * 0.5, 3)
    )
    # implied depth outweighs a shorter real history (empty history, final depth)
    assert fatigue_index([], target, None, 4) == pytest.approx(_CFG.load_weight)
    # everything maxed still clamps to <= 1
    packed = [(date(2026, 7, 18 - i), True) for i in range(8)]
    assert fatigue_index(packed, date(2026, 7, 19), None, 4) <= 1.0


def test_team_histories_uses_record_date_then_schedule():
    # record with its own date wins over the static schedule
    knockout_store.upsert(
        73, "Spain", "France", 1, 0, status="final", source="scraped",
        date="2026-06-27",
    )
    # record without a date falls back to the template (match 74 -> 06-29)
    knockout_store.upsert(74, "Brazil", "Japan", 2, 1, status="final", source="scraped")
    histories = fatigue.team_histories()
    assert (date(2026, 6, 27), False) in histories["Spain"]
    assert (date(2026, 6, 29), False) in histories["Brazil"]


def test_histories_flag_extra_time_from_penalties():
    knockout_store.upsert(
        75, "Germany", "Paraguay", 1, 1, pens_home=3, pens_away=4,
        status="final", source="scraped",
    )
    histories = fatigue.team_histories()
    assert histories["Germany"][-1][1] is True
    assert histories["Paraguay"][-1][1] is True


# ---------------------------------------------------------------- engine hook

def test_fatigue_zero_is_exact_engine_noop():
    cfg = ModelConfig()
    teams = load_teams()
    spain, france = teams["Spain"], teams["France"]
    baseline = compute_lambdas(spain, france, cfg)
    zeroed = compute_lambdas(
        spain, france, cfg,
        overrides=ParameterOverrides(home_fatigue=0.0, away_fatigue=0.0),
    )
    assert baseline == zeroed


def test_fatigue_penalises_attack_and_defense():
    cfg = ModelConfig()
    teams = load_teams()
    spain, france = teams["Spain"], teams["France"]
    lam_h0, lam_a0 = compute_lambdas(spain, france, cfg)
    lam_h1, lam_a1 = compute_lambdas(
        spain, france, cfg, overrides=ParameterOverrides(home_fatigue=1.0)
    )
    assert lam_h1 < lam_h0  # tired side scores less
    assert lam_a1 > lam_a0  # and concedes more


def test_config_rejects_out_of_range_fatigue_weights():
    with pytest.raises(ValueError):
        ModelConfig(fatigue_attack_weight=1.5)
    with pytest.raises(ValueError):
        ModelConfig(fatigue_defense_weight=-0.1)


# ---------------------------------------------------------------- simulator

def _distinct_r32():
    names = list(load_teams())[:32]
    return {
        match: (names[2 * i], names[2 * i + 1])
        for i, match in enumerate(r32_match_numbers())
    }


def test_simulator_without_fatigue_fn_is_unchanged():
    seeded = _distinct_r32()
    a = KnockoutSimulator(_MODEL, load_teams(), seed=2026).simulate(seeded, n_sims=400)
    b = KnockoutSimulator(
        _MODEL, load_teams(), seed=2026, fatigue_fn=None
    ).simulate(seeded, n_sims=400)
    assert a == b


def test_simulator_fatigue_lowers_target_team_odds():
    seeded = _distinct_r32()
    teams = load_teams()
    target = max(
        (n for pair in seeded.values() for n in pair), key=lambda n: teams[n].elo
    )
    seen_matches = set()

    def tire_target(match, home, away):
        seen_matches.add(match)
        return ParameterOverrides(
            home_fatigue=1.0 if home == target else 0.0,
            away_fatigue=1.0 if away == target else 0.0,
        )

    fresh = KnockoutSimulator(_MODEL, teams, seed=2026).simulate(seeded, n_sims=1500)
    tired = KnockoutSimulator(
        _MODEL, teams, seed=2026, fatigue_fn=tire_target
    ).simulate(seeded, n_sims=1500)
    champ_fresh = next(r for r in fresh if r["team"] == target)["champion"]
    champ_tired = next(r for r in tired if r["team"] == target)["champion"]
    assert champ_tired < champ_fresh
    assert seen_matches <= set(range(73, 105)) and seen_matches


# ---------------------------------------------------------------- endpoints

def test_knockout_fatigue_provider_reflects_pens_burden():
    """A shootout in the immediately preceding game raises a team's fatigue
    for the next tie relative to a 90-minute win."""
    knockout_store.upsert(
        75, "Germany", "Paraguay", 1, 1, pens_home=3, pens_away=4,
        status="final", source="scraped",
    )
    knockout_store.upsert(73, "South Africa", "Canada", 0, 1,
                          status="final", source="scraped")
    # R16 match 90 = W73 v W75, played 2026-07-04
    ov = knockout_fatigue(90, "Canada", "Paraguay")
    assert ov.away_fatigue > ov.home_fatigue
    assert ov.away_fatigue - ov.home_fatigue == pytest.approx(
        _CFG.extra_time_weight, abs=2e-3
    )


def test_bracket_projection_shifts_probability_with_pens_burden():
    """The projected R16 tie prices in the shootout burden: the pens winner's
    win probability drops versus the identical matchup without the shootout."""
    def project_p_home():
        ties = client.get("/api/bracket/projection").json()["ties"]
        return next(t for t in ties if t["match"] == 90)["p_home"]

    knockout_store.upsert(90, "Canada", "Paraguay", status="scheduled", source="scraped")
    knockout_store.upsert(73, "South Africa", "Canada", 0, 1,
                          status="final", source="scraped")
    knockout_store.upsert(75, "Germany", "Paraguay", 1, 0,
                          status="final", source="scraped")
    p_no_pens = project_p_home()

    knockout_store.upsert(
        75, "Germany", "Paraguay", 1, 1, pens_home=3, pens_away=4,
        status="final", source="scraped",
    )
    p_with_pens = project_p_home()
    assert p_with_pens > p_no_pens  # tired Paraguay -> Canada's odds rise


def test_bracket_projection_use_results_false_has_no_fatigue():
    """The a-priori bracket ignores fatigue entirely (and stays pending on an
    empty store) — symmetric with ignoring the stores."""
    knockout_store.upsert(
        75, "Germany", "Paraguay", 1, 1, pens_home=3, pens_away=4,
        status="final", source="scraped",
    )
    ties = client.get("/api/bracket/projection?use_results=false").json()["ties"]
    assert all(t["status"] == "pending" for t in ties)
