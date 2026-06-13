"""Geometric, formation-driven matchup analytics for a single fixture.

Given two XIs (each = a formation + 11 player profiles in slot order) this module
computes:

* FCM - per-attacker pairing weights against the nearest opposing defenders,
        derived purely from canonical pitch coordinates (any formation pair works).
* PMS - the score of one positional battle (attacker vs the defenders covering it).
* FSI - a single, symmetric, bounded index of which XI is favored.
* PIS - the pressing-vs-ball-progression mismatch between the two teams.
* PDH - a 3x3 pitch dominance heatmap.
* OLS - the optimal XI for a squad against a known opponent, via the Hungarian
        assignment (scipy.optimize.linear_sum_assignment).

All ratios are epsilon-guarded and all indices are clamped, so degenerate inputs
(empty zones, zero progression) never raise or produce non-finite output.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from scipy.optimize import linear_sum_assignment

from .player_models import (
    ATTACK_CONTRIB,
    DEFEND_ROLES,
    FORMATIONS,
    Slot,
    mirror,
    slot_fit,
)
from .player_models import PlayerProfile
from .player_scorer import facet_scores, normalize, score_squad

EPS = 1e-6
INFEASIBLE = 1e6

# A built XI: each formation slot paired with the player filling it.
Lineup = List[Tuple[Slot, PlayerProfile]]

Coord = Tuple[float, float]


def build_lineup(formation: str, players: Sequence[PlayerProfile]) -> Lineup:
    """Zip a formation's ordered slots with 11 players (player[i] -> slot[i])."""
    if formation not in FORMATIONS:
        raise ValueError(
            f"Unknown formation '{formation}'; supported: {sorted(FORMATIONS)}."
        )
    slots = FORMATIONS[formation]
    if len(players) != len(slots):
        raise ValueError(
            f"Formation '{formation}' needs {len(slots)} players, got {len(players)}."
        )
    return list(zip(slots, players))


def _fcm_weights(att: Coord, defenders: Sequence[Tuple[Coord, PlayerProfile]],
                 k: int = 2) -> List[Tuple[float, PlayerProfile]]:
    """Inverse-distance pairing weights from one attacker to its nearest k
    opposing defenders, normalized to sum 1."""
    if not defenders:
        return []
    dists = [
        (((att[0] - c[0]) ** 2 + (att[1] - c[1]) ** 2) ** 0.5, p)
        for c, p in defenders
    ]
    dists.sort(key=lambda dp: dp[0])
    nearest = dists[: max(k, 1)]
    raw = [(1.0 / (d + EPS), p) for d, p in nearest]
    total = sum(w for w, _ in raw)
    if total <= 0:
        return [(1.0 / len(nearest), p) for _, p in nearest]
    return [(w / total, p) for w, p in raw]


def _attacking_index(
    attackers: Sequence[Tuple[Coord, PlayerProfile]],
    defenders: Sequence[Tuple[Coord, PlayerProfile]],
) -> Tuple[float, List[dict]]:
    """Zone-weighted mean of attacking battles, plus per-battle detail.

    `attackers`/`defenders` coords must already be expressed in the attacking
    team's frame (the caller mirrors the defending team). Returns (index, battles)
    where index in [0, 1]; 0.5 = neutral. Empty attack -> neutral 0.5.
    """
    battles: List[dict] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for coord, atk in attackers:
        zone_w = ATTACK_CONTRIB.get(atk.position, 0.0)
        if zone_w <= 0:
            continue
        pairing = _fcm_weights(coord, defenders)
        resistance = sum(w * d.pps for w, d in pairing)
        pms = min(max(0.5 + (atk.pps - resistance) / 2.0, 0.0), 1.0)
        primary = max(pairing, key=lambda wp: wp[0])[1] if pairing else None
        battles.append({
            "attacker": atk.name,
            "attacker_position": atk.position,
            "attacker_pps": round(atk.pps, 4),
            "defender": primary.name if primary else None,
            "defender_position": primary.position if primary else None,
            "defender_pps": round(primary.pps, 4) if primary else None,
            "pms": round(pms, 4),
        })
        weighted_sum += zone_w * pms
        weight_total += zone_w
    index = weighted_sum / weight_total if weight_total > 0 else 0.5
    return index, battles


