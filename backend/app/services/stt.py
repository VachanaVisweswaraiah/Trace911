"""Gradium streaming STT service.

Ports calls/stream_transcribe.py into an async service that publishes
transcript events via the broker and persists segments to the DB.

Segment lifecycle:
  - Each speaker turn gets one stable segment ID ({call_id}_turn_N).
  - "text" messages from Gradium are cumulative within a turn — each one
    replaces the current segment text (is_final=False).
  - "end_text" marks the turn complete — segment is upserted with is_final=True.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys

import aiohttp

from app.config import settings
from app.db import SessionLocal
from app.pubsub import broker
from app.repository import transcript as transcript_repo
from app.schemas import TranscriptSegment

# Gradium protocol constants — must match calls/stream_transcribe.py
_WS_URL = "wss://us.api.gradium.ai/api/speech/asr"
_SAMPLE_RATE = 24_000          # Gradium expects 24kHz PCM
_FRAME_SAMPLES = 1_920         # 80ms at 24kHz
_BYTES_PER_FRAME = _FRAME_SAMPLES * 2  # 16-bit = 2 bytes/sample
_CHUNK_DURATION = _FRAME_SAMPLES / _SAMPLE_RATE  # 0.08 s


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resample_if_needed(wav_bytes: bytes) -> bytes:
    """Ensure the WAV is 24kHz mono 16-bit PCM (what Gradium expects).

    Uses pydub for conversion — same approach as stream_transcribe.py.
    """
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            if (
                wf.getnchannels() == 1
                and wf.getsampwidth() == 2
                and wf.getframerate() == _SAMPLE_RATE
            ):
                # Already correct — extract raw PCM frames
                return wf.readframes(wf.getnframes())
    except Exception:
        pass

    # Need conversion
    from pydub import AudioSegment

    audio = AudioSegment.from_file(io.BytesIO(wav_bytes))
    audio = audio.set_frame_rate(_SAMPLE_RATE).set_channels(1).set_sample_width(2)
    return audio.raw_data  # 16-bit signed LE mono at 24kHz


async def _send_setup(ws: aiohttp.ClientWebSocketResponse) -> bool:
    """Send setup message and wait for server "ready". No other reader active."""
    await ws.send_str(json.dumps({
        "type": "setup",
        "model_name": "default",
        "input_format": "pcm",
        "json_config": {"language": "en"},
    }))

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("type") == "ready":
                return True
            if data.get("type") == "error":
                return False
        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
            return False

    return False


async def _send_audio(ws: aiohttp.ClientWebSocketResponse, pcm_data: bytes) -> None:
    """Stream PCM chunks — SEND ONLY, never reads from the WebSocket."""
    offset = 0
    while offset < len(pcm_data):
        chunk = pcm_data[offset : offset + _BYTES_PER_FRAME]
        if len(chunk) < _BYTES_PER_FRAME:
            chunk = chunk + b"\x00" * (_BYTES_PER_FRAME - len(chunk))

        await ws.send_str(json.dumps({
            "type": "audio",
            "audio": base64.b64encode(chunk).decode("ascii"),
        }))
        offset += _BYTES_PER_FRAME
        await asyncio.sleep(_CHUNK_DURATION)

    await ws.send_str(json.dumps({"type": "end_of_stream"}))


async def _receive_and_persist(
    ws: aiohttp.ClientWebSocketResponse,
    call_id: str,
) -> str:
    """Sole WebSocket reader. Persists segments and publishes broker events.

    Returns the full accumulated transcript text.
    """
    full_transcript = ""
    turn_count = 0
    turn_text = ""
    turn_start: float | None = None
    segment_id: str | None = None

    async for msg in ws:
        if msg.type != aiohttp.WSMsgType.TEXT:
            if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                break
            continue

        data = json.loads(msg.data)
        kind = data.get("type", "")

        if kind == "text":
            text_chunk = data.get("text", "")
            if not text_chunk:
                continue

            # First word in this turn — record start time and fix segment ID
            if turn_start is None:
                turn_start = float(data.get("start_s", broker.t_for(call_id)))
                segment_id = f"{call_id}_turn_{turn_count}"

            # Gradium sends incremental words — append to build the turn
            turn_text += text_chunk
            t_now = broker.t_for(call_id)

            seg = TranscriptSegment(
                id=segment_id,
                t_start=turn_start,
                t_end=t_now,
                speaker="caller",
                text=turn_text.strip(),
                is_final=False,
                confidence=float(data.get("confidence", 0.85)),
            )

            async with SessionLocal() as db:
                await transcript_repo.upsert(db, call_id, seg)
                await db.commit()

            await broker.publish(call_id, "transcript", seg.model_dump(mode="json"))

        elif kind == "end_text":
            if segment_id is None:
                continue

            stop_s = float(data.get("stop_s", broker.t_for(call_id)))
            seg = TranscriptSegment(
                id=segment_id,
                t_start=turn_start or stop_s,
                t_end=stop_s,
                speaker="caller",
                text=turn_text.strip(),
                is_final=True,
                confidence=0.9,
            )

            async with SessionLocal() as db:
                await transcript_repo.upsert(db, call_id, seg)
                await db.commit()

            await broker.publish(call_id, "transcript", seg.model_dump(mode="json"))

            full_transcript += turn_text.strip() + "\n"
            turn_count += 1
            turn_text = ""
            turn_start = None
            segment_id = None

        elif kind == "end_of_stream":
            break

        elif kind == "error":
            await broker.publish(
                call_id,
                "alert",
                {"message": f"Gradium STT error: {data}", "severity": "error"},
            )
            break

    return full_transcript.strip()


# ── Public entry point ────────────────────────────────────────────────────────

async def stream_transcribe(call_id: str, wav_bytes: bytes) -> str:
    """Stream wav_bytes to Gradium STT. Publishes transcript events, returns full text.

    Resamples to 24kHz mono if needed. Publishes an alert event on failure.
    """
    if not settings.gradium_api_key:
        await broker.publish(
            call_id,
            "alert",
            {"message": "GRADIUM_API_KEY not set — STT skipped.", "severity": "warn"},
        )
        return ""

    # Resample / convert format on the thread pool (pydub is blocking)
    loop = asyncio.get_event_loop()
    try:
        pcm_data = await loop.run_in_executor(None, _resample_if_needed, wav_bytes)
    except Exception as exc:
        await broker.publish(
            call_id,
            "alert",
            {"message": f"Audio resampling failed: {exc}", "severity": "error"},
        )
        return ""

    session = aiohttp.ClientSession()
    try:
        try:
            ws = await session.ws_connect(
                _WS_URL,
                headers={"x-api-key": settings.gradium_api_key},
            )
        except Exception as exc:
            await broker.publish(
                call_id,
                "alert",
                {"message": f"Gradium connection failed: {exc}", "severity": "error"},
            )
            return ""

        try:
            if not await _send_setup(ws):
                await broker.publish(
                    call_id,
                    "alert",
                    {"message": "Gradium setup handshake failed.", "severity": "error"},
                )
                return ""

            # Concurrent send + receive — send_audio NEVER reads the WS
            _, transcript = await asyncio.gather(
                _send_audio(ws, pcm_data),
                _receive_and_persist(ws, call_id),
            )
            return transcript

        finally:
            await ws.close()

    except Exception as exc:
        await broker.publish(
            call_id,
            "alert",
            {"message": f"STT error: {exc}", "severity": "error"},
        )
        return ""

    finally:
        await session.close()
