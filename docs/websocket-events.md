# WebSocket Event Reference

`/ws/calls/{call_id}` — JSON frames, `{ "type", "t", "payload" }`.

## Server → client

```jsonc
// New transcript segment (partial first, then final with same id)
{ "type": "transcript", "t": 12.4, "payload": { /* TranscriptSegment */ } }

// Full incident card snapshot (debounced, ~250ms)
{ "type": "incident", "t": 13.0, "payload": { /* IncidentCard */ } }

// Metrics snapshot (every ~1s)
{ "type": "metrics", "t": 13.0, "payload": { /* MetricsSnapshot */ } }

// Per-window audio metrics (every 1s)
{ "type": "audio_window", "t": 13.0, "payload": {
    "window_ms": 1000,
    "raw":      { "rms_dbfs": -18.2, "noise_floor_dbfs": -31.4, "clipping_pct": 0.3 },
    "enhanced": { "rms_dbfs": -20.1, "noise_floor_dbfs": -48.7, "speech_active": true },
    "lift":     { "noise_reduction_db": 17.3, "speech_preservation_pct": 92 }
} }

// Operator assist update
{ "type": "assist", "t": 13.5, "payload": { /* OperatorAssist */ } }

// Surfaced alert
{ "type": "alert", "t": 14.0, "payload": { "level": "critical", "message": "Caller mentions 'not breathing'" } }

// Call ended
{ "type": "call_ended", "t": 92.7, "payload": { "summary_url": "/api/calls/.../summary" } }
```

## Client → server

```jsonc
// Live audio (only in source=live mode)
{ "type": "audio_frame", "payload": { "pcm16_b64": "...", "sample_rate": 16000 } }

// Operator confirmation / override
{ "type": "operator_event", "payload": { "kind": "confirm", "field": "breathing", "value": "not breathing" } }

// Suggestion feedback
{ "type": "operator_event", "payload": { "kind": "ask", "suggestion_id": "sug_7" } }
```

## Lifecycle
1. Client `POST /api/calls` → gets `call_id` + `ws_url`.
2. Client opens WS.
3. For `upload`: client `POST /api/calls/{id}/audio` (file). For `live`: client
   streams `audio_frame` over WS.
4. Server pushes `transcript`, `incident`, `metrics`, `assist`, `alert`.
5. Client `POST /api/calls/{id}/end` → server emits `call_ended` and closes WS.