def _split(lineup: Lineup, mirror_coords: bool) -> Tuple[
    List[Tuple[Coord, PlayerProfile]], List[Tuple[Coord, PlayerProfile]]
]:
    """Return (attackers, defenders) as (coord, player) pairs, optionally
    mirroring every coordinate into the opponent's frame."""
    attackers: List[Tuple[Coord, PlayerProfile]] = []
    defenders: List[Tuple[Coord, PlayerProfile]] = []
    for slot, player in lineup:
        coord = mirror(slot.coord) if mirror_coords else slot.coord
        if slot.position in ATTACK_CONTRIB:
            attackers.append((coord, player))
        if slot.position in DEFEND_ROLES:
            defenders.append((coord, player))
    return attackers, defenders


def formation_strength_index(home: Lineup, away: Lineup) -> Tuple[float, float, float]:
    """Symmetric, bounded matchup index from the home team's perspective.

    Returns (fsi, home_index, away_index). fsi > 0.5 favors home, and
    fsi(home, away) == 1 - fsi(away, home) by construction.
    """
    home_att, _ = _split(home, mirror_coords=False)
    away_att, _ = _split(away, mirror_coords=False)
    # Defenders are mirrored into the attacking team's frame.
    _, away_def_in_home = _split(away, mirror_coords=True)
    _, home_def_in_away = _split(home, mirror_coords=True)

    home_index, _ = _attacking_index(home_att, away_def_in_home)
    away_index, _ = _attacking_index(away_att, home_def_in_away)
    fsi = min(max(0.5 + (home_index - away_index) / 2.0, 0.0), 1.0)
    return fsi, home_index, away_index


def positional_battles(home: Lineup, away: Lineup) -> List[dict]:
    """Per-attacker battle detail for both teams, tagged with side and favored team."""
    home_att, _ = _split(home, mirror_coords=False)
    away_att, _ = _split(away, mirror_coords=False)
    _, away_def_in_home = _split(away, mirror_coords=True)
    _, home_def_in_away = _split(home, mirror_coords=True)

    _, home_battles = _attacking_index(home_att, away_def_in_home)
    _, away_battles = _attacking_index(away_att, home_def_in_away)

    out: List[dict] = []
    for b in home_battles:
        b = {**b, "side": "home", "favored": "home" if b["pms"] >= 0.5 else "away"}
        out.append(b)
    for b in away_battles:
        b = {**b, "side": "away", "favored": "away" if b["pms"] >= 0.5 else "home"}
        out.append(b)
    return out


def _team_press_profile(lineup: Lineup) -> Tuple[float, float, float]:
    """(avg pressures_won_fraction, avg pressures90, avg progressive_passes90)."""
    n = len(lineup)
    if n == 0:
        return 0.0, 0.0, 0.0
    won = sum(p.pressures_won_pct for _, p in lineup) / n / 100.0
    pres = sum(p.pressures90 for _, p in lineup) / n
    prog = sum(p.progressive_passes90 for _, p in lineup) / n
    return won, pres, prog


def pressing_intensity(attacker: Lineup, opponent: Lineup) -> float:
    """How effectively `attacker` disrupts `opponent` ball progression."""
    won, pres, _ = _team_press_profile(attacker)
    _, _, opp_prog = _team_press_profile(opponent)
    return round((won * pres) / (opp_prog + EPS), 4)


def dominance_heatmap(home: Lineup, away: Lineup) -> List[List[float]]:
    """3x3 pitch grid: home attacking threat minus away defensive presence.

    Row 0 is the home defensive third (y~0), row 2 the home attacking third.
    """
    grid = [[0.0, 0.0, 0.0] for _ in range(3)]

    def cell(coord: Coord) -> Tuple[int, int]:
        col = min(int(coord[0] * 3), 2)
        row = min(int(coord[1] * 3), 2)
        return row, col

    for slot, p in home:
        r, c = cell(slot.coord)
        grid[r][c] += normalize("xg90", p.xg90) + normalize("xa90", p.xa90)
    for slot, p in away:
        r, c = cell(mirror(slot.coord))
        _, dfn, _ = facet_scores(p)
        grid[r][c] -= dfn
    return [[round(v, 4) for v in row] for row in grid]


