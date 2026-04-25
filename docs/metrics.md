# Metrics

Six metrics, computed continuously and pushed via WS as `metrics` and per-window
`audio_window` events.

## 1. Noise severity (raw audio)
Per 1s window on raw input: RMS dBFS, clipping %, silence ratio, noise floor
(RMS during non-speech). Bucketed → `low | medium | high | severe`.

## 2. Enhancement lift (ai-coustics)
Raw vs enhanced audio, side-by-side tap.
- `noise_reduction_db` = raw_noise_floor − enhanced_noise_floor
- `speech_preservation_pct` = enhanced_speech_rms / raw_speech_rms (clamped)
- Reports `model` and `enhancement_level` for transparency.

## 3. VAD stability
From `ai_coustics.VAD()` + LiveKit `user_state_changed`.
- `speech_activity_ratio`, `turns`, `false_start_count`,
  `avg_end_of_turn_ms`, `overlap_events`.

## 4. Transcript health (0–100)
Derived. Inputs: STT word/segment confidence, `[inaudible]` rate, partial→final
revision count, very-short noisy turns, LLM extraction uncertainty.
Display as a single score; expose components in the snapshot for the demo.

## 5. Critical field coverage
`field_coverage = populated_fields / 11`.
`confirmed_coverage = confirmed_by_operator_fields / 11`.
Also: `time_to_first_location_s`, `time_to_incident_type_s`,
`time_to_dispatch_ready_s` (when `dispatch_readiness >= 0.8`),
`contradiction_count`.

## 6. Operator assist quality
`suggestions_shown / used / dismissed`, `operator_overrides`,
`high_risk_unconfirmed_count`, `summary_edit_distance` (post-call).

## Storage
For the hackathon: in-memory ring buffer per call_id (see `app/store/memory.py`).
No DB. Snapshots are recomputed from the buffer on demand.

## Tuning notes (ai-coustics)
- Default model: `QUAIL_VF_L` (foreground voice focus).
- Switch to `QUAIL_L` if multi-speaker / far-field is dominant.
- `enhancement_level=0.8` baseline. Lower preserves ambiguous speech; higher
  suppresses competing speech but risks dropping quiet foreground speech. Watch
  insertions/deletions when tuning.
- `VadSettings`: start with `sensitivity=6.0`, `speech_hold_duration=0.03`,
  `minimum_speech_duration=0.0`.
