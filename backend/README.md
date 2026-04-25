# trace911 backend

FastAPI + SQLAlchemy 2.0 (async) + SQLite (aiosqlite). Single-process.

```
app/
├── main.py                FastAPI app, CORS, lifespan → init_db, route mount
├── config.py              Settings (pydantic-settings)
├── db.py                  Async engine, sessionmaker, get_session dep, init_db
├── pubsub.py              In-process broker for WebSocket fan-out (not persisted)
├── api/
│   ├── calls.py           REST: start/end/snapshot/audio upload
│   ├── incidents.py       REST: PATCH incident updates
│   ├── metrics.py         REST: metrics snapshot fetch
│   └── ws.py              WebSocket endpoint
├── models/
│   └── orm.py             SQLAlchemy tables (Call, TranscriptSegment, IncidentField)
├── schemas/               Pydantic API DTOs (mirror docs/api-contracts.md)
├── repository/
│   ├── calls.py           CRUD + snapshot assembly
│   ├── transcript.py      Upsert by segment id (partial→final)
│   └── incident.py        Per-field upsert, card assembly, coverage math
└── services/
    ├── audio_enhancement.py   ai-coustics wrapper + raw/enhanced taps
    ├── stt.py                 Gladia streaming client
    ├── extraction.py          LLM → IncidentCard fields (via repository.incident)
    └── operator_assist.py     Next-question + alert logic
```

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

OpenAPI: `http://localhost:8000/docs`.

## Database

- SQLite via `sqlite+aiosqlite`. Path set by `DATABASE_URL` (default `./trace911.db`).
- Tables auto-created on startup via `Base.metadata.create_all` (FastAPI lifespan).
  Swap in Alembic if the schema starts to move.
- Three tables:
  - `calls` — id, source, started_at, ended_at, `metrics_json`, `assist_json`
  - `transcript_segments` — keyed by segment id; partial→final is an upsert
  - `incident_fields` — composite PK `(call_id, field)`, one row per tracked field

The repository layer (`app.repository`) is the only thing that touches ORM
models. API + services consume Pydantic schemas.

## Sessions

- `get_session` is the FastAPI dependency. Yields one `AsyncSession` per request,
  commits on success, rolls back on exception.
- For background work (services running outside a request), open `SessionLocal()`
  directly in an `async with` block.

## Pub/sub vs persistence

The DB stores state. The WebSocket needs *push notifications* on top of that —
that's what `app.pubsub` is for: an in-process broker keyed by `call_id`. Slow
subscribers get dropped events; clients recover by re-fetching the snapshot via
`GET /api/calls/{id}`.
