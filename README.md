# SWC26 — Blood & Glory

> 🌐 **English** · [Español](README.es.md) · Setup guides: [EN](SETUP.md) / [ES](SETUP.es.md)

**Interactive predictive analytics platform for the FIFA World Cup 2026**, built from
deep-research telemetry on the 48 qualified nations: Elo ratings, xG/xGA tactical
profiles, form momentum, injury attrition, transcontinental travel burden, altitude
hypoxia and WBGT heat stress.

Dark, blood-red, WebGL-powered. Drag the sliders — the engine recalculates in real time.
Open any fixture for a player-by-player breakdown: squad ratings, formation matchups and
a best-XI optimizer. The interface is available in **English, Spanish and Portuguese**
(selector at the top right; it also auto-detects your browser language).

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
FBref's server-rendered stat tables, with bundled seed squads as the reliable
fallback (Selenium is reserved for confirmed match-day lineups). Each player gets a
**Player Performance Score (PPS)**: a role-weighted blend of attacking, defensive and
physical facets, each normalized against fixed elite-football reference ranges so
scores are absolute and comparable across squads.

From two XIs the engine derives the matchup geometrically — any formation pair works,
no hand-coded tables:

- **PMS** — positional battle scores (each attacker vs the defenders covering them)
- **FSI** — a single, symmetric Formation Strength Index for the matchup
- **PIS** — pressing-vs-ball-progression mismatch between the sides
- **PDH** — a 3×3 pitch dominance heatmap
- **Optimal XI** — the best lineup for a formation against a given opponent, via the
  Hungarian assignment (`scipy.optimize.linear_sum_assignment`), with ranked alternates

The UI opens a full-screen overlay (Squad · Formation · Battles · Optimizer) with an
SVG pitch, PPS-colored player nodes and the dominance heatmap. Seed squads ship for
Spain, Uruguay, Argentina and Austria (fixtures Uruguay–Spain and Argentina–Austria);
other fixtures degrade gracefully until their squads are scraped or seeded.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/players/{slug}` | Scored squad (PPS) for a team — seed or scraped |
| POST | `/api/scrape/players` | Scrape both squads of a fixture (FBref, seed fallback) |
| POST | `/api/analyze/lineup` | FSI, pressing, positional battles and 3×3 dominance heatmap for two XIs |
| POST | `/api/analyze/optimal-xi` | Best XI (Hungarian) vs an opponent — top-3 candidates |
| GET | `/api/formations` | Formation slot coordinates (4-3-3, 4-2-3-1, 4-4-2, 3-5-2) |

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
backend/app/services/  Results store + metrics replay, day scraper, and the squad
                       cache + hybrid FBref player scraper
backend/app/data/      48-team dataset + 16-venue catalogue; data/players/ holds
                       seed squads (Spain, Uruguay, Argentina, Austria)
backend/tests/         Engine, results and player-analyzer tests
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
