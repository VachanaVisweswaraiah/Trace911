# API Contracts

Base URL: `http://localhost:8000`
WebSocket base: `ws://localhost:8000`

All payloads are JSON unless noted. Times are ISO-8601 UTC; offsets within a call
(`t`) are seconds-since-call-start as floats.

---

## REST

### `POST /api/calls`
Start a new call session.

**Request**
```json
{ "source": "upload" }    // "upload" | "live"
```

**Response 201**
```json
{
  "call_id": "call_01HK...",
  "started_at": "2026-04-25T12:00:00Z",
  "ws_url": "/ws/calls/call_01HK..."
}
```

### `POST /api/calls/{call_id}/audio`
Upload an audio chunk (or full file in upload mode). `multipart/form-data` with
field `audio` (WAV/PCM 16k preferred). For `live` calls, prefer the WS audio
channel instead (see below).

**Response 202** `{ "accepted_bytes": 123456 }`

### `POST /api/calls/{call_id}/end`
Mark the call ended. Triggers final summary generation.

**Response 200** → same shape as `GET /api/calls/{call_id}/summary`.

### `GET /api/calls/{call_id}`
Snapshot of current call state (transcript, incident card, latest metrics).

**Response 200**
```json
{
  "call_id": "call_...",
  "started_at": "...",
  "ended_at": null,
  "transcript": [ /* TranscriptSegment[] */ ],
  "incident": { /* IncidentCard */ },
  "metrics": { /* MetricsSnapshot */ },
  "assist": { /* OperatorAssist */ }
}
```

### `GET /api/calls/{call_id}/summary`
Dispatch handoff. Available after `end`.

```json
{
  "call_id": "call_...",
  "narrative": "Caller reports one adult male unconscious near ...",
  "incident": { /* IncidentCard */ },
  "unconfirmed": ["breathing", "exact_location"],
  "evidence": [
    { "field": "breathing", "transcript_segment_id": "seg_12", "t": 28.4 }
  ]
}
```

### `PATCH /api/calls/{call_id}/incident`
Operator confirmations / overrides.

**Request**
```json
{
  "updates": [
    { "field": "breathing", "value": "not breathing", "status": "confirmed_by_operator" },
    { "field": "location",  "value": "Kottbusser Tor 1, Berlin", "status": "confirmed_by_operator" }
  ]
}
```

**Response 200** → updated `IncidentCard`.

### `POST /api/calls/{call_id}/assist/feedback`
Track operator interaction with suggestions (drives the assist-quality metric).

```json
{ "suggestion_id": "sug_7", "action": "used" }   // used | dismissed | edited
```

---

## WebSocket — `/ws/calls/{call_id}`

Bi-directional. Server pushes live state; client may push audio frames in `live`
mode.

### Server → client events
Every message: `{ "type": "...", "t": 4.21, "payload": { ... } }`.

| `type`             | `payload`                          |
| ------------------ | ---------------------------------- |
| `transcript`       | `TranscriptSegment` (partial or final) |
| `incident`         | `IncidentCard` (full snapshot, debounced) |
| `metrics`          | `MetricsSnapshot`                  |
| `assist`           | `OperatorAssist`                   |
| `alert`            | `{ "level": "info\|warn\|critical", "message": "..." }` |
| `audio_window`     | per-window audio metrics (see `metrics.md`) |
| `call_ended`       | `{ "summary_url": "/api/calls/.../summary" }` |

### Client → server messages
| `type`           | `payload`                              |
| ---------------- | -------------------------------------- |
| `audio_frame`    | base64 PCM16 mono 16kHz, ~20ms frames  |
| `operator_event` | `{ "kind": "confirm\|override\|ask",  "field": "...", "value": "..." }` |

---

## Shared types

### `TranscriptSegment`
```json
{
  "id": "seg_12",
  "t_start": 27.8,
  "t_end": 30.1,
  "speaker": "caller",            // caller | bystander | operator | unknown
  "text": "I think he's not breathing",
  "is_final": true,
  "confidence": 0.71,
  "entities": [
    { "type": "symptom", "text": "not breathing", "field": "breathing" }
  ]
}
```

### `IncidentField`
```json
{
  "field": "breathing",
  "value": "possibly not breathing",
  "status": "heard",              // missing | heard | suggested | confirmed_by_operator | uncertain | contradicted
  "confidence": 0.62,
  "source_segment_ids": ["seg_12"],
  "updated_at_t": 28.9
}
```

### `IncidentCard`
```json
{
  "incident_type": { "field": "incident_type", "value": "medical", "status": "suggested", ... },
  "location":      { ... },
  "number_of_people": { ... },
  "injury_status": { ... },
  "consciousness": { ... },
  "breathing":    { ... },
  "immediate_danger": { ... },
  "weapons":      { ... },
  "fire_or_smoke":{ ... },
  "caller_callback": { ... },
  "access_instructions": { ... },
  "field_coverage": 0.64,
  "confirmed_coverage": 0.36,
  "dispatch_readiness": 0.71
}
```

### `OperatorAssist`
```json
{
  "next_question": {
    "id": "sug_7",
    "text": "Is the person breathing?",
    "reason": "breathing field is heard but unconfirmed"
  },
  "critical_missing": ["breathing", "exact_location"],
  "high_risk_unconfirmed": [
    { "field": "breathing", "quote": "I think he's not breathing", "t": 28.9 }
  ]
}
```

### `MetricsSnapshot`
```json
{
  "audio": {
    "noise_severity": "high",         // low | medium | high | severe
    "enhancement_lift_db": 17.3,
    "speech_preservation_pct": 92,
    "model": "QUAIL_VF_L",
    "enhancement_level": 0.8
  },
  "vad": {
    "speech_activity_ratio": 0.61,
    "false_start_count": 2,
    "avg_end_of_turn_ms": 420,
    "turns": 14
  },
  "transcript": {
    "health_score": 88,
    "low_confidence_words": 6,
    "revisions": 3
  },
  "incident": {
    "field_coverage": 0.64,
    "confirmed_coverage": 0.36,
    "dispatch_readiness": 0.71,
    "time_to_first_location_s": 8.4,
    "time_to_incident_type_s": 12.1
  },
  "assist": {
    "suggestions_shown": 5,
    "suggestions_used": 3,
    "operator_overrides": 1
  }
}
```
