# SWC26 — Blood & Glory

> 🌐 **English** · [Español](README.es.md) · Setup guides: [EN](SETUP.md) / [ES](SETUP.es.md)

**Interactive predictive analytics platform for the FIFA World Cup 2026**, built from
deep-research telemetry on the 48 qualified nations: Elo ratings, xG/xGA tactical
profiles, form momentum, injury attrition, transcontinental travel burden, altitude
hypoxia and WBGT heat stress.

Dark, blood-red, WebGL-powered. Drag the sliders — the engine recalculates in real time.
Open any fixture for a player-by-player breakdown: squad ratings, formation matchups,
a best-XI optimizer, and a one-click pull of the **confirmed match-day lineups**. The
interface is available in **English, Spanish and Portuguese** (selector at the top right;
it also auto-detects your browser language).

## Quickstart (Docker)

```bash
docker compose up --build
```

Open <http://localhost:5173>. That's it — nginx serves the frontend and proxies
`/api` to the backend container. For local development without Docker, see
[SETUP.md](SETUP.md).

## Architecture

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  React 19 + TypeScript  │  HTTP  │  FastAPI (Python 3.10+)      │
│  Vite · R3F · Motion    │ ─────► │  numpy · scipy · pandas      │
│  3D hero, dashboard,    │  JSON  │  Elo + xG bivariate Poisson  │
│  live what-if sliders,  │ ◄───── │  Dixon-Coles · Monte Carlo   │
│  i18n EN/ES/PT          │        │                              │
└─────────────────────────┘        └──────────────────────────────┘
```

**The model.** Elo ratings are mapped to expected goals through a bounded `tanh`
supremacy, then blended with an xG-cross model (own attack vs opposing defense).
Both are modulated by form momentum and injury attrition factors, then penalized
for venue altitude (Estadio Azteca: 2,240 m) and WBGT heat burden (NRG Houston:
score 100). Scoreline probabilities use a bivariate Poisson with the Dixon-Coles
low-score correction (ρ = −0.13). Group and tournament outcomes are estimated by
Monte Carlo simulation with full FIFA tiebreakers and the best-8-thirds rule.
A maximum-likelihood calibrator with Dixon-Coles time decay is included
(`backend/app/engine/calibration.py`).

## Per-game player analyzer

Beyond the team-level model, any fixture can be opened for a **player-by-player**
breakdown. Selecting a match triggers a hybrid squad scrape — `requests` against
FBref's server-rendered stat tables, with bundled reference squads as the reliable
fallback (headless-Chrome Selenium adds confirmed match-day lineups on demand —
see below). The scrape reads
**attacking** per-90s from the standard table and **real defensive** metrics
(tackles, interceptions, clearances, aerials) from FBref's comment-wrapped
Defensive-Actions and Misc tables, per-90-normalized via `minutes_90s`; only
pressures fall back to position defaults (FBref discontinued them). Each player gets a
**Player Performance Score (PPS)**: a role-weighted blend of attacking, defensive and
physical facets, each normalized against fixed elite-football reference ranges so
scores are absolute and comparable across squads.

**All 48 teams ship with a committed reference squad**, so every fixture works
offline. FBref squad URLs are resolved through a hybrid map
(`data/fbref_squads.json` + on-demand discovery from FBref's World Cup index); teams
FBref cannot supply get a deterministic synthetic baseline scaled by team strength.
Regenerate or refresh the reference squads with the bootstrap CLI:

```bash
cd backend
python -m scripts.bootstrap_squads            # populate/refresh all 48 teams
python -m scripts.bootstrap_squads --team Brazil --force   # one team, re-scrape
python -m scripts.bootstrap_squads --discover-only         # just refresh the URL map
```

From two XIs the engine derives the matchup geometrically — any formation pair works,
no hand-coded tables:

- **PMS** — positional battle scores (each attacker vs the defenders covering them)
- **FSI** — a single, symmetric Formation Strength Index for the matchup
- **PIS** — pressing-vs-ball-progression mismatch between the sides
- **PDH** — a 3×3 pitch dominance heatmap
- **Optimal XI** — the best lineup for a formation against a given opponent, via the
  Hungarian assignment (`scipy.optimize.linear_sum_assignment`), with ranked alternates

The UI opens a full-screen overlay (Squad · Formation · Battles · Optimizer) with an
SVG pitch, PPS-colored player nodes and the dominance heatmap. Every fixture works out
of the box: Spain, Uruguay, Argentina and Austria ship as hand-curated seed squads,
the other 44 teams as committed reference squads (`source` is reported per team as
`seed`, `scraped` or `synthetic`).

**Confirmed lineups.** A "Confirmed XI" action pulls the announced starting elevens
from Sofascore via headless Chrome. Because that page is JS-rendered and the scrape is
slow, it runs as a background job (`POST /api/scrape/lineups`) that the UI polls
(`GET /api/scrape/players/status/{fixture_id}`); once both XIs are confirmed they are
matched to the squad, ordered into formation slots and applied to the pitch — otherwise
the analyzer keeps its optimal XI. The scraper never raises: missing Chrome, an unmapped
fixture, or lineups not yet announced all fall back to the optimal-XI path.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/players` | Squad coverage across the 48 teams — player count and `source` per team |
| GET | `/api/players/{slug}` | Scored squad (PPS) for a team — seed, scraped or synthetic |
| POST | `/api/scrape/players` | Scrape both squads of a fixture (FBref, reference fallback) |
| POST | `/api/scrape/discover` | Refresh the FBref squad-URL map from the World Cup index |
| POST | `/api/analyze/lineup` | FSI, pressing, positional battles and 3×3 dominance heatmap for two XIs |
| POST | `/api/analyze/optimal-xi` | Best XI (Hungarian) vs an opponent — top-3 candidates |
| GET | `/api/formations` | Formation slot coordinates (4-3-3, 4-2-3-1, 4-4-2, 3-5-2) |
| POST | `/api/scrape/lineups` | Start a background confirmed-XI scrape (Sofascore, headless Chrome) |
| GET | `/api/scrape/players/status/{fixture_id}` | Poll the confirmed-lineup job status/result |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/teams` | 48 teams with Elo, xG/xGA, form, injury metrics |
| GET | `/api/groups` | Official December 2025 draw (12 groups) |
| GET | `/api/matches` | 72 group-stage fixtures with venue context |
| POST | `/api/predict` | Win/draw/loss %, exact-score matrix, top scorelines — accepts live parameter overrides (form, injury, altitude, heat, host advantage, xG blend, ρ) |
| POST | `/api/simulate/group` | Monte Carlo qualification table for one group |
| POST | `/api/simulate/tournament` | R32 qualification odds for all 48 teams |

Interactive OpenAPI docs at `http://localhost:8001/docs`.

