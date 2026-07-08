"""Predicted-vs-real performance benchmark.

Scores the model's *a-priori* predictions — computed from the base team profiles
(``load_teams()``), with no result feedback, so every prediction is the model's
pre-tournament view and is fully reproducible — against the real results that
have been recorded/scraped. Covers the group stage (results store) and the
knockout stage (knockout store).

Per match we report: correct-winner, Brier score, log-loss and exact-score hit.
Group matches are scored three-way (home/draw/away); knockout matches have no
draw (penalties decide), so they are scored two-way on the win probabilities
renormalized over ``p_home + p_away``. Aggregates are the mean of the per-match
values, globally and broken down per round and per team.
"""

from __future__ import annotations

import math
from typing import Dict, Iterator, List, Optional

from ..engine.core import MatchContext
from ..engine.loader import get_fixtures, load_teams
from ..engine.predictor import EloPoissonModel, MatchPredictor
from .knockout_store import knockout_store, winner_of
from .results_store import results_store

_EPS = 1e-12
_model = EloPoissonModel()
_predictor = MatchPredictor(_model)

# Knockout match number -> stage label.
_KO_STAGE: Dict[int, str] = {
    **{m: "R32" for m in range(73, 89)},
    **{m: "R16" for m in range(89, 97)},
    **{m: "QF" for m in range(97, 101)},
    **{m: "SF" for m in range(101, 103)},
    103: "3P",
    104: "F",
}

_STAGE_ORDER = ["Group", "R32", "R16", "QF", "SF", "3P", "F"]


def _p_actual_score(matrix, gh: int, ga: int) -> float:
    n = matrix.shape[0]
    return float(matrix[gh, ga]) if gh < n and ga < n else 0.0


def _log_loss(p: float) -> float:
    return -math.log(min(max(p, _EPS), 1.0))


def _score_group(teams) -> Iterator[dict]:
    stored = results_store.all()
    for f in get_fixtures():
        rec = stored.get(f["id"])
        if not rec or rec["status"] != "final":
            continue
        home, away = f["home"], f["away"]
        if home not in teams or away not in teams:
            continue
        gh, ga = rec["goals_home"], rec["goals_away"]
        venue = f["venue"]
        ctx = MatchContext(
            altitude_m=venue["altitude_m"],
            heat_index=venue["heat_index"],
            home_team=f["home_team_host"],
        )
        pred = _predictor.predict(teams[home], teams[away], ctx)
        probs = {"home": pred.p_home, "draw": pred.p_draw, "away": pred.p_away}
        actual = "home" if gh > ga else ("away" if ga > gh else "draw")
        predicted = max(probs, key=probs.get)
        brier = sum((probs[o] - (1.0 if o == actual else 0.0)) ** 2 for o in probs)
        pred_score = pred.top_scorelines[0][0]
        yield {
            "key": f["id"], "stage": "Group", "home": home, "away": away,
            "goals_home": gh, "goals_away": ga, "actual": actual,
            "p_home": pred.p_home, "p_draw": pred.p_draw, "p_away": pred.p_away,
            "predicted": predicted, "correct_winner": predicted == actual,
            "brier": round(brier, 4), "log_loss": round(_log_loss(probs[actual]), 4),
            "predicted_score": pred_score, "exact_hit": pred_score == f"{gh}-{ga}",
            "p_actual_score": round(_p_actual_score(pred.matrix, gh, ga), 4),
        }


def _score_knockout(teams) -> Iterator[dict]:
    for key, rec in knockout_store.all().items():
        if rec["status"] != "final":
            continue
        winner = winner_of(rec)
        if winner is None:
            continue
        home, away = rec["home"], rec["away"]
        if home not in teams or away not in teams:
            continue
        gh, ga = rec["goals_home"], rec["goals_away"]
        pred = _predictor.predict(teams[home], teams[away])  # neutral venue
        # Two-way: renormalize over a decisive result (no draw in knockout).
        decisive = pred.p_home + pred.p_away
        p_home = pred.p_home / decisive if decisive > 0 else 0.5
        p_away = 1.0 - p_home
        actual = "home" if winner == home else "away"
        probs = {"home": p_home, "away": p_away}
        predicted = "home" if p_home >= p_away else "away"
        brier = sum((probs[o] - (1.0 if o == actual else 0.0)) ** 2 for o in probs)
        pred_score = pred.top_scorelines[0][0]
        yield {
            "key": str(key), "stage": _KO_STAGE.get(int(key), "R32"),
            "home": home, "away": away, "goals_home": gh, "goals_away": ga,
            "actual": actual,
            "p_home": pred.p_home, "p_draw": pred.p_draw, "p_away": pred.p_away,
            "predicted": predicted, "correct_winner": predicted == actual,
            "brier": round(brier, 4), "log_loss": round(_log_loss(probs[actual]), 4),
            "predicted_score": pred_score, "exact_hit": pred_score == f"{gh}-{ga}",
            "p_actual_score": round(_p_actual_score(pred.matrix, gh, ga), 4),
        }


def _aggregate(label: str, rows: List[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"label": label, "matches": 0, "correct_winner_pct": 0.0,
                "brier": 0.0, "log_loss": 0.0, "exact_score_pct": 0.0}
    return {
        "label": label,
        "matches": n,
        "correct_winner_pct": round(100 * sum(r["correct_winner"] for r in rows) / n, 1),
        "brier": round(sum(r["brier"] for r in rows) / n, 4),
        "log_loss": round(sum(r["log_loss"] for r in rows) / n, 4),
        "exact_score_pct": round(100 * sum(r["exact_hit"] for r in rows) / n, 1),
    }


def build_benchmark() -> dict:
    """Score every finished match and aggregate globally, per round and per team."""
    teams = load_teams()
    matches = list(_score_group(teams)) + list(_score_knockout(teams))

    by_round = [
        _aggregate(stage, [m for m in matches if m["stage"] == stage])
        for stage in _STAGE_ORDER
        if any(m["stage"] == stage for m in matches)
    ]

    team_rows: Dict[str, List[dict]] = {}
    for m in matches:
        team_rows.setdefault(m["home"], []).append(m)
        team_rows.setdefault(m["away"], []).append(m)
    by_team = sorted(
        (_aggregate(name, rows) for name, rows in team_rows.items()),
        key=lambda a: (-a["matches"], a["label"]),
    )

    return {
        "summary": _aggregate("overall", matches),
        "by_round": by_round,
        "by_team": by_team,
        "matches": matches,
    }
