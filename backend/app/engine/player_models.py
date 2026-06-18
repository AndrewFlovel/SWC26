"""Player-level data model for the granular per-game analyzer.

Defines the position taxonomy, the canonical unit-pitch coordinate system used
by the geometric matchup engine (see lineup_analyzer), and the supported
formations as ordered 11-slot templates. Each formation slot carries its own
(x, y) so the analyzer is fully formation-driven — no hand-coded matchup tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# Fine-grained position taxonomy used across scoring and matchup analysis.
POSITIONS: Tuple[str, ...] = (
    "GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "ST",
)

# Coarse grouping (used by the dominance heatmap and group-level summaries).
GROUP_OF: Dict[str, str] = {
    "GK": "GK",
    "CB": "DEF", "LB": "DEF", "RB": "DEF",
    "CDM": "MID", "CM": "MID", "CAM": "MID",
    "LW": "ATT", "RW": "ATT", "ST": "ATT",
}

# Positions whose primary job is to create/score (battle initiators) and the
# weight of each in the attacking index (normalized over those present).
ATTACK_CONTRIB: Dict[str, float] = {
    "ST": 0.30, "LW": 0.20, "RW": 0.20, "CAM": 0.18, "CM": 0.12,
}

# Positions that defend a zone (battle responders).
DEFEND_ROLES: Tuple[str, ...] = ("GK", "CB", "LB", "RB", "CDM", "CM")

# Position interchangeability for the optimal-lineup assignment. Exact match
# scores 1.0; a listed adjacency scores 0.6; anything else is infeasible.
ADJACENCY: Dict[str, Tuple[str, ...]] = {
    "GK": (),
    "CB": ("LB", "RB", "CDM"),
    "LB": ("CB", "LW", "CM"),
    "RB": ("CB", "RW", "CM"),
    "CDM": ("CM", "CB"),
    "CM": ("CDM", "CAM", "LB", "RB"),
    "CAM": ("CM", "LW", "RW", "ST"),
    "LW": ("RW", "CAM", "ST", "LB"),
    "RW": ("LW", "CAM", "ST", "RB"),
    "ST": ("CAM", "LW", "RW"),
}


def slot_fit(player_pos: str, slot_pos: str) -> float:
    """Suitability of a player's natural position for a formation slot."""
    if player_pos == slot_pos:
        return 1.0
    if slot_pos in ADJACENCY.get(player_pos, ()):
        return 0.6
    return 0.0


@dataclass(frozen=True)
class Slot:
    """A single position in a formation, with its canonical pitch coordinate.

    `label` is unique within a formation (e.g. "CB_L"); `position` is the
    taxonomy role used for scoring and compatibility. Coordinates are on a unit
    pitch with the team attacking toward y = 1.
    """

    label: str
    position: str
    x: float
    y: float

    @property
    def coord(self) -> Tuple[float, float]:
        return (self.x, self.y)


def _slots(*rows: Tuple[str, str, float, float]) -> List[Slot]:
    return [Slot(label, pos, x, y) for label, pos, x, y in rows]


# Supported formations as ordered 11-slot templates. The order defines the
# contract for lineup name lists in the API (name[i] fills slot[i]).
FORMATIONS: Dict[str, List[Slot]] = {
    "4-3-3": _slots(
        ("GK", "GK", 0.50, 0.05),
        ("LB", "LB", 0.15, 0.25), ("CB_L", "CB", 0.38, 0.18),
        ("CB_R", "CB", 0.62, 0.18), ("RB", "RB", 0.85, 0.25),
        ("CDM", "CDM", 0.50, 0.40),
        ("CM_L", "CM", 0.35, 0.52), ("CM_R", "CM", 0.65, 0.52),
        ("LW", "LW", 0.18, 0.75), ("ST", "ST", 0.50, 0.82),
        ("RW", "RW", 0.82, 0.75),
    ),
    "4-2-3-1": _slots(
        ("GK", "GK", 0.50, 0.05),
        ("LB", "LB", 0.15, 0.25), ("CB_L", "CB", 0.38, 0.18),
        ("CB_R", "CB", 0.62, 0.18), ("RB", "RB", 0.85, 0.25),
        ("CDM_L", "CDM", 0.38, 0.38), ("CDM_R", "CDM", 0.62, 0.38),
        ("CAM", "CAM", 0.50, 0.58),
        ("LW", "LW", 0.18, 0.72), ("RW", "RW", 0.82, 0.72),
        ("ST", "ST", 0.50, 0.82),
    ),
    "4-4-2": _slots(
        ("GK", "GK", 0.50, 0.05),
        ("LB", "LB", 0.15, 0.25), ("CB_L", "CB", 0.38, 0.18),
        ("CB_R", "CB", 0.62, 0.18), ("RB", "RB", 0.85, 0.25),
        ("LM", "LW", 0.15, 0.55), ("CM_L", "CM", 0.38, 0.50),
        ("CM_R", "CM", 0.62, 0.50), ("RM", "RW", 0.85, 0.55),
        ("ST_L", "ST", 0.38, 0.80), ("ST_R", "ST", 0.62, 0.80),
    ),
    "3-5-2": _slots(
        ("GK", "GK", 0.50, 0.05),
        ("CB_L", "CB", 0.30, 0.18), ("CB_C", "CB", 0.50, 0.15),
        ("CB_R", "CB", 0.70, 0.18),
        ("LWB", "LB", 0.12, 0.48), ("CM_L", "CM", 0.38, 0.50),
        ("CDM", "CDM", 0.50, 0.40), ("CM_R", "CM", 0.62, 0.50),
        ("RWB", "RB", 0.88, 0.48),
        ("ST_L", "ST", 0.40, 0.80), ("ST_R", "ST", 0.60, 0.80),
    ),
}


