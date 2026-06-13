"""Tests for the per-game player analyzer: PPS, matchup analytics, the optimal
lineup selector, and the four new API endpoints. All offline and deterministic,
driven by the seed squads in app/data/players."""

import math
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.engine import build_lineup, optimal_xi, score_squad
from app.engine.lineup_analyzer import (
    analyze_lineups,
    formation_strength_index,
    pressing_intensity,
)
from app.engine.player_models import FORMATIONS, POSITIONS, slot_fit
from app.engine.player_scorer import player_performance_score
from app.main import app
from app.services.player_scraper import normalize_position
from app.services.player_store import get_squad, team_slug

client = TestClient(app)

# Canonical strong XIs per seed team (slot order matches 4-3-3).
SPAIN_433 = [
    "Unai Simón", "Marc Cucurella", "Pau Cubarsí", "Aymeric Laporte",
    "Dani Carvajal", "Rodri", "Pedri", "Fabián Ruiz",
    "Nico Williams", "Álvaro Morata", "Lamine Yamal",
]
URUGUAY_433 = [
    "Sergio Rochet", "Mathías Olivera", "Ronald Araújo",
    "José María Giménez", "Nahitan Nández", "Manuel Ugarte",
    "Federico Valverde", "Rodrigo Bentancur", "Facundo Pellistri",
    "Darwin Núñez", "Maximiliano Araújo",
]


@pytest.fixture(scope="module")
def spain():
    squad = get_squad("spain")
    assert squad is not None
    return squad


@pytest.fixture(scope="module")
def uruguay():
    squad = get_squad("uruguay")
    assert squad is not None
    return squad


@pytest.fixture(scope="module")
def spain_lineup(spain):
    by_name = {p.name: p for p in spain}
    return build_lineup("4-3-3", [by_name[n] for n in SPAIN_433])


@pytest.fixture(scope="module")
def uruguay_lineup(uruguay, spain_lineup):
    # Uruguay's optimal XI against Spain, as a realistic opponent.
    best = optimal_xi(uruguay, "4-3-3", spain_lineup, top_n=1)[0]
    by_name = {p.name: p for p in uruguay}
    return build_lineup("4-3-3", [by_name[s["player"]] for s in best["lineup"]])


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def test_seed_squads_present():
    for slug in ("spain", "uruguay", "argentina", "austria"):
        squad = get_squad(slug)
        assert squad is not None and len(squad) == 16


def test_pps_in_unit_interval(spain, uruguay):
    for p in list(spain) + list(uruguay):
        assert 0.0 <= p.pps <= 1.0


def test_star_outscores_backup(spain):
    by_name = {p.name: p for p in spain}
    # An elite forward must rate above a clearly second-choice keeper/squad player.
    assert by_name["Lamine Yamal"].pps > by_name["David Raya"].pps
    assert by_name["Pedri"].pps > by_name["Martín Zubimendi"].pps


def test_score_squad_is_idempotent(spain):
    first = [p.pps for p in spain]
    score_squad(spain)
    assert [p.pps for p in spain] == first


def test_normalize_position_maps_fbref_codes():
    assert normalize_position("GK") == "GK"
    assert normalize_position("DF") == "CB"
    assert normalize_position("MF,FW") == "CM"
    assert normalize_position("FW") == "ST"
    assert normalize_position("AM") == "CAM"
    assert normalize_position("") == "CM"
    assert normalize_position("DF,MF") in POSITIONS


# --------------------------------------------------------------------------- #
# Matchup analytics
# --------------------------------------------------------------------------- #

def test_fsi_bounded_and_symmetric(spain_lineup, uruguay_lineup):
    fsi_fwd, _, _ = formation_strength_index(spain_lineup, uruguay_lineup)
    fsi_rev, _, _ = formation_strength_index(uruguay_lineup, spain_lineup)
    assert 0.0 <= fsi_fwd <= 1.0
    assert fsi_fwd + fsi_rev == pytest.approx(1.0, abs=1e-9)


def test_stronger_side_is_favored(spain_lineup, uruguay_lineup):
    fsi, _, _ = formation_strength_index(spain_lineup, uruguay_lineup)
    assert fsi > 0.5  # Spain (deeper, higher-rated squad) edges Uruguay


def test_analyze_report_shape(spain_lineup, uruguay_lineup):
    rep = analyze_lineups(spain_lineup, uruguay_lineup)
    assert len(rep["dominance_heatmap"]) == 3
    assert all(len(row) == 3 for row in rep["dominance_heatmap"])
    assert all(math.isfinite(v) for row in rep["dominance_heatmap"] for v in row)
    assert rep["positional_battles"], "expected at least one positional battle"
    for b in rep["positional_battles"]:
        assert 0.0 <= b["pms"] <= 1.0
        assert b["side"] in ("home", "away")


def test_pressing_intensity_handles_zero_progression(spain_lineup, uruguay_lineup):
    # Zero out the opponent's ball progression; the epsilon guard keeps PIS finite.
    flat = [(s, replace(p, progressive_passes90=0.0)) for s, p in uruguay_lineup]
    pis = pressing_intensity(spain_lineup, flat)
    assert math.isfinite(pis) and pis >= 0.0


