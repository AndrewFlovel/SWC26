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
from .engine.loader import GROUPS, get_draw, get_fixtures, load_teams
from .schemas import (
    FixtureOut,
    GroupOut,
    GroupSimRequest,
    GroupSimResponse,
    PredictRequest,
    PredictResponse,
    ScorelineOut,
    TeamOut,
    TournamentSimRequest,
    TournamentSimResponse,
)

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
    teams = load_teams()
    if name not in teams:
        raise HTTPException(status_code=404, detail=f"Team '{name}' not found.")
    return teams[name]


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "teams": len(load_teams())}


@app.get("/api/teams", response_model=list[TeamOut])
def list_teams() -> list[dict]:
    return [asdict(t) for t in load_teams().values()]


@app.get("/api/groups", response_model=list[GroupOut])
def list_groups() -> list[dict]:
    draw = get_draw()
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


@app.post("/api/simulate/group", response_model=GroupSimResponse)
def simulate_group(req: GroupSimRequest) -> dict:
    draw = get_draw()
    sim = MonteCarloSimulator(_model, seed=2026)
    table = sim.simulate_group(draw[req.group], n_sims=req.n_sims)
    return {"group": req.group, "n_sims": req.n_sims, "table": table}


@app.post("/api/simulate/tournament", response_model=TournamentSimResponse)
def simulate_tournament(req: TournamentSimRequest) -> dict:
    sim = TournamentSimulator(_model, get_draw(), seed=2026)
    return {"n_sims": req.n_sims, "table": sim.simulate(n_sims=req.n_sims)}
