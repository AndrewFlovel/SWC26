"""FastAPI application exposing the WC2026 prediction engine.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .engine import (
    EloPoissonModel,
    KnockoutSimulator,
    MatchContext,
    MatchPredictor,
    MonteCarloSimulator,
    ParameterOverrides,
    TournamentSimulator,
    analyze_lineups,
    build_lineup,
    optimal_xi,
    seed_r32,
)
from .engine.bracket import load_bracket
from .engine.player_models import FORMATIONS
from .engine.loader import GROUPS, get_fixtures, load_teams
from .schemas import (
    AdjustedTeamOut,
    BracketProjectionResponse,
    FixtureOut,
    GroupOut,
    FormationSlotOut,
    GroupSimRequest,
    GroupSimResponse,
    KnockoutSimRequest,
    KnockoutSimResponse,
    LineupAnalysisRequest,
    LineupAnalysisResponse,
    OptimalXiRequest,
    OptimalXiResponse,
    PlayerScrapeRequest,
    PlayerSquadResponse,
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
from .services import fbref_index, player_scraper, scraper
from .services.metrics import get_adjusted_draw, get_adjusted_teams, metrics_report
from .services.player_store import get_squad, player_store, squad_index, team_slug
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


def _all_groups_fixed_results() -> dict:
    """group -> {(home, away): (gh, ga)} for every group with recorded finals."""
    out = {}
    for g in GROUPS:
        fixed = _group_fixed_results(g)
        if fixed:
            out[g] = fixed
    return out


@app.post("/api/simulate/knockout", response_model=KnockoutSimResponse)
def simulate_knockout(req: KnockoutSimRequest) -> dict:
    """Title-odds Monte Carlo: plays the full bracket each run and reports every
    team's probability of reaching R16/QF/SF/the final and winning the cup."""
    fixed = _all_groups_fixed_results() if req.use_results else None
    sim = KnockoutSimulator(_model, get_adjusted_draw(), seed=2026)
    return {"n_sims": req.n_sims, "table": sim.simulate(n_sims=req.n_sims, fixed_results=fixed)}


@app.get("/api/bracket/projection", response_model=BracketProjectionResponse)
def bracket_projection(use_results: bool = True) -> dict:
    """The single most-likely bracket: project each group's standings, seed the
    official R32 slots, then resolve every tie by the higher predicted win
    probability. Each tie is fully predictable on demand via /api/predict."""
    draw = get_adjusted_draw()
    teams = get_adjusted_teams()
    sim = MonteCarloSimulator(_model, seed=2026)
    fixed_all = _all_groups_fixed_results() if use_results else {}

    group_order: dict[str, list[str]] = {}
    thirds: list[tuple] = []  # (avg_points, group, third_name)
    for g in GROUPS:
        rows = sim.simulate_group(
            draw[g], n_sims=3000, fixed_results=fixed_all.get(g) or None
        )
        ordered = sorted(
            rows, key=lambda r: (r["avg_points"], r["win_group_pct"]), reverse=True
        )
        group_order[g] = [r["team"] for r in ordered]
        thirds.append((ordered[2]["avg_points"], g, ordered[2]["team"]))
    thirds.sort(reverse=True)
    qualified = [g for _, g, _ in thirds[:8]]

    seeded = seed_r32(group_order, qualified)
    winners: dict[int, str] = {}
    losers: dict[int, str] = {}
    ties: list[dict] = []

    def resolve(match: int, rnd: str, home: str, away: str) -> None:
        pred = _predictor.predict(teams[home], teams[away])
        winner = home if pred.p_home >= pred.p_away else away
        winners[match] = winner
        losers[match] = away if winner == home else home
        ties.append({
            "match": match, "round": rnd, "home": home, "away": away,
            "p_home": pred.p_home, "p_away": pred.p_away, "winner": winner,
        })

    for match in sorted(seeded):
        home, away = seeded[match]
        resolve(match, "R32", home, away)

    def ref(token: str) -> str:
        return (winners if token[0] == "W" else losers)[int(token[1:])]

    for tie in load_bracket()["tree"]:
        resolve(tie["match"], tie["round"], ref(tie["home"]), ref(tie["away"]))

    ties.sort(key=lambda t: t["match"])
    return {"use_results": use_results, "ties": ties}


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


# --------------------------------------------------------------------------- #
# Per-game player analyzer
# --------------------------------------------------------------------------- #

