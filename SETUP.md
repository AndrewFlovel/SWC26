# SWC26 — Setup Instructions

> 🌐 **English** · [Español](SETUP.es.md)

Two ways to run the platform: **Docker** (recommended, zero local toolchain) or
**local development** (hot reload for both sides).

---

## Option A — Docker (recommended)

### Prerequisites

- Docker Engine 24+ with the Compose plugin (`docker compose version`)

### Run

```bash
git clone https://github.com/AndrewFlovel/SWC26.git
cd SWC26
docker compose up --build
```

| Service | URL | Notes |
| --- | --- | --- |
| Frontend | <http://localhost:5173> | nginx serves the built app and proxies `/api` to the backend |
| Backend | <http://localhost:8001> | FastAPI + uvicorn; OpenAPI docs at `/docs` |

Stop with `Ctrl+C`, or `docker compose down` if started with `-d`.

### How the containers talk

The frontend image is built with `VITE_API_BASE=""`, so the app issues relative
`/api/*` requests to its own origin. nginx (see `frontend/nginx.conf`) proxies
those to `http://backend:8001` over the Compose network — no CORS involved.

---

## Option B — Local development

### Prerequisites

- Python **3.10+** (3.12+ recommended)
- Node.js **20+** and npm
- A free port **8001** (backend) and **5173** (frontend)

### 1. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8001
```

Sanity check:

```bash
curl http://localhost:8001/api/health
# {"status":"ok","teams":48}
```

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. In dev mode the app calls the backend directly at
`http://localhost:8001` (CORS for the Vite origin is pre-configured). To point
at a different engine, set `VITE_API_BASE`:

```bash
VITE_API_BASE=http://my-server:9000 npm run dev
```

### 3. Tests

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

Expected: `64 passed` (prediction engine, results tracking, player analyzer and
player scraper).

### 4. Production build of the frontend (optional)

```bash
cd frontend
npm run build      # outputs to frontend/dist
npm run preview    # serves the production bundle locally
```

---

## Using the platform

1. **Pick a group** (A–L). The match cards show venue, matchday, and environmental
   badges (⛰ altitude ≥ 1,000 m, 🔥 WBGT heat burden, ★ host nation).
2. **Click a match** to open the analysis modal.
3. **Drag the sliders** — xG form, injury impact, altitude, heat, xG/Elo blend,
   host advantage. Every change triggers a debounced re-prediction (~250 ms):
   win/draw/loss bars, the most probable scorelines and the exact-score heatmap
   update live.
4. **Open a deep player analysis** with the "⚔ Deep player analysis" button in the
   match modal. The overlay scrapes both squads (with a reference-squad fallback) and
   surfaces squad cards with Player Performance Scores, an SVG formation pitch with a
   3×3 dominance heatmap, the positional-battles table, and a best-XI optimizer. **All
   48 teams ship with a reference squad**, so every fixture works — Spain, Uruguay,
   Argentina and Austria are hand-curated seed squads (try Uruguay vs Spain in Group H,
   or Argentina vs Austria in Group J); the rest are committed scraped/synthetic
   references. To refresh them from FBref, run
   `python -m scripts.bootstrap_squads` from `backend/` (add `--force` to overwrite
   existing files, `--team <Name>` for a single team). `GET /api/players` reports the
   per-team `source` and player count.
5. **Switch language** (EN/ES/PT) with the selector at the top right. The choice
   persists in `localStorage`; the first visit auto-detects the browser language.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `address already in use` on 8001/5173 | Another process owns the port. Stop it, or change the mapping in `docker-compose.yml` / `--port` flags. |
| Frontend shows "Engine unreachable" | The backend isn't running, or `VITE_API_BASE` points to the wrong host. Verify `curl localhost:8001/api/health`. |
| Black background but no 3D scene | WebGL is unavailable in your browser/GPU; the app falls back to a static gradient by design. |
| `docker compose` rebuild doesn't pick changes | Use `docker compose up --build` (the `--build` flag forces image rebuild). |
