"""Tests for the manual per-team availability adjustments: the store, the
/api/adjustments endpoints, their effect on predictions and the a-priori
guarantee of the benchmark."""

import pytest
from fastapi.testclient import TestClient

from app.engine.loader import load_teams
from app.main import app
from app.services import fatigue, metrics, standings
from app.services.knockout_store import knockout_store
from app.services.results_store import results_store
from app.services.team_adjust_store import TeamAdjustStore, team_adjust_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path):
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


# ---------------------------------------------------------------- store

def test_store_crud_persists_and_bumps_version(tmp_path):
    store = TeamAdjustStore(path=tmp_path / "adj.json")
    v0 = store.version
    rec = store.upsert("France", 0.15, note="Two starters suspended")
    assert store.version == v0 + 1
    assert rec["injury_delta"] == 0.15 and rec["note"] == "Two starters suspended"
    # reload from disk
    again = TeamAdjustStore(path=tmp_path / "adj.json")
    assert again.get("France")["injury_delta"] == 0.15
    store.delete("France")
    assert store.get("France") is None
    assert store.version == v0 + 2


def test_store_validation_errors(tmp_path):
    store = TeamAdjustStore(path=tmp_path / "adj.json")
    with pytest.raises(ValueError):
        store.upsert("France", 1.5)
    with pytest.raises(ValueError):
        store.upsert("France", -1.5)
    with pytest.raises(ValueError):
        store.upsert("France", 0.1, note="x" * 281)
    with pytest.raises(ValueError):
        store.upsert("", 0.1)


# ---------------------------------------------------------------- endpoints

def test_put_adjustment_returns_effective_injury():
    base = load_teams()["France"].injury_impact
    resp = client.put(
        "/api/adjustments/France",
        json={"injury_delta": 0.2, "note": "test suspension"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["team"] == "France"
    assert body["base_injury"] == pytest.approx(base)
    assert body["effective_injury"] == pytest.approx(min(base + 0.2, 1.0))


def test_put_adjustment_unknown_team_404_and_out_of_range_422():
    assert client.put(
        "/api/adjustments/Narnia", json={"injury_delta": 0.2}
    ).status_code == 404
    assert client.put(
        "/api/adjustments/France", json={"injury_delta": 1.5}
    ).status_code == 422
    assert client.put(
        "/api/adjustments/France", json={"injury_delta": 0.1, "note": "x" * 300}
    ).status_code == 422


def test_list_adjustments_sorted_and_delete():
    client.put("/api/adjustments/Spain", json={"injury_delta": 0.1})
    client.put("/api/adjustments/France", json={"injury_delta": -0.05})
    listed = client.get("/api/adjustments").json()
    assert [a["team"] for a in listed] == ["France", "Spain"]
    assert client.delete("/api/adjustments/Spain").status_code == 200
    assert [a["team"] for a in client.get("/api/adjustments").json()] == ["France"]
    assert client.delete("/api/adjustments/Narnia").status_code == 404


# ---------------------------------------------------------------- predictions

def test_adjustment_feeds_predictions_and_delete_restores():
    body = {"home": "France", "away": "Morocco"}
    p0 = client.post("/api/predict", json=body).json()["p_home"]
    client.put("/api/adjustments/France", json={"injury_delta": 0.4})
    p1 = client.post("/api/predict", json=body).json()["p_home"]
    assert p1 < p0  # more injuries -> weaker France
    client.delete("/api/adjustments/France")
    p2 = client.post("/api/predict", json=body).json()["p_home"]
    assert p2 == pytest.approx(p0)  # cache invalidated both ways


def test_adjustment_visible_in_teams_endpoint():
    base = load_teams()["France"].injury_impact
    client.put("/api/adjustments/France", json={"injury_delta": 0.3})
    teams = {t["name"]: t for t in client.get("/api/teams").json()}
    assert teams["France"]["injury_impact"] == pytest.approx(
        min(base + 0.3, 1.0)
    )


def test_benchmark_ignores_adjustments():
    """The benchmark must stay a-priori: manual availability deltas never
    change the scored predictions."""
    fixture = client.get("/api/matches").json()[0]
    client.put(f"/api/results/{fixture['id']}", json={"goals_home": 2, "goals_away": 0})
    before = client.get("/api/metrics/benchmark").json()
    client.put(f"/api/adjustments/{fixture['home']}", json={"injury_delta": 0.9})
    after = client.get("/api/metrics/benchmark").json()
    assert before == after
