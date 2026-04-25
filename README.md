# trace911

Real-time emergency call intelligence. Audio enhancement (ai-coustics) + STT
(Gradium) + live incident extraction, surfaced to a single operator workspace.

The operator is always in control — the AI extracts and suggests; only the
operator can `confirm`.

## Repo layout

```
trace911/
├── backend/    FastAPI + SQLite. Ingestion → enhancement → STT → extraction → WS
├── frontend/   Drop the Lovable React app here (Vite + React + JS)
├── calls/      Standalone CLI scripts (dev tooling — not part of the live pipeline)
│               clean_audio.py       MP3 → 16kHz WAV → ai-coustics (writes _cleaned.wav)
│               stream_transcribe.py WAV → Gradium STT (writes transcript.txt)
└── docs/       app-spec.md · api-contracts.md · websocket-events.md · metrics.md · data-model.md
```

`calls/` was the original prototype. The same logic now lives in `backend/app/services/` and runs
as part of the HTTP pipeline (`POST /audio` → enhance → transcribe → WebSocket push). Use the
scripts directly to test audio or STT in isolation without starting the full backend.

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

After `make install`, open `backend/.env` and fill in `AIC_SDK_LICENSE` and
`GRADIUM_API_KEY` at minimum. `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` will be
needed once extraction is implemented.

Until the Lovable export lands in `frontend/`, `make dev` runs the backend
only and prints a note. The frontend talks to `http://localhost:8000` (REST)
and `ws://localhost:8000/ws/calls/{call_id}` (live stream).

---

## Architecture in one picture

```
                 ┌──── REST /api/calls/* ──────────────────────────────┐
 Operator UI ────┤                                                     │
 (Lovable React) └──── WS /ws/calls/{id}  ◀── push  /  recv ─────────►│
                         │ audio_frame msg                             │
                         ▼                                             │
   audio in ──► [audio_enhancement] ──► [stt] ──► [extraction 🚧] ──► [operator_assist 🚧]
   (REST POST     ai-coustics           Gradium      LLM               rules + LLM polish
    or WS frame)       │                   │              │                   │
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

**Audio can enter two ways:**
- **Upload** — `POST /api/calls/{id}/audio` with a WAV file. Returns 202 immediately; enhancement → transcription run as a `BackgroundTask`.
- **Live** — send `{"type": "audio_frame", "payload": {"audio": "<base64 WAV>"}}` over the WebSocket. Same pipeline fires per frame.

**🚧 = not yet wired.** Enhancement and STT are live. Extraction and operator assist raise `NotImplementedError` — they are the next two pieces to implement.

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
| `Call`, `TranscriptSegment`, `IncidentField` | `models/orm.py` | SQLAlchemy tables — the DB. |
| `CallCreateRequest` | `schemas/call.py` | `source: "upload" \| "live"` |
| `CallCreateResponse` | `schemas/call.py` | `call_id`, `started_at`, `ws_url` |
| `CallSnapshot` | `schemas/call.py` | Full state: `transcript`, `incident`, `metrics`, `assist` |
| `CallSummary` | `schemas/call.py` | `narrative`, `incident`, `unconfirmed: list[str]`, `evidence` |
| `IncidentCard` | `schemas/incident.py` | 11 `IncidentField` objects + `field_coverage`, `confirmed_coverage`, `dispatch_readiness` |
| `IncidentField.status` | `schemas/incident.py` | `missing` \| `heard` \| `suggested` \| `confirmed_by_operator` \| `uncertain` \| `contradicted` |
| `FIELD_NAMES` (the 11 tracked fields) | `schemas/incident.py` | `incident_type`, `location`, `breathing`, `consciousness`, `number_of_people`, `injury_status`, `immediate_danger`, `weapons`, `fire_or_smoke`, `caller_callback`, `access_instructions` |
| `MetricsSnapshot` | `schemas/metrics.py` | 5 sub-objects: `audio` (noise/lift), `vad` (turns/ratio), `transcript` (health/revisions), `incident` (coverage/timing), `assist` (suggestions/overrides) |
| `OperatorAssist` | `schemas/call.py` | `next_question: OperatorAssistSuggestion`, `critical_missing: list[str]`, `high_risk_unconfirmed: list[HighRiskUnconfirmed]` |
| `TranscriptSegment` | `schemas/transcript.py` | `id`, `t_start`, `t_end`, `speaker`, `text`, `is_final`, `confidence`, `entities` |
| `broker` | `pubsub.py` | `subscribe(call_id)`, `publish(call_id, type, payload)`, `t_for(call_id)`. Queue size 256 — slow consumers get events dropped. |
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

**Services**

- `services.audio_enhancement.enhance_and_meter(call_id, wav_bytes)` ✅ — ai-coustics SDK in a thread-pool executor; emits `audio_window` + `metrics` events. Falls back to raw audio if the SDK is unavailable.
- `services.stt.stream_transcribe(call_id, wav_bytes)` ✅ — Gradium WS; resamples to 24kHz, streams PCM, upserts partial→final segments, publishes `transcript` events.
- `services.extraction.update_from_transcript(incident, transcript)` 🚧 — LLM → call `repository.incident.upsert_extracted` per field. **Not yet implemented.**
- `services.extraction.build_summary(transcript, incident)` 🚧 — narrative for the dispatch handoff. **Not yet implemented.**
- `services.operator_assist.compute_assist(incident, transcript)` 🚧 → `OperatorAssist` (next question + critical missing). **Not yet implemented.**

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
| `GET`  | `/health` | Health probe. Returns `{"status": "ok"}`. |
| `POST` | `/api/calls` | Start a call (`source: "upload"\|"live"`). Returns `call_id`, `started_at`, `ws_url`. |
| `GET`  | `/api/calls/{id}` | Full `CallSnapshot` (transcript + incident + metrics + assist). |
| `POST` | `/api/calls/{id}/audio` | Upload a WAV. Returns 202 immediately; enhancement → transcription run as a background task. |
| `PATCH`| `/api/calls/{id}/incident` | Operator confirms / overrides fields. Publishes `incident` WS event. |
| `POST` | `/api/calls/{id}/end` | End call → returns `CallSummary`. Publishes `call_ended` WS event. |
| `GET`  | `/api/calls/{id}/summary` | Dispatch handoff (`CallSummary`). |
| `GET`  | `/api/calls/{id}/metrics` | Latest `MetricsSnapshot`. |
| `WS`   | `/ws/calls/{id}` | **Bidirectional.** On connect: server pushes `snapshot` (full state replay). Ongoing server→client events: `transcript`, `incident`, `metrics`, `audio_window`, `assist`, `alert`, `call_ended`. Client→server messages: `audio_frame` (base64 WAV → triggers pipeline), `operator_event` (routed to extraction/assist once implemented). |

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

- **Audio + metrics:** ✅ Done. `services/audio_enhancement.py` is wired and live.
- **STT:** ✅ Done. `services/stt.py` streams to Gradium; set `GRADIUM_API_KEY` in `.env`.
- **Extraction:** 🚧 **Up next.** `services/extraction.py` — LLM over rolling transcript → field updates via `repository.incident.upsert_extracted`. Called automatically after each final transcript segment once implemented.
- **Assist:** 🚧 `services/operator_assist.py`. Priority list is already in the file — start with deterministic rules, then layer LLM polish.
- **Frontend:** drop the Lovable export into `frontend/`. Wiring snippet in `frontend/README.md`.
