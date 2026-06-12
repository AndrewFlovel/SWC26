"""Tests for the results store, metric adjustment replay, scraper
degradation and the results/metrics API endpoints."""

import json

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.engine.adjuster import (
    AdjustmentConfig,
    apply_results,
    elo_delta,
    update_form,
)
from app.engine.loader import get_fixtures, load_teams
from app.main import app
from app.services import scraper
from app.services.results_store import ResultsStore, results_store

client = TestClient(app)

CFG = AdjustmentConfig()


@pytest.fixture(autouse=True)
def isolated_store(tmp_path):
    """Point the singleton store at a temp file and reset it afterwards."""
    original_path, original_records = results_store.path, results_store._records
    results_store.path = tmp_path / "results.json"
    results_store._records = {}
    results_store._version += 1  # invalidate cached adjusted metrics
    yield results_store
    results_store.path = original_path
    results_store._records = original_records
    results_store._version += 1


# ---------------------------------------------------------------- fixtures

def test_official_schedule_dates():
    """Fixtures carry per-match official dates (June 11-27), not a single
    date per matchday."""
    fixtures = get_fixtures()
    dates = {f["date"] for f in fixtures}
    assert min(dates) == "2026-06-11"
    assert max(dates) == "2026-06-27"
    assert len(dates) > 3  # the old generator collapsed everything to 3 dates
    opener = next(f for f in fixtures if f["id"] == "A1")
    assert (opener["home"], opener["away"]) == ("Mexico", "South Africa")
    assert opener["date"] == "2026-06-11"
    assert opener["venue"]["id"] == "mexico_city"


# ---------------------------------------------------------------- adjuster

def test_elo_delta_exact():
    # Equal Elos, home wins 2-0: 40 * 1.5 * (1 - 0.5) = 30.
    assert elo_delta(1800, 1800, 2, 0, cfg=CFG) == pytest.approx(30.0)


def test_elo_delta_host_bonus_shifts_expectation():
    neutral = elo_delta(1800, 1800, 1, 0, cfg=CFG)
    as_host = elo_delta(1800, 1800, 1, 0, home_adv_elo=65.0, cfg=CFG)
    assert as_host < neutral  # the host was expected to win more often


def test_update_form_ema_and_clamp():
    assert update_form(0.5, 1.0, CFG) == pytest.approx(0.65)
    assert update_form(0.0, 0.0, CFG) == 0.0
    assert 0.0 <= update_form(1.0, 1.0, CFG) <= 1.0


def test_apply_results_deterministic_and_zero_sum():
    base = load_teams()
    fixtures = get_fixtures()
    results = {"A1": {"goals_home": 2, "goals_away": 1, "status": "final"}}
    once = apply_results(base, fixtures, results, CFG)
    twice = apply_results(base, fixtures, results, CFG)
    fixture = next(f for f in fixtures if f["id"] == "A1")
    home, away = fixture["home"], fixture["away"]
    assert once[home].elo == twice[home].elo
    gained = once[home].elo - base[home].elo
    lost = once[away].elo - base[away].elo
    assert gained == pytest.approx(-lost)
    assert gained > 0
    # Untouched metrics stay untouched.
    assert once[home].xg_avg == base[home].xg_avg
    assert once["Spain"].elo == base["Spain"].elo


def test_apply_results_ignores_live():
    base = load_teams()
    results = {"A1": {"goals_home": 2, "goals_away": 1, "status": "live"}}
    adjusted = apply_results(base, get_fixtures(), results, CFG)
    assert all(adjusted[n].elo == base[n].elo for n in base)


def test_apply_results_sequential_elo():
    """The replay uses the running Elo: the same matchday-2 win is worth
    less when a matchday-1 win already raised the team's rating."""
    base = load_teams()
    fixtures = get_fixtures()
    a_fixtures = sorted(
        (f for f in fixtures if f["group"] == "A"),
        key=lambda f: (f["matchday"], f["id"]),
    )
    team = a_fixtures[0]["home"]

    def win_for(f):
        if f["home"] == team:
            return {"goals_home": 1, "goals_away": 0, "status": "final"}
        return {"goals_home": 0, "goals_away": 1, "status": "final"}

    md1 = a_fixtures[0]
    md2 = next(
        f for f in a_fixtures
        if f["matchday"] == 2 and team in (f["home"], f["away"])
    )
    md1_only = apply_results(base, fixtures, {md1["id"]: win_for(md1)}, CFG)
    md2_only = apply_results(base, fixtures, {md2["id"]: win_for(md2)}, CFG)
    both = apply_results(
        base, fixtures,
        {md1["id"]: win_for(md1), md2["id"]: win_for(md2)}, CFG,
    )
    gain_md2_alone = md2_only[team].elo - base[team].elo
    gain_md2_after_md1 = both[team].elo - md1_only[team].elo
    assert gain_md2_alone > 0
    assert gain_md2_after_md1 < gain_md2_alone


# ------------------------------------------------------------------ store

def test_store_roundtrip_and_version(tmp_path):
    store = ResultsStore(tmp_path / "r.json")
    v0 = store.version
    store.upsert("A1", 2, 1, status="final", source="manual")
    assert store.version == v0 + 1
    assert store.get("A1")["goals_home"] == 2
    on_disk = json.loads((tmp_path / "r.json").read_text())
    assert on_disk["A1"]["status"] == "final"
    reloaded = ResultsStore(tmp_path / "r.json")
    assert reloaded.get("A1")["goals_away"] == 1
    store.delete("A1")
    assert store.get("A1") is None
    assert store.version == v0 + 2


def test_store_rejects_invalid():
    store = ResultsStore(path=results_store.path)
    with pytest.raises(ValueError):
        store.upsert("A1", 1, 0, status="postponed")
    with pytest.raises(ValueError):
        store.upsert("A1", -1, 0)


