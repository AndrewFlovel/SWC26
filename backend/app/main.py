"""FastAPI application exposing the WC2026 prediction engine.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .engine import (
    EloPoissonModel,
    MatchContext,
    MatchPredictor,
    MonteCarloSimulator,
    ParameterOverrides,
    TournamentSimulator,
)
from .engine.loader import GROUPS, get_fixtures, load_teams
from .schemas import (
    AdjustedTeamOut,
    FixtureOut,
    GroupOut,
    GroupSimRequest,
    GroupSimResponse,
    PredictRequest,
    PredictResponse,
    ResultIn,
    ResultOut,
    ScorelineOut,
    ScrapeResponse,
    TeamOut,
    TournamentSimRequest,
    TournamentSimResponse,
)
from .services import scraper
from .services.metrics import get_adjusted_draw, get_adjusted_teams, metrics_report
from .services.results_store import results_store

app = FastAPI(
    title="SWC26 — World Cup 2026 Analytics Engine",
    description="Elo + xG bivariate Poisson (Dixon-Coles) prediction API "
                "with Monte Carlo group and tournament simulation.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_model = EloPoissonModel()
_predictor = MatchPredictor(_model)


def _get_team(name: str):
    teams = get_adjusted_teams()
    if name not in teams:
        raise HTTPException(status_code=404, detail=f"Team '{name}' not found.")
    return teams[name]


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "teams": len(load_teams())}


@app.get("/api/teams", response_model=list[TeamOut])
def list_teams() -> list[dict]:
    return [asdict(t) for t in get_adjusted_teams().values()]


@app.get("/api/groups", response_model=list[GroupOut])
def list_groups() -> list[dict]:
    draw = get_adjusted_draw()
    return [
        {"group": g, "teams": [asdict(t) for t in draw[g]]}
        for g in GROUPS
    ]


@app.get("/api/matches", response_model=list[FixtureOut])
def list_matches() -> list[dict]:
    return get_fixtures()


@app.post("/api/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> dict:
    home = _get_team(req.home)
    away = _get_team(req.away)
    if home.name == away.name:
        raise HTTPException(status_code=422, detail="A team cannot play itself.")

    host = None
    if req.home_advantage == "home":
        host = home.name
    elif req.home_advantage == "away":
        host = away.name

    ctx = MatchContext(
        altitude_m=req.altitude_m, heat_index=req.heat_index, home_team=host
    )
    overrides = ParameterOverrides(
        home_form=req.home_form,
        away_form=req.away_form,
        home_injury=req.home_injury,
        away_injury=req.away_injury,
        xg_blend_weight=req.xg_blend_weight,
        rho=req.rho,
    )
    pred = _predictor.predict(home, away, ctx, overrides)
    return {
        "home": pred.home,
        "away": pred.away,
        "lambda_home": pred.lambda_home,
        "lambda_away": pred.lambda_away,
        "p_home": pred.p_home,
        "p_draw": pred.p_draw,
        "p_away": pred.p_away,
        "top_scorelines": [
            ScorelineOut(score=s, prob=p) for s, p in pred.top_scorelines
        ],
        "matrix": [[round(float(v), 5) for v in row] for row in pred.matrix],
        "matrix_size": pred.matrix.shape[0],
    }


def _group_fixed_results(group: str) -> dict:
    """(home, away) -> (gh, ga) for the group's recorded final results."""
    stored = results_store.all()
    fixed = {}
    for f in get_fixtures():
        record = stored.get(f["id"])
        if f["group"] == group and record and record["status"] == "final":
            fixed[(f["home"], f["away"])] = (
                record["goals_home"], record["goals_away"],
            )
    return fixed


@app.post("/api/simulate/group", response_model=GroupSimResponse)
def simulate_group(req: GroupSimRequest) -> dict:
    draw = get_adjusted_draw()
    fixed = _group_fixed_results(req.group) if req.use_results else {}
    sim = MonteCarloSimulator(_model, seed=2026)
    table = sim.simulate_group(
        draw[req.group], n_sims=req.n_sims, fixed_results=fixed or None
    )
    return {
        "group": req.group,
        "n_sims": req.n_sims,
        "played": len(fixed),
        "table": table,
    }


@app.post("/api/simulate/tournament", response_model=TournamentSimResponse)
def simulate_tournament(req: TournamentSimRequest) -> dict:
    sim = TournamentSimulator(_model, get_adjusted_draw(), seed=2026)
    return {"n_sims": req.n_sims, "table": sim.simulate(n_sims=req.n_sims)}


def _fixtures_by_id() -> dict:
    return {f["id"]: f for f in get_fixtures()}


def _result_out(fixture: dict, record: dict | None) -> dict:
    return {
        "fixture_id": fixture["id"],
        "group": fixture["group"],
        "matchday": fixture["matchday"],
        "date": fixture["date"],
        "home": fixture["home"],
        "away": fixture["away"],
        "goals_home": record["goals_home"] if record else None,
        "goals_away": record["goals_away"] if record else None,
        "status": record["status"] if record else "scheduled",
        "source": record["source"] if record else None,
        "updated_at": record["updated_at"] if record else None,
    }


@app.get("/api/results", response_model=list[ResultOut])
def list_results() -> list[dict]:
    stored = results_store.all()
    return [_result_out(f, stored.get(f["id"])) for f in get_fixtures()]


@app.put("/api/results/{fixture_id}", response_model=ResultOut)
def put_result(fixture_id: str, body: ResultIn) -> dict:
    fixture = _fixtures_by_id().get(fixture_id)
    if fixture is None:
        raise HTTPException(
            status_code=404, detail=f"Fixture '{fixture_id}' not found."
        )
    record = results_store.upsert(
        fixture_id, body.goals_home, body.goals_away,
        status=body.status, source="manual",
    )
    return _result_out(fixture, record)


@app.delete("/api/results/{fixture_id}")
def delete_result(fixture_id: str) -> dict:
    if _fixtures_by_id().get(fixture_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Fixture '{fixture_id}' not found."
        )
    results_store.delete(fixture_id)
    return {"status": "deleted"}


@app.post("/api/scrape/refresh", response_model=ScrapeResponse)
def scrape_refresh() -> dict:
    adjusted = {name: t.elo for name, t in get_adjusted_teams().items()}
    return scraper.refresh_today(adjusted_elo=adjusted)


@app.get("/api/metrics/adjusted", response_model=list[AdjustedTeamOut])
def adjusted_metrics() -> list[dict]:
    return metrics_report()
