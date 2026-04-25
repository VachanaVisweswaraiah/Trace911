# trace911

Real-time emergency call intelligence. Audio enhancement (ai-coustics) + STT
(Gladia) + live incident extraction, surfaced to a single operator workspace.

The operator is always in control — the AI extracts and suggests; only the
operator can `confirm`.

## Repo layout

```
trace911/
├── backend/    FastAPI + SQLite. Ingestion → enhancement → STT → extraction → WS
├── frontend/   Drop the Lovable React app here (Vite + React + JS)
└── docs/       app-spec.md · api-contracts.md · websocket-events.md · metrics.md · data-model.md
```

## Quickstart

```bash
make install     # backend venv + deps; frontend npm install (if present)
make dev         # backend + frontend together. Ctrl+C stops both.
```

→ backend  http://localhost:8000  (OpenAPI at `/docs`)
→ frontend http://localhost:5173

Other useful targets: `make backend`, `make frontend`, `make clean`, `make help`.

If you prefer npm (colored multiplexed output):

```bash
npm install && npm run install:all
npm run dev
```

Until the Lovable export lands in `frontend/`, `make dev` runs the backend
only and prints a note. The frontend talks to `http://localhost:8000` (REST)
and `ws://localhost:8000/ws/calls/{call_id}` (live stream).

---

## Architecture in one picture

```
                 ┌──── REST /api/calls/* ──────────────┐
 Operator UI ────┤                                     │
 (Lovable React) └──── WS /ws/calls/{id}  ◀── push ────│
                                                       │
                                                       ▼
   audio in ──► [audio_enhancement] ──► [stt] ──► [extraction] ──► [operator_assist]
                  ai-coustics            Gladia      LLM            rules + LLM polish
                       │                   │           │                   │
                       └──► metrics ◄──────┴──► transcript          incident card
                                                      │                    │
                                                      ▼                    ▼
                                              ┌────────── SQLite ──────────┐
                                              │ calls / segments / fields  │
                                              └─────────────┬──────────────┘
                                                            │
                                                  app.pubsub.broker  (in-process)
                                                            │
                                                            ▼
                                                  WebSocket fan-out
```

**Two channels, one source of truth.** State lives in SQLite. The broker is
just a notification bus — slow WS clients can drop events and recover by
re-fetching the snapshot via `GET /api/calls/{id}`.

---

## Backend layout (the bits you'll touch)

```
backend/app/
├── main.py            FastAPI app, lifespan → init_db
├── config.py          Settings (env + .env)
├── db.py              async engine, SessionLocal, get_session, init_db
├── pubsub.py          in-process broker for WS fan-out
├── api/               HTTP + WS endpoints (thin — just orchestration)
├── models/orm.py      SQLAlchemy tables
├── schemas/           Pydantic DTOs (the API surface)
├── repository/        all DB reads/writes live here
└── services/          the four "agents" (audio, stt, extraction, assist)
```

### Key objects

| Object | Where | What it is |
| --- | --- | --- |
| `Call`, `TranscriptSegment`, `IncidentField` | `models/orm.py` | SQLAlchemy tables. The DB. |
| `IncidentCard`, `TranscriptSegment`, `MetricsSnapshot`, `OperatorAssist`, `CallSnapshot` | `schemas/` | Pydantic DTOs. The API surface. |
| `IncidentField.status` | `schemas/incident.py` | `missing` \| `heard` \| `suggested` \| `confirmed_by_operator` \| `uncertain` \| `contradicted` |
| `FIELD_NAMES` (the 11 tracked fields) | `schemas/incident.py` | `incident_type`, `location`, `breathing`, `consciousness`, … |
| `broker` | `pubsub.py` | `subscribe(call_id)`, `publish(call_id, type, payload)`, `t_for(call_id)` |
| `SessionLocal` / `get_session` | `db.py` | Async session factory + FastAPI dep |

### Key functions (where to plug in)

**Repository (DB I/O — call these from services and APIs)**

