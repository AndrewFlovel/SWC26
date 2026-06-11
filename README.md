# SWC26 — Blood & Glory

**Interactive predictive analytics platform for the FIFA World Cup 2026**, built from
deep-research telemetry on the 48 qualified nations: Elo ratings, xG/xGA tactical
profiles, form momentum, injury attrition, transcontinental travel burden, altitude
hypoxia and WBGT heat stress.

Dark, blood-red, WebGL-powered. Drag the sliders — the engine recalculates in real time.

## Architecture

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  React 19 + TypeScript  │  HTTP  │  FastAPI (Python 3.10+)      │
│  Vite · R3F · Motion    │ ─────► │  numpy · scipy · pandas      │
│  3D hero, dashboard,    │  JSON  │  Elo + xG bivariate Poisson  │
│  live what-if sliders   │ ◄───── │  Dixon-Coles · Monte Carlo   │
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

## Quickstart

### Backend (port 8001)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8001
```

### Frontend (port 5173)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The frontend expects the API at
`http://localhost:8001` (override with `VITE_API_BASE`).

### Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

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
backend/app/engine/    Prediction engine (config, core math, predictor,
                       Monte Carlo simulators, MLE calibration, data loader)
backend/app/data/      48-team dataset + 16-venue catalogue (June 2026)
backend/tests/         Engine and API sanity tests
frontend/src/three/    React Three Fiber blood-themed 3D hero scene
frontend/src/components/  Dashboard, group tables, interactive match analysis
research.md            Source deep-research document
monteCarlo.py          Original single-file prediction pipeline (reference)
```

## Provenance

The dataset and modeling rationale derive from `research.md` (Phase 1–3:
infrastructure, climate, logistics, physiology, tactics, and the Dixon-Coles
mathematical foundation). The engine refactors and extends `monteCarlo.py`.
