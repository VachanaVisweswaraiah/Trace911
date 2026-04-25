# ClearCall — App Spec

## One-liner
An emergency-call co-pilot that does not replace the operator. It makes chaotic
audio usable, extracts the right facts, and keeps the human in control.

## Audience
Hackathon judges (ai-coustics track). One operator, one live call, one screen.

## Stack
- **Frontend:** Lovable → React + JavaScript (Vite). Single-page workspace.
- **Backend:** Python 3.11 + FastAPI. WebSocket fan-out for live state.
- **Audio enhancement:** ai-coustics via the LiveKit plugin
  (`livekit-plugins-ai-coustics`), model `QUAIL_VF_L` at `enhancement_level=0.8`.
- **VAD:** `ai_coustics.VAD()` (model-internal, runs on enhanced audio).
- **STT:** Gladia (streaming).
- **Extraction:** LLM call over rolling transcript → structured incident card.

## Surfaces (one screen, three columns)
1. **Left — Call stream:** waveform (raw + enhanced), live transcript with
   confidence styling, entity highlights.
2. **Center — Incident card:** structured fields with status (`missing`, `heard`,
   `suggested`, `confirmed_by_operator`, `uncertain`, `contradicted`).
3. **Right — Operator assist:** next best question, critical missing fields,
   alerts. No chatbot. Buttons only.

Plus a **handoff summary** view shown after the call ends.

## Incident schema
Fields tracked on every call:

- `location`
- `incident_type` (medical | fire | police | traffic | other)
- `number_of_people`
- `injury_status`
- `consciousness`
- `breathing`
- `immediate_danger`
- `weapons`
- `fire_or_smoke`
- `caller_callback`
- `access_instructions`

## Metrics surfaced to the UI
The six the judges should see (full detail in `metrics.md`):

1. Noise severity
2. Enhancement lift (dB noise reduction, % speech preserved)
3. VAD stability (turns, false starts, end-of-turn delay)
4. Transcript health (0–100, derived)
5. Critical field coverage (`x/11`, with confirmed subset)
6. Dispatch readiness (%)

## Non-goals
- No autonomous dispatch.
- No medical diagnosis.
- No multi-call command center for the demo.
- No map view.
- No auth. Single-user demo.

## Demo flow
1. Operator opens the workspace, clicks **Start call** (uploads or streams a noisy
   sample WAV).
2. Backend enhances audio → STT → extraction; pushes events over WS.
3. Incident card fills in with status badges. Right rail suggests next question.
4. Operator confirms / overrides fields.
5. **End call** → handoff summary, editable.