## Repository layout

```
docker-compose.yml     One-command deployment (frontend + backend)
backend/app/engine/    Prediction engine (config, core math, predictor, Monte Carlo
                       simulators, MLE calibration, data loader) + player analyzer
                       (player models, PPS scorer, lineup/FSI/optimal-XI analyzer)
backend/app/services/  Results store + metrics replay, day scraper, hybrid FBref
                       player scraper + squad cache, the FBref squad-URL resolver,
                       and the Selenium confirmed-lineup scraper + threaded
                       background-job registry
backend/app/data/      48-team dataset + 16-venue catalogue; data/players/ holds a
                       reference squad per team (4 seed, 44 scraped/synthetic);
                       data/fbref_squads.json is the committed FBref squad-URL map
backend/scripts/       bootstrap_squads.py — one-time CLI to populate/refresh squads
backend/tests/         Engine, results, player-analyzer, player-scraper and
                       confirmed-lineup tests
frontend/src/i18n.tsx  EN/ES/PT translations + language context
frontend/src/three/    React Three Fiber blood-themed 3D hero scene
frontend/src/components/  Dashboard, group tables, interactive match analysis, and the
                       player analyzer (squad cards, SVG formation pitch + heatmap,
                       positional battles, lineup optimizer)
research.md            Source deep-research document
monteCarlo.py          Original single-file prediction pipeline (reference)
```

## Provenance

The dataset and modeling rationale derive from `research.md` (Phase 1–3:
infrastructure, climate, logistics, physiology, tactics, and the Dixon-Coles
mathematical foundation). The engine refactors and extends `monteCarlo.py`.
