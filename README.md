# GrievanceAI Backend

FastAPI backend for an AI-based civic grievance system. Citizens report
complaints via web or WhatsApp; an AI layer classifies and routes them
to city departments; the system tracks them through resolution with
SLA-based escalation and supports multi-department complaint splitting.

Stack: Python (FastAPI), PostgreSQL + pgvector, SQLAlchemy, Pydantic,
APScheduler.

## Local development

### 1. Start Postgres with pgvector

```bash
docker run --name grievance-pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=grievanceai \
  -p 5432:5432 \
  -d pgvector/pgvector:pg16
```

### 2. Set up your environment

```bash
cp .env.example .env
# edit .env if your DATABASE_URL differs from the default
```

### 3. Install dependencies

Use **Python 3.12** — some pinned dependencies don't yet have prebuilt
wheels for very new Python releases (3.13/3.14), which causes slow,
error-prone source builds on Windows especially.

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Seed the departments

```bash
python -m app.seed
```

### 5. Run the server

```bash
uvicorn app.main:app --reload --reload-dir app
```

`--reload-dir app` scopes the file-watcher to your own code — without
it, uvicorn also watches `venv/`, which triggers constant unnecessary
restarts.

### 6. Verify

```bash
curl http://localhost:8000/health
# {"ok":true}
```

## Deploying to Railway

Railway is the easiest option here since it has ready-made templates
with pgvector already compiled in — no custom Dockerfile needed.

### 1. Push your code to GitHub

Railway deploys straight from a GitHub repo.

### 2. Create the database

In your Railway project, deploy one of Railway's pgvector-enabled
Postgres templates (search "pgvector" in the Railway template
directory — e.g. "Postgres with pgVector Engine" or "Deploy PgVector").
Avoid the plain built-in Postgres plugin — it does **not** have the
`vector` extension available.

### 3. Create the app service

- **New Service → Deploy from GitHub repo** → select this repo
- Railway auto-detects Python via Nixpacks. This repo includes
  `railway.json`, `Procfile`, and `runtime.txt` to pin the Python
  version and start command explicitly, so no manual build/start
  configuration should be needed.

### 4. Set environment variables on the app service

| Variable | Value |
|---|---|
| `DATABASE_URL` | Reference your Postgres service's connection string (Railway lets you do this via a variable reference, e.g. `${{Postgres.DATABASE_URL}}`) |
| `GEMINI_API_KEY` | Real key once the AI service is wired up; any placeholder works for now since `ai_client.py` is currently mocked |
| `WHATSAPP_TOKEN` | Same — placeholder is fine until the WhatsApp integration goes live |

### 5. Deploy

Railway builds and deploys automatically. On first boot, `init_db()`
runs `CREATE EXTENSION IF NOT EXISTS vector` and creates all tables —
no manual migration step needed.

### 6. Seed departments on the deployed instance

Easiest via the Railway CLI:

```bash
railway run python -m app.seed
```

### 7. Verify

```bash
curl https://<your-app>.up.railway.app/health
# {"ok":true}
```

Share this URL with your frontend/AI teammates so they can start
integrating against a live backend instead of `localhost`.

## Deploying to Render (alternative)

Render doesn't have a pgvector-enabled Postgres template out of the
box, so you'd need to run Postgres yourself via Render's "Private
Service" with the `pgvector/pgvector:pg16` Docker image, or use an
external managed Postgres that supports pgvector (e.g. Supabase,
Neon's paid tier, or your own Railway-hosted Postgres). For the web
service itself, point Render at this repo with:

- **Build command**: `pip install -r requirements.txt`
- **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Same environment variables as above.

## Project structure

```
app/
  main.py          FastAPI app, CORS, error handlers, startup/shutdown
  config.py        Settings loaded from .env
  db.py            Engine/session, init_db() (extension + table creation)
  models.py        SQLAlchemy models
  schemas.py       Pydantic request/response models
  ai_client.py     MOCK AI functions — swap for the real ai_service package
  notifications.py MOCK notification dispatch
  scheduler.py     APScheduler job: SLA breach auto-escalation
  seed.py          Seeds the 5 departments
  routers/
    intake.py      POST /intake/web, POST /intake/whatsapp/webhook
    citizen.py     GET /grievance/{tracking_id}/status, POST .../verify
    admin.py       GET /admin/queue, PATCH/escalate endpoints
```

## Known mock/placeholder areas

These are intentionally mocked for now and documented with `TODO`
comments at each call site — swap them for real implementations
without needing to change any calling code, since the function
signatures match the intended real contracts:

- `ai_client.classify_complaint` — category/priority/confidence
  classification, plus a naive regex-based location extractor as a
  geotagging placeholder
- `ai_client.embed_text` — 768-dim embedding generation
- `ai_client.split_departments` — multi-department detection (contract
  shape not yet confirmed with the AI team — see comment in the file)
- `ai_client.transcribe_audio` — defined but not yet wired into the
  WhatsApp webhook (text messages only for now)
- `notifications.send_notification` — logs to `notifications_log`
  instead of actually sending via WhatsApp/SMS/email