# -------------------------------------------------------------------- API

def test_results_crud_roundtrip():
    resp = client.get("/api/results")
    assert resp.status_code == 200
    assert len(resp.json()) == 72
    assert all(r["status"] == "scheduled" for r in resp.json())

    put = client.put(
        "/api/results/A1",
        json={"goals_home": 2, "goals_away": 1, "status": "final"},
    )
    assert put.status_code == 200
    assert put.json()["source"] == "manual"

    rows = {r["fixture_id"]: r for r in client.get("/api/results").json()}
    assert rows["A1"]["goals_home"] == 2
    assert rows["A1"]["status"] == "final"

    assert client.delete("/api/results/A1").status_code == 200
    rows = {r["fixture_id"]: r for r in client.get("/api/results").json()}
    assert rows["A1"]["status"] == "scheduled"


def test_results_unknown_fixture_404():
    resp = client.put(
        "/api/results/Z9", json={"goals_home": 1, "goals_away": 0}
    )
    assert resp.status_code == 404
    assert client.delete("/api/results/Z9").status_code == 404


def test_adjusted_metrics_reflect_result():
    fixture = next(f for f in get_fixtures() if f["id"] == "A1")
    client.put(
        "/api/results/A1",
        json={"goals_home": 3, "goals_away": 0, "status": "final"},
    )
    rows = {r["team"]: r for r in client.get("/api/metrics/adjusted").json()}
    assert rows[fixture["home"]]["elo_delta"] > 0
    assert rows[fixture["home"]]["matches_played"] == 1
    assert rows[fixture["away"]]["elo_delta"] < 0
    assert rows["Spain"]["elo_delta"] == 0


def test_prediction_uses_adjusted_elo():
    fixture = next(f for f in get_fixtures() if f["id"] == "A1")
    body = {"home": fixture["home"], "away": fixture["away"]}
    base = client.post("/api/predict", json=body).json()
    client.put(
        "/api/results/A1",
        json={"goals_home": 4, "goals_away": 0, "status": "final"},
    )
    boosted = client.post("/api/predict", json=body).json()
    assert boosted["p_home"] > base["p_home"]


def test_group_sim_conditioned_on_results():
    fixture = next(f for f in get_fixtures() if f["group"] == "A")
    weak_side = fixture["away"]
    for f in get_fixtures():
        if f["group"] != "A" or f["matchday"] > 2:
            continue
        if f["home"] == weak_side:
            client.put(f"/api/results/{f['id']}",
                       json={"goals_home": 2, "goals_away": 0, "status": "final"})
        elif f["away"] == weak_side:
            client.put(f"/api/results/{f['id']}",
                       json={"goals_home": 0, "goals_away": 2, "status": "final"})

    conditioned = client.post(
        "/api/simulate/group",
        json={"group": "A", "n_sims": 1500, "use_results": True},
    ).json()
    unconditioned = client.post(
        "/api/simulate/group",
        json={"group": "A", "n_sims": 1500, "use_results": False},
    ).json()
    assert conditioned["played"] == 2
    assert unconditioned["played"] == 0
    top2 = {r["team"]: r["top2_pct"] for r in conditioned["table"]}
    top2_base = {r["team"]: r["top2_pct"] for r in unconditioned["table"]}
    assert top2[weak_side] > top2_base[weak_side]


# ---------------------------------------------------------------- scraper

def test_scrape_endpoint_degrades_gracefully(monkeypatch):
    def boom(*args, **kwargs):
        raise scraper.requests.ConnectionError("offline")

    monkeypatch.setattr(scraper.requests, "get", boom)
    resp = client.post("/api/scrape/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["elo_updates"] == []
    assert "offline" in body["messages"][0]


def test_scraper_parses_canned_html(monkeypatch):
    html = """
    <table>
      <tr><td>Spain</td><td>2155</td></tr>
      <tr><td>Czech Republic</td><td>1,810</td></tr>
      <tr><td>Narnia</td><td>1500</td></tr>
      <tr><td>not-a-rating</td><td>abc</td></tr>
    </table>
    """

    class FakeResp:
        text = html
        def raise_for_status(self): pass

    monkeypatch.setattr(scraper.requests, "get", lambda *a, **k: FakeResp())
    live = scraper.fetch_live_elo()
    assert live["Spain"] == 2155.0
    assert live["Czechia"] == 1810.0  # alias applied, comma stripped
    assert "not-a-rating" not in live

    report = scraper.refresh_today()
    assert report["status"] == "ok"
    teams_reported = {u["team"] for u in report["elo_updates"]}
    assert teams_reported == {"Spain", "Czechia"}  # Narnia dropped
    assert any("Narnia" in m for m in report["messages"])


def test_scraper_parses_results_rows():
    html = """
    <table>
      <tr><td>Mexico</td><td>2-1</td><td>South Korea</td></tr>
      <tr><td>Header</td><td>junk</td><td>row</td></tr>
    </table>
    """
    rows = scraper.parse_results_rows(BeautifulSoup(html, "html.parser"))
    assert rows == [("Mexico", "South Korea", 2, 1)]


def test_scraped_result_does_not_overwrite_manual(monkeypatch):
    client.put("/api/results/A1",
               json={"goals_home": 1, "goals_away": 1, "status": "final"})
    fixture = next(f for f in get_fixtures() if f["id"] == "A1")
    messages = []
    stored = scraper._store_scraped_results(
        [(fixture["home"], fixture["away"], 5, 0)], messages
    )
    assert stored == 0
    assert results_store.get("A1")["goals_home"] == 1
    assert results_store.get("A1")["source"] == "manual"
