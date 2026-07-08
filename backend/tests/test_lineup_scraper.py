"""Tests for the Selenium confirmed-lineup round: name matching, the
never-raises scrape contract, the threaded job lifecycle, and the two new
endpoints. Fully offline and deterministic — selenium/Chrome are never invoked
(the module imports `selenium` lazily, so these pass with it uninstalled); the
browser fetch is either mocked or forced to fail to exercise the fallback."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import lineup_scraper
from app.services.lineup_jobs import lineup_jobs, run_lineup_job

client = TestClient(app)

# H6 is Uruguay (home) vs Spain (away) — both have seed squads in app/data/players.
FIXTURE = "H6"

URUGUAY_433 = [
    "Sergio Rochet", "Mathías Olivera", "Ronald Araújo",
    "José María Giménez", "Nahitan Nández", "Manuel Ugarte",
    "Federico Valverde", "Rodrigo Bentancur", "Facundo Pellistri",
    "Darwin Núñez", "Maximiliano Araújo",
]
SPAIN_433 = [
    "Unai Simón", "Marc Cucurella", "Pau Cubarsí", "Aymeric Laporte",
    "Dani Carvajal", "Rodri", "Pedri", "Fabián Ruiz",
    "Nico Williams", "Álvaro Morata", "Lamine Yamal",
]


@pytest.fixture(autouse=True)
def clear_jobs():
    """Isolate the in-memory job registry between tests."""
    lineup_jobs._jobs.clear()
    yield
    lineup_jobs._jobs.clear()


def _canned(announced=True, home_starters=URUGUAY_433, away_starters=SPAIN_433):
    def fake(fixture_id, home_team, away_team):
        return {
            "announced": announced,
            "home": {"team": home_team, "formation": "4-3-3",
                     "starters": list(home_starters)},
            "away": {"team": away_team, "formation": "4-3-3",
                     "starters": list(away_starters)},
            "messages": ["canned"],
        }
    return fake


def _wait_terminal(fixture_id, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/scrape/players/status/{fixture_id}")
        if resp.status_code == 200 and resp.json()["status"] in ("done", "error"):
            return resp.json()
        time.sleep(0.02)
    return client.get(f"/api/scrape/players/status/{fixture_id}").json()


# --------------------------------------------------------------------------- #
# Name matching
# --------------------------------------------------------------------------- #

def test_match_names_accents_surnames_and_unmatched():
    squad = ["Lamine Yamal", "Álvaro Morata", "Pedri", "Rodri"]
    scraped = ["L. Yamal", "Alvaro Morata", "Pedri", "Unknown Guy"]
    matched, unmatched = lineup_scraper._match_names(scraped, squad)
    assert "Lamine Yamal" in matched      # surname fallback ("L. Yamal")
    assert "Álvaro Morata" in matched      # accent-insensitive
    assert "Pedri" in matched
    assert unmatched == ["Unknown Guy"]


# --------------------------------------------------------------------------- #
# scrape_confirmed never raises
# --------------------------------------------------------------------------- #

def test_scrape_confirmed_unmapped_fixture_is_graceful():
    out = lineup_scraper.scrape_confirmed("ZZ99", "Uruguay", "Spain")
    assert out["announced"] is False
    assert out["home"]["starters"] == []
    assert any("No Sofascore event" in m for m in out["messages"])


def test_scrape_confirmed_graceful_without_chrome(monkeypatch):
    monkeypatch.setitem(lineup_scraper.SOFASCORE_EVENTS, FIXTURE, 999999)

    def boom(*args, **kwargs):
        raise RuntimeError("no chrome here")

    monkeypatch.setattr(lineup_scraper, "_make_driver", boom)
    out = lineup_scraper.scrape_confirmed(FIXTURE, "Uruguay", "Spain")
    assert out["announced"] is False
    assert any("failed" in m for m in out["messages"])


def test_parse_side_filters_substitutes():
    data = {
        "team": "Spain",
        "formation": "4-3-3",
        "players": [
            {"player": {"name": "Unai Simón"}, "substitute": False},
            {"player": {"name": "Benched Guy"}, "substitute": True},
        ],
    }
    side = lineup_scraper._parse_side(data, "Spain")
    assert side["starters"] == ["Unai Simón"]
    assert side["formation"] == "4-3-3"


# --------------------------------------------------------------------------- #
# Worker: confirmed XI resolution
# --------------------------------------------------------------------------- #

def test_worker_resolves_confirmed_xi(monkeypatch):
    monkeypatch.setattr(lineup_scraper, "scrape_confirmed", _canned())
    lineup_jobs.start(FIXTURE)  # endpoint creates the job; worker fills it
    run_lineup_job(FIXTURE, "Uruguay", "Spain")
    job = lineup_jobs.get(FIXTURE)
    assert job.status == "done"
    for side in (job.home, job.away):
        assert side["announced"] is True
        assert len(side["lineup"]) == 11
        assert len(set(side["lineup"])) == 11      # no duplicates
        assert side["unmatched"] == []
    # GK is slotted first (slot order applied for 4-3-3).
    assert job.home["lineup"][0] == "Sergio Rochet"
    assert job.away["lineup"][0] == "Unai Simón"


def test_worker_unmatched_starter_blocks_apply(monkeypatch):
    bad_spain = list(SPAIN_433)
    bad_spain[5] = "Nobody McGhost"  # a confirmed starter we have no stats for
    monkeypatch.setattr(lineup_scraper, "scrape_confirmed",
                        _canned(away_starters=bad_spain))
    lineup_jobs.start(FIXTURE)
    run_lineup_job(FIXTURE, "Uruguay", "Spain")
    job = lineup_jobs.get(FIXTURE)
    assert job.status == "done"
    assert job.away["announced"] is True
    assert job.away["lineup"] == []                 # cannot apply: starter missing
    assert "Nobody McGhost" in job.away["unmatched"]
    assert len(job.home["lineup"]) == 11            # home still fully resolved


def test_worker_unannounced(monkeypatch):
    monkeypatch.setattr(lineup_scraper, "scrape_confirmed", _canned(announced=False))
    lineup_jobs.start(FIXTURE)
    run_lineup_job(FIXTURE, "Uruguay", "Spain")
    job = lineup_jobs.get(FIXTURE)
    assert job.status == "done"
    assert job.home["announced"] is False
    assert job.home["lineup"] == []


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

def test_scrape_lineups_lifecycle(monkeypatch):
    monkeypatch.setattr(lineup_scraper, "scrape_confirmed", _canned())
    resp = client.post("/api/scrape/lineups", json={"fixture_id": FIXTURE})
    assert resp.status_code == 202
    assert resp.json()["status"] in ("pending", "running", "done")

    final = _wait_terminal(FIXTURE)
    assert final["status"] == "done"
    assert final["home"]["announced"] and final["away"]["announced"]
    assert len(final["home"]["lineup"]) == 11
    assert len(final["away"]["lineup"]) == 11

    # The confirmed XIs are in valid slot order -> analyze accepts them.
    analyzed = client.post("/api/analyze/lineup", json={
        "home_team": "Uruguay", "away_team": "Spain",
        "home_formation": final["home"]["formation"],
        "away_formation": final["away"]["formation"],
        "home_lineup": final["home"]["lineup"],
        "away_lineup": final["away"]["lineup"],
    })
    assert analyzed.status_code == 200
    assert 0.0 <= analyzed.json()["fsi"] <= 1.0


def test_scrape_lineups_unknown_fixture():
    resp = client.post("/api/scrape/lineups", json={"fixture_id": "ZZ9"})
    assert resp.status_code == 404


def test_lineup_status_unknown_fixture():
    resp = client.get("/api/scrape/players/status/NOPE")
    assert resp.status_code == 404
