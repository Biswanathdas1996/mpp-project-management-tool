# Project Management Accelerator (PMA)

Upload MS Project `.mpp` files repeatedly for a programme; every upload becomes an immutable, versioned
**snapshot** with an as-of date. PMA parses it (MPXJ), maps it to delivery tracks and milestones, computes
KPIs with a deterministic engine, renders an executive dashboard, tracks change across snapshots, and adds
AI insights through Ollama (self-hosted or cloud), with AI optional.

* **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Redis + RQ, MPXJ via JPype, S3/MinIO or Azure Blob.
* **Frontend:** Vue 3 + TypeScript (strict), Vite, Pinia, vue-i18n (EN/AR, RTL), ECharts.
* **Plan, architecture and decisions:** [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md). **Operations:** [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Quick start on Windows (one machine)

Prerequisites: Python 3.11+, Java 11+ and Node.js 20+.

| Script | What it does |
|---|---|
| `setup.bat` | Run once (or again after updates). Checks prerequisites, installs backend packages into `backend\.venv`, builds the UI, then asks for the admin email/password and whether to use a local Ollama model. Writes `backend\.env`. If a database already exists you can keep it or start fresh. |
| `start.bat` | Starts PMA in a minimised "PMA Server" window, waits until it is healthy and opens http://localhost:8000. Logs go to `backend\data\server.log`. If PMA is already running it just opens the browser. |
| `stop.bat` | Stops PMA. |

Set `PMA_PORT` before running `start.bat`/`stop.bat` to use a port other than 8000.

## Run in production (Docker Compose)

```bash
cp .env.example .env        # set PMA_SECRET_KEY, POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD, PMA_BOOTSTRAP_ADMIN_PASSWORD
docker compose up -d --build
docker compose --profile ai up -d    # optional: self-hosted Ollama, then: docker compose exec ollama ollama signin  (deepseek-v4.1-flash:cloud runs on Ollama Cloud)
```

Open `http://localhost:8080` and sign in with `PMA_BOOTSTRAP_ADMIN_EMAIL` / `PMA_BOOTSTRAP_ADMIN_PASSWORD`.
The API docs are at `/api/docs`. Services: `web` (nginx + SPA), `api` (FastAPI, runs migrations on start),
`worker` (RQ, parses files and computes KPIs), `postgres`, `redis`, `minio`, and optionally `ollama`.

## Run locally without Docker (single process)

Requirements: Python 3.11+, **Java 11+** (for MPXJ), Node 20+.

```bash
cd frontend && npm ci && npm run build && cd ..
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt     # (Linux/macOS: .venv/bin/pip)
PMA_BOOTSTRAP_ADMIN_PASSWORD=ChangeMe12345 .venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Open `http://localhost:8000`. This uses SQLite, local file storage and an in-process job queue (defaults);
the API also serves the built UI. For UI development run `npm run dev` in `frontend/` (port 5173,
proxies `/api` to port 8000).

To enable AI locally, install [Ollama](https://ollama.com), pull a model and set `PMA_AI_DEFAULT_MODE=self_hosted`
and `PMA_AI_DEFAULT_MODEL=<model>`, or switch it per organisation under **Administration → Organisation**.

## First use

1. **Programs → New program.**
2. **Snapshots:** drop one or more `.mpp` / MSPDI `.xml` files. The as-of date defaults to the project status date.
3. The first upload is profiled (by AI when enabled) and waits for the **Mapping wizard**: confirm the
   track rule, milestone rule, planned-to-date method and the KPI set, then approve.
4. The dashboard is built. Later uploads reuse the approved mapping automatically.

Sample schedules (genuine MS Project XML written by MPXJ, for UAT) can be generated with
`python backend/scripts/generate_sample_plans.py samples/`.

## Roles

| Role | Can |
|---|---|
| Admin | everything: programs, mapping approval, KPI set, users, branding, AI settings, alert rules, audit |
| PMO Editor | upload snapshots, manage risks/decisions/attention, review AI drafts, generate AI insights |
| Super Viewer | read all dashboards, drill-downs, change history; export PDF/Excel/PPTX; ask Q&A |

Platform administrators (the bootstrap admin) also manage tenants.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest tests -q -p no:faulthandler    # API end-to-end + units (real MPXJ parsing)
cd frontend && npm run build                                                # strict type-check + build
# UI smoke test against a running server (Playwright):
.venv/Scripts/python tests/ui_smoke.py http://127.0.0.1:8000 admin@pma.local <password> ../samples ./shots
```
