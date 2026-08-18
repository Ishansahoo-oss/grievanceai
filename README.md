# GrievanceAI Backend

Phase 2 adds the mocked AI client and `POST /intake/web`.

## Start PostgreSQL + pgvector

```powershell
docker run --name grievanceai-db `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=grievanceai `
  -p 5432:5432 `
  -d pgvector/pgvector:pg16
```

If the container already exists:

```powershell
docker start grievanceai-db
```

## Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Start the API:

```powershell
uvicorn app.main:app --reload
```

## Test health

```powershell
curl.exe http://localhost:8000/health
```

Expected:

```json
{"ok":true}
```

## Test web intake

Use `curl.exe` in PowerShell so it invokes real curl rather than PowerShell's `Invoke-WebRequest` alias:

```powershell
curl.exe -X POST http://localhost:8000/intake/web `
  -H "Content-Type: application/json" `
  -d '{"description":"There has been no water supply in our area for 3 days","address":"Bengaluru","language":"en"}'
```

Expected shape:

```json
{
  "tracking_id": "GRV-xxxxx",
  "status": "new",
  "category": "water_supply",
  "priority": "high",
  "department": "Water Board",
  "summary": "Water supply disruption reported.",
  "merged": false
}
```

Submit the same complaint again. The second request should normally return the existing tracking ID with:

```json
{"tracking_id":"GRV-xxxxx","merged":true}
```

The mock embedding is deterministic, but unrelated complaints will not necessarily be close enough to merge. This is only a Phase 2 mock; the real embedding service will replace it later.

## Important

Run the seed script before testing intake because department routing expects the five departments to exist. The seed endpoint/script is part of the next phase.
