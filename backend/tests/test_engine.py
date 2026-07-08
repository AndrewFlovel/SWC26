"""Sanity tests for the WC2026 prediction engine and API."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.engine import (
    EloPoissonModel,
    MatchContext,
    MatchPredictor,
    ModelConfig,
    ParameterOverrides,
)
from app.engine.loader import get_draw, get_fixtures, load_teams
from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def teams():
    return load_teams()


@pytest.fixture(scope="module")
def predictor():
    return MatchPredictor(EloPoissonModel())


def test_dataset_integrity(teams):
    assert len(teams) == 48
    draw = get_draw()
    assert len(draw) == 12
    assert all(len(g) == 4 for g in draw.values())
    assert len(get_fixtures()) == 72


def test_matrix_normalization(teams, predictor):
    pred = predictor.predict(teams["Spain"], teams["Brazil"])
    assert pred.matrix.sum() == pytest.approx(1.0, abs=1e-9)
    assert pred.p_home + pred.p_draw + pred.p_away == pytest.approx(1.0, abs=1e-3)


def test_favorite_direction(teams, predictor):
    """Spain (Elo 2150, xG 2.45) must be favored over Iraq (1700, xG 0.70)."""
    pred = predictor.predict(teams["Spain"], teams["Iraq"])
    assert pred.p_home > 0.6
    assert pred.p_home > pred.p_away


def test_injury_override_reduces_win_probability(teams, predictor):
    base = predictor.predict(teams["France"], teams["Senegal"])
    crippled = predictor.predict(
        teams["France"], teams["Senegal"],
        overrides=ParameterOverrides(home_injury=1.0),
    )
    assert crippled.p_home < base.p_home


def test_form_override_boosts_attack(teams):
    model = EloPoissonModel()
    cold = model.score_matrix(
        teams["England"], teams["Ghana"],
        overrides=ParameterOverrides(home_form=0.0),
    )[1]
    hot = model.score_matrix(
        teams["England"], teams["Ghana"],
        overrides=ParameterOverrides(home_form=1.0),
    )[1]
    assert hot > cold


def test_altitude_penalizes_unadapted_only(teams):
    model = EloPoissonModel()
    ctx = MatchContext(altitude_m=2240)
    # Mexico is altitude_adapted; Germany is not.
    _, lam_mex, lam_ger = model.score_matrix(teams["Mexico"], teams["Germany"], ctx)
    _, lam_mex0, lam_ger0 = model.score_matrix(teams["Mexico"], teams["Germany"])
    assert lam_mex == pytest.approx(lam_mex0)
    assert lam_ger < lam_ger0


def test_extreme_parameters_stay_finite(teams):
    """Zero-division / degenerate-distribution guard."""
    model = EloPoissonModel()
    matrix, lam_h, lam_a = model.score_matrix(
        teams["Iraq"], teams["Spain"],
        MatchContext(altitude_m=4000, heat_index=2.0),
        ParameterOverrides(home_form=0.0, home_injury=1.0,
                           away_form=0.0, away_injury=1.0),
    )
    assert np.isfinite(matrix).all()
    assert matrix.sum() == pytest.approx(1.0, abs=1e-9)
    assert lam_h >= ModelConfig().min_lambda


def test_api_predict_endpoint():
    resp = client.post("/api/predict", json={"home": "Spain", "away": "Brazil"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["p_home"] + body["p_draw"] + body["p_away"] == pytest.approx(1.0, abs=1e-2)
    assert len(body["matrix"]) == body["matrix_size"]


def test_api_predict_unknown_team():
    resp = client.post("/api/predict", json={"home": "Wakanda", "away": "Spain"})
    assert resp.status_code == 404


def test_api_predict_invalid_params():
    resp = client.post("/api/predict", json={
        "home": "Spain", "away": "Brazil", "home_injury": 2.5,
    })
    assert resp.status_code == 422


def test_api_matches_have_venues():
    resp = client.get("/api/matches")
    assert resp.status_code == 200
    matches = resp.json()
    assert len(matches) == 72
    azteca = [m for m in matches if m["venue"]["id"] == "mexico_city"]
    assert all(m["venue"]["altitude_m"] == 2240 for m in azteca)