- `repository.calls.create(db, source)` — new call + seeds 11 missing fields.
- `repository.calls.snapshot(db, call_id)` → `CallSnapshot` for REST + WS replay.
- `repository.calls.update_metrics(db, call_id, MetricsSnapshot)` — services call this every ~1s.
- `repository.transcript.upsert(db, call_id, TranscriptSegment)` — partial→final updates same id.
- `repository.incident.upsert_extracted(db, call_id, field, value, status, confidence, source_segment_ids, t_now)` — extraction writes here. **Never overwrites `confirmed_by_operator`.**
- `repository.incident.patch(db, call_id, IncidentPatchRequest, t_now)` — operator confirmations.
- `repository.incident.assemble_card(rows)` — pure function, also computes `field_coverage`, `confirmed_coverage`, `dispatch_readiness`.

**Services (stubbed — pick one and implement)**

- `services.audio_enhancement.enhance_and_meter(call_id, pcm_bytes, sample_rate)` — run ai-coustics, emit `audio_window` events with raw vs enhanced metrics.
- `services.stt.stream_transcribe(call_id)` — Gladia WS, push enhanced PCM, `repository.transcript.upsert(...)` + `broker.publish('transcript', ...)`.
- `services.extraction.update_from_transcript(incident, transcript)` — LLM → call `repository.incident.upsert_extracted` per field.
- `services.extraction.build_summary(transcript, incident)` — narrative for the handoff.
- `services.operator_assist.compute_assist(incident, transcript)` → `OperatorAssist` (next question + critical missing).

### Standard flow when a service produces something

```python
async with SessionLocal() as db:
    await repository.transcript.upsert(db, call_id, segment)
    await db.commit()
await broker.publish(call_id, "transcript", segment.model_dump(mode="json"))
```

DB first, then broadcast. UI receives the WS event and re-renders.

---

## API at a glance

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/calls` | Start a call. Returns `call_id` + `ws_url`. |
| `GET`  | `/api/calls/{id}` | Full `CallSnapshot` (transcript + incident + metrics + assist). |
| `POST` | `/api/calls/{id}/audio` | Upload mode: post a WAV. |
| `PATCH`| `/api/calls/{id}/incident` | Operator confirms / overrides fields. |
| `POST` | `/api/calls/{id}/end` | End call → returns `CallSummary`. |
| `GET`  | `/api/calls/{id}/summary` | Dispatch handoff. |
| `GET`  | `/api/calls/{id}/metrics` | Latest `MetricsSnapshot`. |
| `WS`   | `/ws/calls/{id}` | Live: server pushes `transcript`, `incident`, `metrics`, `audio_window`, `assist`, `alert`, `call_ended`. |

Full payloads in `docs/api-contracts.md`. WS event catalog in `docs/websocket-events.md`.

---

## Database

SQLite (`sqlite+aiosqlite`). Three tables, schema in `docs/data-model.md`:

- `calls` — id, source, started_at, ended_at, `metrics_json`, `assist_json`
- `transcript_segments` — keyed by stable segment id (partial→final upsert)
- `incident_fields` — composite PK `(call_id, field)`, one row per tracked field

Tables auto-create on startup. Default DB path: `./trace911.db` (gitignored).

---

## Conventions

- **ORM stays in `repository/`.** APIs and services consume Pydantic DTOs.
- **One session per request** via `Depends(get_session)`. Background tasks open
  `async with SessionLocal()` themselves.
- **Operator wins.** `upsert_extracted` refuses to overwrite a row that's
  `confirmed_by_operator`. The only path out of that state is `PATCH /incident`.
- **Time `t`** in events is seconds since `call.started_at` — get it via
  `broker.t_for(call_id)`.
- **DB → broker, in that order.** Persist first, then publish.

---

## Where to start (per teammate)

- **Audio + metrics:** `services/audio_enhancement.py` + `repository.calls.update_metrics`. See `docs/metrics.md` for the six metrics; ai-coustics setup pattern is in the docstring.
- **STT:** `services/stt.py` + `repository.transcript.upsert`. Stream Gladia, push partial→final segments.
- **Extraction:** `services/extraction.py` + `repository.incident.upsert_extracted`. LLM over rolling transcript → field updates with confidence.
- **Assist:** `services/operator_assist.py`. Priority list is already in the file — start with deterministic rules.
- **Frontend:** drop the Lovable export into `frontend/`. Wiring snippet in `frontend/README.md`.