def _team_squad_payload(team: str, source: str) -> dict:
    slug = team_slug(team)
    squad = get_squad(slug) or []
    return {
        "team": team,
        "slug": slug,
        "source": source if squad else "unavailable",
        "players": [asdict(p) for p in squad],
    }


def _resolve_lineup(team: str, names: list[str], formation: str):
    """Map 11 player names + a formation to a built lineup; HTTP errors on miss."""
    squad = get_squad(team_slug(team))
    if squad is None:
        raise HTTPException(
            status_code=404, detail=f"No squad data for '{team}'."
        )
    by_name = {p.name: p for p in squad}
    try:
        players = [by_name[n] for n in names]
    except KeyError as exc:
        raise HTTPException(
            status_code=422, detail=f"Player {exc} not in {team} squad."
        )
    try:
        return build_lineup(formation, players)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/scrape/players", response_model=PlayerSquadResponse)
def scrape_players(req: PlayerScrapeRequest) -> dict:
    fixture = _fixtures_by_id().get(req.fixture_id)
    if fixture is None:
        raise HTTPException(
            status_code=404, detail=f"Fixture '{req.fixture_id}' not found."
        )
    messages: list[str] = []
    sources: dict[str, str] = {}
    for side in ("home", "away"):
        team = fixture[side]
        if req.live:
            _, source, msgs = player_scraper.scrape_squad(team)
            messages.extend(msgs)
        else:
            doc = player_store.get_doc(team_slug(team))
            source = doc.get("source", "seed") if doc else "unavailable"
        sources[side] = source
    return {
        "fixture_id": req.fixture_id,
        "home": _team_squad_payload(fixture["home"], sources["home"]),
        "away": _team_squad_payload(fixture["away"], sources["away"]),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "messages": messages,
    }


@app.get("/api/players")
def list_player_squads() -> dict:
    """Squad coverage across the 48 teams: slug -> player count and source."""
    teams = [
        {
            "slug": slug,
            "team": (doc := player_store.get_doc(slug)) and doc.get("team", slug) or slug,
            "players": count,
            "source": doc.get("source", "seed") if doc else "seed",
        }
        for slug, count in squad_index().items()
    ]
    return {"count": len(teams), "teams": teams}


@app.post("/api/scrape/discover")
def scrape_discover() -> dict:
    """Refresh the FBref squad-url map from the competition index. Never raises."""
    mapping = fbref_index.discover_squad_urls()
    return {
        "resolved": len(mapping),
        "teams": sorted(mapping.keys()),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/players/{slug}")
def get_team_players(slug: str) -> dict:
    squad = get_squad(slug)
    if squad is None:
        raise HTTPException(
            status_code=404, detail=f"No squad data for slug '{slug}'."
        )
    doc = player_store.get_doc(slug)
    return _team_squad_payload(doc["team"] if doc else slug,
                               doc.get("source", "seed") if doc else "seed")


@app.post("/api/analyze/lineup", response_model=LineupAnalysisResponse)
def analyze_lineup(req: LineupAnalysisRequest) -> dict:
    home = _resolve_lineup(req.home_team, req.home_lineup, req.home_formation)
    away = _resolve_lineup(req.away_team, req.away_lineup, req.away_formation)
    return analyze_lineups(home, away)


@app.post("/api/analyze/optimal-xi", response_model=OptimalXiResponse)
def analyze_optimal_xi(req: OptimalXiRequest) -> dict:
    squad = get_squad(team_slug(req.team))
    if squad is None:
        raise HTTPException(
            status_code=404, detail=f"No squad data for '{req.team}'."
        )
    if req.opponent_lineup and req.opponent_team and req.opponent_formation:
        opponent = _resolve_lineup(
            req.opponent_team, req.opponent_lineup, req.opponent_formation
        )
    else:
        opponent = []  # neutral opponent -> best XI in a vacuum (FSI ~ 0.5)
    try:
        candidates = optimal_xi(squad, req.formation, opponent, top_n=req.top_n)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "team": req.team,
        "opponent_team": req.opponent_team or "",
        "candidates": candidates,
    }


@app.get("/api/formations", response_model=dict[str, list[FormationSlotOut]])
def list_formations() -> dict:
    """Slot templates (label, position, unit-pitch x/y) for every supported
    formation — the single source of truth shared with the SVG pitch UI."""
    return {
        name: [
            {"slot": s.label, "position": s.position, "x": s.x, "y": s.y}
            for s in slots
        ]
        for name, slots in FORMATIONS.items()
    }