# --------------------------------------------------------------------------- #
# Optimal Lineup Selector
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("formation", ["4-3-3", "4-2-3-1", "4-4-2", "3-5-2"])
def test_optimal_xi_is_valid(spain, uruguay_lineup, formation):
    cands = optimal_xi(spain, formation, uruguay_lineup, top_n=3)
    assert 1 <= len(cands) <= 3
    by_name = {p.name: p for p in spain}
    for cand in cands:
        names = [s["player"] for s in cand["lineup"]]
        assert len(names) == 11
        assert len(set(names)) == 11, "no player may appear twice"
        assert 0.0 <= cand["fsi"] <= 1.0
        for slot in cand["lineup"]:
            nat = by_name[slot["player"]].position
            assert slot_fit(nat, slot["position"]) > 0, (
                f"{slot['player']} ({nat}) is incompatible with slot {slot['position']}"
            )


def test_optimal_xi_candidates_ranked(spain, uruguay_lineup):
    cands = optimal_xi(spain, "4-3-3", uruguay_lineup, top_n=3)
    fsis = [c["fsi"] for c in cands]
    assert fsis == sorted(fsis, reverse=True)


def test_optimal_xi_rejects_short_squad(uruguay_lineup):
    tiny = get_squad("spain")[:5]
    with pytest.raises(ValueError):
        optimal_xi(tiny, "4-3-3", uruguay_lineup)


# --------------------------------------------------------------------------- #
# API endpoints
# --------------------------------------------------------------------------- #

def test_api_get_players():
    resp = client.get("/api/players/spain")
    assert resp.status_code == 200
    body = resp.json()
    assert body["team"] == "Spain"
    assert body["source"] == "seed"
    assert len(body["players"]) == 16
    assert all(0.0 <= p["pps"] <= 1.0 for p in body["players"])


def test_api_get_players_unknown():
    assert client.get("/api/players/wakanda").status_code == 404


def test_api_scrape_players_fallback():
    # live=False -> deterministic seed/cache path, no network.
    resp = client.post("/api/scrape/players", json={"fixture_id": "J3", "live": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["home"]["team"] == "Argentina"
    assert body["away"]["team"] == "Austria"
    assert len(body["home"]["players"]) == 16


def test_api_scrape_players_unknown_fixture():
    resp = client.post("/api/scrape/players", json={"fixture_id": "ZZ9", "live": False})
    assert resp.status_code == 404


def test_api_analyze_lineup():
    uru = optimal_xi(get_squad("uruguay"), "4-3-3",
                     build_lineup("4-3-3", [{p.name: p for p in get_squad("spain")}[n]
                                            for n in SPAIN_433]), top_n=1)[0]
    uru_names = [s["player"] for s in uru["lineup"]]
    resp = client.post("/api/analyze/lineup", json={
        "home_team": "Spain", "away_team": "Uruguay",
        "home_formation": "4-3-3", "away_formation": "4-3-3",
        "home_lineup": SPAIN_433, "away_lineup": uru_names,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert 0.0 <= body["fsi"] <= 1.0
    assert len(body["dominance_heatmap"]) == 3
    assert body["positional_battles"]


def test_api_analyze_lineup_unknown_player():
    resp = client.post("/api/analyze/lineup", json={
        "home_team": "Spain", "away_team": "Uruguay",
        "home_formation": "4-3-3", "away_formation": "4-3-3",
        "home_lineup": ["Nobody"] * 11, "away_lineup": SPAIN_433,
    })
    assert resp.status_code == 422


def test_api_optimal_xi():
    resp = client.post("/api/analyze/optimal-xi", json={
        "team": "Spain", "formation": "4-3-3",
        "opponent_team": "Uruguay", "opponent_formation": "4-3-3",
        "opponent_lineup": URUGUAY_433,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["team"] == "Spain"
    assert 1 <= len(body["candidates"]) <= 3
    assert len(body["candidates"][0]["lineup"]) == 11


def test_api_optimal_xi_bad_formation():
    resp = client.post("/api/analyze/optimal-xi", json={
        "team": "Spain", "formation": "9-9-9",
        "opponent_team": "Uruguay", "opponent_formation": "4-3-3",
        "opponent_lineup": URUGUAY_433,
    })
    assert resp.status_code == 422


def test_api_optimal_xi_without_opponent():
    # The UI fetches a team's best XI before it knows the opponent.
    resp = client.post("/api/analyze/optimal-xi", json={
        "team": "Spain", "formation": "4-3-3",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["opponent_team"] == ""
    assert len(body["candidates"][0]["lineup"]) == 11


def test_api_formations():
    resp = client.get("/api/formations")
    assert resp.status_code == 200
    formations = resp.json()
    assert set(formations) == {"4-3-3", "4-2-3-1", "4-4-2", "3-5-2"}
    for slots in formations.values():
        assert len(slots) == 11
        for s in slots:
            assert 0.0 <= s["x"] <= 1.0 and 0.0 <= s["y"] <= 1.0
            assert s["position"] in POSITIONS