@dataclass
class PlayerProfile:
    """Per-player statistical profile (per-90 rates and aggregate percentages).

    `pps` is the composite Player Performance Score, filled by player_scorer.
    """

    name: str
    team: str
    position: str
    age: int
    caps: int
    international_goals: int
    club: str
    # Attacking (per 90)
    xg90: float
    xa90: float
    shots90: float
    progressive_passes90: float
    shot_creating_actions90: float
    dribbles_completed90: float
    # Defending (per 90 / percentages)
    tackles_won_pct: float
    interceptions90: float
    clearances90: float
    pressures90: float
    pressures_won_pct: float
    aerial_won_pct: float
    # Workload
    minutes_played: int
    # Appearances / discipline season totals (defaulted)
    starts: int = 0
    assists: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    # Meta (defaulted)
    position_group: str = ""
    is_starter: bool = False
    injury_flag: bool = False
    source: str = "seed"
    scraped_at: str = ""
    pps: float = 0.0

    # Per-90 fields that must never be negative.
    _RATE_FIELDS = (
        "xg90", "xa90", "shots90", "progressive_passes90",
        "shot_creating_actions90", "dribbles_completed90",
        "interceptions90", "clearances90", "pressures90",
    )
    # Percentage fields constrained to [0, 100].
    _PCT_FIELDS = ("tackles_won_pct", "pressures_won_pct", "aerial_won_pct")

    def __post_init__(self) -> None:
        if self.position not in POSITIONS:
            raise ValueError(
                f"Unknown position '{self.position}' for {self.name}; "
                f"expected one of {POSITIONS}."
            )
        if not self.position_group:
            self.position_group = GROUP_OF[self.position]
        for f in self._RATE_FIELDS:
            if getattr(self, f) < 0:
                raise ValueError(f"{f} must be >= 0 for {self.name}.")
        for f in self._PCT_FIELDS:
            v = getattr(self, f)
            if not (0.0 <= v <= 100.0):
                raise ValueError(f"{f} must be in [0, 100] for {self.name}.")
        if self.minutes_played < 0:
            raise ValueError(f"minutes_played must be >= 0 for {self.name}.")
        for f in ("starts", "assists", "yellow_cards", "red_cards"):
            if getattr(self, f) < 0:
                raise ValueError(f"{f} must be >= 0 for {self.name}.")

    @classmethod
    def from_dict(cls, raw: dict, *, team: str = "", source: str = "seed") -> "PlayerProfile":
        """Build a profile from a JSON row, tolerating absent optional fields.

        `position_group` is derived from `position` when missing.
        """
        return cls(
            name=raw["name"],
            team=raw.get("team", team),
            position=raw["position"],
            age=int(raw.get("age", 0)),
            caps=int(raw.get("caps", 0)),
            international_goals=int(raw.get("international_goals", 0)),
            club=raw.get("club", ""),
            xg90=float(raw.get("xg90", 0.0)),
            xa90=float(raw.get("xa90", 0.0)),
            shots90=float(raw.get("shots90", 0.0)),
            progressive_passes90=float(raw.get("progressive_passes90", 0.0)),
            shot_creating_actions90=float(raw.get("shot_creating_actions90", 0.0)),
            dribbles_completed90=float(raw.get("dribbles_completed90", 0.0)),
            tackles_won_pct=float(raw.get("tackles_won_pct", 0.0)),
            interceptions90=float(raw.get("interceptions90", 0.0)),
            clearances90=float(raw.get("clearances90", 0.0)),
            pressures90=float(raw.get("pressures90", 0.0)),
            pressures_won_pct=float(raw.get("pressures_won_pct", 0.0)),
            aerial_won_pct=float(raw.get("aerial_won_pct", 0.0)),
            minutes_played=int(raw.get("minutes_played", 0)),
            starts=int(raw.get("starts", 0)),
            assists=int(raw.get("assists", 0)),
            yellow_cards=int(raw.get("yellow_cards", 0)),
            red_cards=int(raw.get("red_cards", 0)),
            position_group=raw.get("position_group", ""),
            is_starter=bool(raw.get("is_starter", False)),
            injury_flag=bool(raw.get("injury_flag", False)),
            source=raw.get("source", source),
            scraped_at=raw.get("scraped_at", ""),
            pps=float(raw.get("pps", 0.0)),
        )


def mirror(coord: Tuple[float, float]) -> Tuple[float, float]:
    """Map an away player's own-formation coordinate onto the shared pitch as
    seen from the home team's attacking perspective (point reflection)."""
    x, y = coord
    return (1.0 - x, 1.0 - y)
