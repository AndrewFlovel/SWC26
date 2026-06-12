"""Pydantic request/response schemas for the WC2026 analytics API."""

from __future__ import annotations

from typing import List, Optional, Tuple

from pydantic import BaseModel, Field


class TeamOut(BaseModel):
    name: str
    group: str
    elo: float
    fifa_ranking: int
    confederation: str
    is_host: bool
    altitude_adapted: bool
    xg_avg: float
    xga_avg: float
    form_index: float
    injury_impact: float


class VenueOut(BaseModel):
    id: str
    stadium: str
    city: str
    country: str
    altitude_m: float
    heat_index: float
    wbgt_score: float
    notes: str


class FixtureOut(BaseModel):
    id: str
    group: str
    matchday: int
    date: str
    home: str
    away: str
    home_team_host: Optional[str] = None
    venue: VenueOut


class GroupOut(BaseModel):
    group: str
    teams: List[TeamOut]


class PredictRequest(BaseModel):
    home: str
    away: str
    home_form: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    away_form: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    home_injury: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    away_injury: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    altitude_m: float = Field(default=0.0, ge=0.0, le=4000.0)
    heat_index: float = Field(default=0.0, ge=0.0, le=2.0)
    home_advantage: Optional[str] = Field(
        default=None, pattern="^(home|away)$",
        description="Which side, if any, receives the host Elo bonus.",
    )
    xg_blend_weight: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rho: Optional[float] = Field(default=None, ge=-0.5, le=0.3)


class ScorelineOut(BaseModel):
    score: str
    prob: float


class PredictResponse(BaseModel):
    home: str
    away: str
    lambda_home: float
    lambda_away: float
    p_home: float
    p_draw: float
    p_away: float
    top_scorelines: List[ScorelineOut]
    matrix: List[List[float]]
    matrix_size: int


class GroupSimRequest(BaseModel):
    group: str = Field(pattern="^[A-L]$")
    n_sims: int = Field(default=5000, ge=100, le=20000)
    use_results: bool = Field(
        default=True,
        description="Condition the simulation on recorded final results.",
    )


class GroupSimRow(BaseModel):
    team: str
    win_group_pct: float
    second_pct: float
    top2_pct: float
    third_pct: float
    avg_points: float


class GroupSimResponse(BaseModel):
    group: str
    n_sims: int
    played: int = 0
    table: List[GroupSimRow]


class ResultIn(BaseModel):
    goals_home: int = Field(ge=0, le=20)
    goals_away: int = Field(ge=0, le=20)
    status: str = Field(default="final", pattern="^(live|final)$")


class ResultOut(BaseModel):
    fixture_id: str
    group: str
    matchday: int
    date: str
    home: str
    away: str
    goals_home: Optional[int] = None
    goals_away: Optional[int] = None
    status: str = "scheduled"
    source: Optional[str] = None
    updated_at: Optional[str] = None


class ScrapeEloUpdate(BaseModel):
    team: str
    live_elo: float
    model_elo: float
    delta: float


class ScrapeResponse(BaseModel):
    status: str
    fetched_at: str
    elo_updates: List[ScrapeEloUpdate]
    results_found: int
    messages: List[str]


class AdjustedTeamOut(BaseModel):
    team: str
    group: str
    base_elo: float
    adjusted_elo: float
    elo_delta: float
    base_form: float
    adjusted_form: float
    form_delta: float
    matches_played: int


class TournamentSimRequest(BaseModel):
    n_sims: int = Field(default=2000, ge=100, le=10000)


class TournamentSimRow(BaseModel):
    group: str
    team: str
    elo: int
    win_group_pct: float
    top2_pct: float
    best_third_pct: float
    qualify_r32_pct: float


class TournamentSimResponse(BaseModel):
    n_sims: int
    table: List[TournamentSimRow]