def analyze_lineups(home: Lineup, away: Lineup) -> dict:
    """Full per-fixture matchup report for two explicit XIs."""
    fsi, home_index, away_index = formation_strength_index(home, away)
    return {
        "fsi": round(fsi, 4),
        "home_index": round(home_index, 4),
        "away_index": round(away_index, 4),
        "pis_home": pressing_intensity(home, away),
        "pis_away": pressing_intensity(away, home),
        "positional_battles": positional_battles(home, away),
        "dominance_heatmap": dominance_heatmap(home, away),
    }


# --------------------------------------------------------------------------- #
# Optimal Lineup Selector (Hungarian assignment)
# --------------------------------------------------------------------------- #

def _assign(squad: Sequence[PlayerProfile], slots: Sequence[Slot]) -> List[int]:
    """Return, per slot, the index into `squad` assigned by min-cost matching.

    Cost = -(slot_fit * pps); infeasible pairings carry a large finite penalty so
    the solver fills every slot even when ideal players are scarce.
    """
    n_players, n_slots = len(squad), len(slots)
    cost = [[0.0] * n_slots for _ in range(n_players)]
    for i, p in enumerate(squad):
        for j, s in enumerate(slots):
            fit = slot_fit(p.position, s.position)
            cost[i][j] = -(fit * p.pps) if fit > 0 else INFEASIBLE
    row_ind, col_ind = linear_sum_assignment(cost)
    slot_to_player = [-1] * n_slots
    for i, j in zip(row_ind, col_ind):
        slot_to_player[j] = i
    return slot_to_player


def _lineup_from_assignment(
    squad: Sequence[PlayerProfile], slots: Sequence[Slot], slot_to_player: Sequence[int]
) -> Lineup:
    return [(slots[j], squad[slot_to_player[j]]) for j in range(len(slots))]


def optimal_xi(
    squad: Sequence[PlayerProfile],
    formation: str,
    opponent: Lineup,
    top_n: int = 3,
) -> List[dict]:
    """Best XI(s) for `squad` in `formation` against a known opponent XI.

    Returns up to `top_n` candidates (the optimal assignment plus least-disruptive
    single-slot swaps), each with its lineup, FSI and pressing index, sorted by FSI.
    """
    if formation not in FORMATIONS:
        raise ValueError(
            f"Unknown formation '{formation}'; supported: {sorted(FORMATIONS)}."
        )
    slots = FORMATIONS[formation]
    if len(squad) < len(slots):
        raise ValueError(
            f"Squad has {len(squad)} players; formation needs {len(slots)}."
        )
    score_squad(squad)  # ensure pps populated

    base_assign = _assign(squad, slots)
    candidates: List[Sequence[int]] = [base_assign]

    # Generate alternates: for the two least-disruptive slots, swap the assigned
    # player for the next-best eligible bench player.
    used = set(base_assign)
    swap_losses: List[Tuple[float, int, int]] = []  # (loss, slot_j, bench_i)
    for j, s in enumerate(slots):
        cur_i = base_assign[j]
        cur_val = slot_fit(squad[cur_i].position, s.position) * squad[cur_i].pps
        best_bench, best_val = -1, -1.0
        for i, p in enumerate(squad):
            if i in used:
                continue
            val = slot_fit(p.position, s.position) * p.pps
            if val > best_val:
                best_bench, best_val = i, val
        if best_bench >= 0 and best_val > 0:
            swap_losses.append((cur_val - best_val, j, best_bench))
    swap_losses.sort(key=lambda t: t[0])
    for _, j, bench_i in swap_losses[: max(top_n - 1, 0)]:
        alt = list(base_assign)
        alt[j] = bench_i
        candidates.append(alt)

    seen: set = set()
    rows: List[dict] = []
    for assign in candidates:
        key = tuple(assign)
        if key in seen or -1 in assign:
            continue
        seen.add(key)
        lineup = _lineup_from_assignment(squad, slots, assign)
        fsi, _, _ = formation_strength_index(lineup, opponent)
        rows.append({
            "formation": formation,
            "lineup": [
                {"slot": s.label, "position": s.position, "player": p.name,
                 "pps": round(p.pps, 4)}
                for s, p in lineup
            ],
            "fsi": round(fsi, 4),
            "pis": pressing_intensity(lineup, opponent),
        })
    rows.sort(key=lambda r: r["fsi"], reverse=True)
    return rows[:top_n]
