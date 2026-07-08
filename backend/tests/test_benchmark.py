"""Tests for the predicted-vs-real performance benchmark."""

import pytest

from app.engine.loader import get_fixtures
from app.services.benchmark import build_benchmark
from app.services.knockout_store import knockout_store
from app.services.results_store import results_store


@pytest.fixture(autouse=True)
def iso_stores(tmp_path):
    """Isolate both persisted stores so each test starts from empty."""
    rs, ks = results_store, knockout_store
    saved = (rs.path, rs._records, ks.path, ks._records)
    rs.path = tmp_path / "results.json"
    rs._records = {}
    ks.path = tmp_path / "knockout_results.json"
    ks._records = {}
    yield
    rs.path, rs._records, ks.path, ks._records = saved


def test_benchmark_empty_when_nothing_final():
    data = build_benchmark()
    assert data["summary"]["matches"] == 0
    assert data["matches"] == []
    assert data["by_round"] == []
    assert data["by_team"] == []


def test_benchmark_group_match_scoring():
    f = next(fx for fx in get_fixtures() if fx["group"] == "A" and fx["matchday"] == 1)
    results_store.upsert(f["id"], 2, 0, status="final", source="manual")

    data = build_benchmark()
    assert data["summary"]["matches"] == 1
    m = data["matches"][0]
    assert m["stage"] == "Group"
    assert m["key"] == f["id"]
    assert m["actual"] == "home"  # 2-0

    probs = {"home": m["p_home"], "draw": m["p_draw"], "away": m["p_away"]}
    assert m["predicted"] == max(probs, key=probs.get)
    assert m["correct_winner"] == (m["predicted"] == "home")

    # Brier is the three-way sum of squared errors against the one-hot outcome.
    exp_brier = sum((probs[o] - (1.0 if o == "home" else 0.0)) ** 2 for o in probs)
    assert m["brier"] == pytest.approx(round(exp_brier, 4), abs=1e-4)
    assert m["log_loss"] >= 0.0
    assert 0.0 <= m["p_actual_score"] <= 1.0

    assert any(r["label"] == "Group" for r in data["by_round"])
    team_labels = {r["label"] for r in data["by_team"]}
    assert f["home"] in team_labels and f["away"] in team_labels


def test_benchmark_knockout_scored_two_way():
    knockout_store.upsert(73, "Spain", "Iraq", 3, 0, status="final", source="scraped")

    data = build_benchmark()
    m = next(x for x in data["matches"] if x["key"] == "73")
    assert m["stage"] == "R32"
    assert m["actual"] == "home"
    # Two-way scoring drops the draw, so Brier is bounded by 2.
    assert 0.0 <= m["brier"] <= 2.0
    # Spain is a heavy favourite over Iraq and won, so the model is correct.
    assert m["correct_winner"] is True
    assert any(r["label"] == "R32" for r in data["by_round"])


def test_benchmark_aggregates_group_and_knockout():
    f = next(fx for fx in get_fixtures() if fx["group"] == "B" and fx["matchday"] == 1)
    results_store.upsert(f["id"], 1, 1, status="final", source="manual")
    knockout_store.upsert(89, "Spain", "Iraq", 2, 1, pens_home=None, pens_away=None,
                          status="final", source="scraped")

    data = build_benchmark()
    assert data["summary"]["matches"] == 2
    stages = {r["label"] for r in data["by_round"]}
    assert {"Group", "R16"} <= stages
    # Every per-team aggregate stays within valid percentage/score ranges.
    for r in data["by_team"]:
        assert 0.0 <= r["correct_winner_pct"] <= 100.0
        assert 0.0 <= r["exact_score_pct"] <= 100.0
        assert r["matches"] >= 1
