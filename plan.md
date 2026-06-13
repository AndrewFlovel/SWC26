# Plan: Granular Per-Game Player Analyzer

## Context

Today SWC26 predicts matches at the **team** level: each fixture is reduced to two
`TeamProfile`s (Elo, xG/xGA, form, injury) and run through the Elo+Poisson engine
(`backend/app/engine/`). This feature adds a **per-game, player-level** analyzer: when a
specific fixture is selected, the engine pulls the two squads and their individual
statistics, then scores the matchup position-by-position — surfacing tactical detail
(who wins each battle, best XI, pressing mismatch) that team aggregates hide.

Delivery is staged. **Round 1 (this document's focus) is a backend-first slice**: the
analytics engine, API endpoints, seed player data, and tests — fully verifiable via
pytest and curl, no UI or live network required. The React UI and the Selenium
confirmed-lineup scraper are explicit follow-ons (§9).

Scraping is **hybrid**: `requests`+`BeautifulSoup` for FBref's server-rendered stat
tables (no new dependency — both already in `requirements.txt`); Selenium is reserved for
the JS-rendered confirmed-lineup page in the later phase.

Design honors `.claude/agent.md`: **Zero Placeholder Policy** (complete, functional code)
and **explicit division-by-zero / degenerate-input guards**. It mirrors existing
conventions: the `results_store` atomic-write + `version` counter, the
`lru_cache(version)` invalidation in `services/metrics.py`, the graceful "never-raises"
scraper pattern in `services/scraper.py`, and the `@dataclass` engine core in
`engine/core.py`.

---

## What ships in Round 1

| Layer | File | Action |
|---|---|---|
| Models | `backend/app/engine/player_models.py` | **new** — `PlayerProfile`, position taxonomy, canonical pitch coordinates, `FORMATIONS` |
| Scoring | `backend/app/engine/player_scorer.py` | **new** — reference-normalized PPS |
| Analytics | `backend/app/engine/lineup_analyzer.py` | **new** — FCM, PMS, FSI, PIS, PDH, OLS |
| Exports | `backend/app/engine/__init__.py` | edit — export the new classes/functions |
| Cache | `backend/app/services/player_store.py` | **new** — squad cache (mirrors `results_store`) |
| Scraper | `backend/app/services/player_scraper.py` | **new** — FBref requests/BS4 scrape, graceful fallback |
| Schemas | `backend/app/schemas.py` | edit — add player/lineup/optimal-xi models |
| API | `backend/app/main.py` | edit — add 4 endpoints |
| Seed data | `backend/app/data/players/<slug>.json` | **new** — hand-built squads for the teams the tests use |
| Tests | `backend/tests/test_lineup_engine.py` | **new** — engine + endpoint tests (offline, deterministic) |

`requirements.txt` needs **no change** in Round 1 (`scipy`, `requests`, `beautifulsoup4`
already present). `selenium` is added only in the follow-on lineup phase.

---

## 1. Data models — `engine/player_models.py`

```python
POSITIONS = ("GK","CB","LB","RB","CDM","CM","CAM","LW","RW","ST")
GROUP_OF = {"GK":"GK","CB":"DEF","LB":"DEF","RB":"DEF",
            "CDM":"MID","CM":"MID","CAM":"MID","LW":"ATT","RW":"ATT","ST":"ATT"}

@dataclass
class PlayerProfile:
    name: str; team: str; position: str; position_group: str
    age: int; caps: int; international_goals: int; club: str
    # attacking per-90
    xg90: float; xa90: float; shots90: float
    progressive_passes90: float; shot_creating_actions90: float; dribbles_completed90: float
    # defending per-90 / %
    tackles_won_pct: float; interceptions90: float; clearances90: float
    pressures90: float; pressures_won_pct: float; aerial_won_pct: float
    minutes_played: int
    is_starter: bool = False; injury_flag: bool = False
    source: str = "seed"; scraped_at: str = ""
    pps: float = 0.0          # filled by player_scorer
    # __post_init__ validates position in POSITIONS and rates >= 0 (degenerate-input guard)
```

**Canonical coordinates** (unit pitch, attacking "up", `y∈[0,1]`) and **`FORMATIONS`**
(name → ordered 11-slot list) live here as module constants. Supported now: `4-3-3`,
`4-2-3-1`, `4-4-2`, `3-5-2`. Each slot carries its `(x,y)` so the analyzer is fully
formation-driven (no hand-coded matchup tables).

---

## 2. Reference-normalized PPS — `player_scorer.py`

Scraping is **on-demand for the 2 teams of one fixture**, so we cannot normalize "across
all 48 squads". Instead normalize each metric against a **fixed reference distribution**
(tunable min→max anchors from elite-football per-90 ranges), so a player's score is
absolute and stable regardless of who else has been scraped:

```python
REFERENCE_RANGES = {  # metric: (lo->0.0, hi->1.0), clamped
  "xg90": (0.0, 0.80), "xa90": (0.0, 0.50), "shots90": (0.0, 4.0),
  "progressive_passes90": (0.0, 8.0), "shot_creating_actions90": (0.0, 5.0),
  "dribbles_completed90": (0.0, 3.0),
  "tackles_won_pct": (40.0, 75.0), "interceptions90": (0.0, 2.5),
  "clearances90": (0.0, 6.0), "pressures90": (0.0, 25.0),
  "pressures_won_pct": (20.0, 40.0), "aerial_won_pct": (30.0, 75.0),
}
norm(v, lo, hi) = clip((v - lo) / (hi - lo), 0, 1)   # hi>lo guaranteed in table
```

**Component scores use a weighted *arithmetic* mean (not geometric)** — a geometric mean
zero-collapses when any input is 0 (normal for a defender's xG), which also risks the
degenerate output `agent.md` warns against:

- `att_score` = wmean(xg90, xa90, sca90, prog90, shots90, dribbles90)
- `def_score` = wmean(tackles_won_pct, interceptions90, clearances90, pressures_won_pct, aerial_won_pct)
- `phys_score` = wmean(pressures90, dribbles90)

`PPS = w_att·att + w_def·def + w_phys·phys`, clamped to `[0,1]`, with role weights:

| Pos | w_att | w_def | w_phys |  | Pos | w_att | w_def | w_phys |
|---|---|---|---|---|---|---|---|---|
| GK | .05 | .85 | .10 | | CAM | .65 | .20 | .15 |
| CB | .10 | .80 | .10 | | LW/RW | .75 | .10 | .15 |
| LB/RB | .25 | .55 | .20 | | ST | .85 | .05 | .10 |
| CDM | .20 | .65 | .15 | | CM | .40 | .40 | .20 |

`score_squad(players)` fills `player.pps` for a list. All means guard `Σw>0`.

---

## 3. Matchup analytics — `lineup_analyzer.py`

- **FCM (Formation Compatibility Matrix).** Geometric pairing: for each home attacking
  position, relevance to away position *j* = inverse-distance weight over the *k=2*
  nearest defensively-relevant opponents (Euclidean on canonical coords), normalized to
  sum 1. Computed both directions. No hand-coded matchups → any supported formation pair
  works.
- **PMS (Positional Matchup Score).** `PMS = clip(0.5 + (PPS_att − resistance)/2, 0, 1)`
  where `resistance = Σ_j FCM(att,j)·PPS(def_j)`. 0.5 = even, >0.5 favors attacker.
- **FSI (Formation Strength Index).** Symmetric & bounded: compute `home_index` (zone-
  weighted mean of home attacking battles) and `away_index` (mirror), then
  `FSI = clip(0.5 + (home_index − away_index)/2, 0, 1)`. >0.5 favors home. One zone-
  importance table, normalized to sum to 1.
- **PIS (Pressing Intensity Score).** `PIS(A vs B) = (won%_A · pressures90_A) /
  (prog_passes90_B + ε)` on XI aggregates; `ε` guards the divide.
- **PDH (Positional Dominance Heatmap).** 3×3 zone grid; per cell `Σ(xg90_n+xa90_n)` of
  home players in the cell minus `Σ def_score` of away players (coords mirrored for away).
  Returns a 3×3 float array.
- **OLS (Optimal Lineup Selector).** Reuse **`scipy.optimize.linear_sum_assignment`**
  (scipy already a dependency) on a `players × slots` cost matrix
  `cost = −(slot_fit · pps_contribution)`; `slot_fit` from a compatibility table (1.0
  exact, 0.6 adjacent e.g. CM↔CDM / LW↔RW, incompatible → large finite penalty). Returns
  the optimal XI + its FSI vs the opponent, plus up to 2 heuristic alternates (swap the
  lowest-margin slot). O(n³) with n≤26 → instant.

---

## 4. Cache + scraper

**`services/player_store.py`** — mirrors `results_store`: load `data/players/<slug>.json`,
atomic `.tmp → os.replace` writes, in-memory `version` counter, plus an
`lru_cache(version)` helper for scored squads (same pattern as `services/metrics.py`).
`get_squad(slug)` returns seed/cached players or `None`.

**`services/player_scraper.py`** — hybrid, **never raises** (like `scraper.py`):
`scrape_squad(team)` fetches FBref national-team stat/defense tables with `requests`
(descriptive User-Agent, ~3s inter-request delay for FBref's strict rate limit), maps
FBref position codes (`DF/MF/FW`, combos) → our taxonomy via a normalizer, applies a
`PLAYER_ALIASES` dict (same idea as `NAME_ALIASES`), writes through `player_store`. On any
failure or empty parse it returns the existing seed/cache and tags `source` accordingly —
honoring "scrape on select" while staying robust to FBref blocks or not-yet-populated 2026
pages. (The Selenium Sofascore confirmed-XI scraper is the follow-on phase.)

---

## 5. API — `main.py` + `schemas.py`

| Method | Path | Behavior |
|---|---|---|
| POST | `/api/scrape/players` | body `{fixture_id}` → resolve home/away from `get_fixtures()`, scrape-or-fallback both, score, return both squads + `source` |
| GET | `/api/players/{slug}` | scored cached/seed squad; 404 if none |
| POST | `/api/analyze/lineup` | two lineups+formations → `{fsi, pis_home, pis_away, positional_battles[], dominance_heatmap[3][3]}` |
| POST | `/api/analyze/optimal-xi` | `{team, formation, opponent_lineup, opponent_formation}` → top-3 `XiCandidate` |

New Pydantic models follow the existing `schemas.py` style (Field constraints, `Optional`
defaults): `PlayerOut`, `PlayerSquadResponse`, `LineupAnalysisRequest/Response`,
`PositionalBattleOut`, `OptimalXiRequest/Response`, `XiCandidate`. Lineups validated as
exactly 11 names; unknown player/formation → 422; unknown fixture/team → 404 (reuse the
`_get_team`/`_fixtures_by_id` helper style already in `main.py`).

---

## 6. Seed data — `data/players/<slug>.json`

Hand-built squads (≈16 players each) for the teams the tests exercise — at minimum both
sides of two representative fixtures (e.g. a Group H / Group J heavyweight tie). Schema =
list of `PlayerProfile` fields. This makes the whole feature **demoable and tests
deterministic with zero network**, matching the repo ethos (full `teams/fixtures/venues`
seed data; `scraper.py` docstring: manual/seed is the reliable path).

---

## 7. Tests — `backend/tests/test_lineup_engine.py`

Mirror `test_engine.py` (pytest fixtures + `TestClient`), all on seed data:
- PPS ∈ [0,1]; a known elite striker out-scores a backup.
- PMS direction; FSI ∈ [0,1] and `FSI(home,away) ≈ 1 − FSI(away,home)` (symmetry).
- OLS returns exactly 11 players, **no duplicates**, every slot position-compatible.
- PDH is 3×3 and finite; PIS finite even when a team's prog-passes ≈ 0 (ε guard).
- Endpoint tests: `/api/analyze/lineup` 200 + shape; unknown player → 422; unknown
  fixture on `/api/scrape/players` → 404; `/api/players/{unknown}` → 404.

---

## 8. Verification

```bash
cd backend && . .venv/bin/activate
pytest tests/test_lineup_engine.py -q          # offline, deterministic
uvicorn app.main:app --reload --port 8001      # then, in another shell:
curl -s localhost:8001/api/players/spain | head
curl -s -X POST localhost:8001/api/scrape/players -H 'Content-Type: application/json' \
     -d '{"fixture_id":"H1"}'
curl -s -X POST localhost:8001/api/analyze/optimal-xi -H 'Content-Type: application/json' \
     -d '{"team":"Spain","formation":"4-3-3","opponent_lineup":[...11...],"opponent_formation":"4-2-3-1"}'
```
Also confirm `pytest -q` (full suite) stays green and `/docs` lists the 4 new endpoints.

---

## 9. Follow-on (later rounds)

- **Frontend:** `PlayerAnalysis.tsx` overlay (Squad / Formation / Battles / Optimizer
  tabs), `FormationView.tsx` (SVG pitch + PDH overlay), `PositionalBattles.tsx`,
  `LineupOptimizer.tsx`, `PlayerCard.tsx`; new TS types + `client.ts` calls reusing the
  `request<T>` helper and a poll/debounce hook like `useLivePrediction`. Entry point:
  restructure the `MatchList` card (currently a single `<button>`) so a "Deep Analysis"
  action can sit beside the existing select — or add the trigger inside `MatchAnalysis`.
  i18n EN/ES/PT keys.
- **Selenium lineup scrape:** add `selenium`+`webdriver-manager`, Sofascore confirmed-XI
  via headless Chrome as a background job + `GET /api/scrape/players/status/{fixture_id}`
  polling; Docker image gains Chrome.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| FBref rate-limits / blocks bots (HTTP 429) | ~3s delay, descriptive UA, scrape only the 2 selected teams, cache hard; seed data is the reliable fallback |
| 2026 squad pages sparse | Seed JSON ships with the feature; scrape only enhances |
| FBref coarse positions (DF/MF/FW) | Normalizer + group-default; OLS position-flexibility absorbs ambiguity |
| Player name mismatches | `PLAYER_ALIASES` dict (same pattern as `NAME_ALIASES`) |
| Zero/degenerate inputs | Arithmetic means, ε divide guards, clamps, `__post_init__` validation |
