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


# --------------------------------------------------------------------------- #
# Per-game player analyzer
# --------------------------------------------------------------------------- #

class PlayerOut(BaseModel):
    name: str
    team: str
    position: str
    position_group: str
    age: int
    caps: int
    international_goals: int
    club: str
    xg90: float
    xa90: float
    shots90: float
    progressive_passes90: float
    shot_creating_actions90: float
    dribbles_completed90: float
    tackles_won_pct: float
    interceptions90: float
    clearances90: float
    pressures90: float
    pressures_won_pct: float
    aerial_won_pct: float
    minutes_played: int
    is_starter: bool
    injury_flag: bool
    pps: float


class PlayerScrapeRequest(BaseModel):
    fixture_id: str
    live: bool = Field(
        default=True,
        description="Attempt a live FBref scrape; falls back to seed/cache on failure.",
    )


class TeamSquadOut(BaseModel):
    team: str
    slug: str
    source: str           # "scraped" | "cached" | "seed" | "unavailable"
    players: List[PlayerOut]


class PlayerSquadResponse(BaseModel):
    fixture_id: str
    home: TeamSquadOut
    away: TeamSquadOut
    scraped_at: str
    messages: List[str]


class LineupAnalysisRequest(BaseModel):
    home_team: str
    away_team: str
    home_formation: str
    away_formation: str
    home_lineup: List[str] = Field(min_length=11, max_length=11)
    away_lineup: List[str] = Field(min_length=11, max_length=11)


class PositionalBattleOut(BaseModel):
    side: str
    attacker: str
    attacker_position: str
    attacker_pps: float
    defender: Optional[str] = None
    defender_position: Optional[str] = None
    defender_pps: Optional[float] = None
    pms: float
    favored: str


class LineupAnalysisResponse(BaseModel):
    fsi: float
    home_index: float
    away_index: float
    pis_home: float
    pis_away: float
    positional_battles: List[PositionalBattleOut]
    dominance_heatmap: List[List[float]]


class OptimalXiRequest(BaseModel):
    team: str
    formation: str
    # Opponent is optional: when omitted, the best XI is found against a neutral
    # opponent (FSI ~ 0.5). Provide all three to optimize against a real XI.
    opponent_team: Optional[str] = None
    opponent_formation: Optional[str] = None
    opponent_lineup: Optional[List[str]] = Field(default=None, min_length=11, max_length=11)
    top_n: int = Field(default=3, ge=1, le=5)


class FormationSlotOut(BaseModel):
    slot: str
    position: str
    x: float
    y: float


class XiSlotOut(BaseModel):
    slot: str
    position: str
    player: str
    pps: float


class XiCandidate(BaseModel):
    formation: str
    fsi: float
    pis: float
    lineup: List[XiSlotOut]


class OptimalXiResponse(BaseModel):
    team: str
    opponent_team: str
    candidates: List[XiCandidate]
