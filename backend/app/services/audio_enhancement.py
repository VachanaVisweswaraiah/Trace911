"""ai-coustics enhancement service.

Ports the logic from calls/clean_audio.py into an async-friendly service.
CPU-intensive enhancement runs in a thread-pool executor so it does not
block the event loop.

Pipeline:
    WAV bytes → enhance → compute metrics → persist + publish → return enhanced WAV bytes
"""

from __future__ import annotations

import asyncio
import io
import math

import numpy as np
import soundfile as sf

try:
    import aic_sdk as aic
    _AIC_AVAILABLE = True
except ImportError:
    _AIC_AVAILABLE = False

from app.config import settings
from app.db import SessionLocal
from app.pubsub import broker
from app.repository import calls as calls_repo
from app.schemas import AudioMetrics, AudioWindow, MetricsSnapshot
from app.schemas.metrics import NoiseSeverity, _AudioWindowSide, _AudioWindowLift


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rms_dbfs(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms < 1e-10:
        return -100.0
    return 20.0 * math.log10(rms)


def _noise_severity(rms_dbfs: float) -> NoiseSeverity:
    if rms_dbfs < -40:
        return "low"
    elif rms_dbfs < -30:
        return "medium"
    elif rms_dbfs < -20:
        return "high"
    return "severe"


# ── CPU-bound enhancement (runs in thread pool) ───────────────────────────────

def _run_enhancement(wav_bytes: bytes) -> tuple[bytes, float, float, float, int]:
    """
    Enhance audio using ai-coustics SDK.

    Returns:
        enhanced_wav_bytes, raw_rms_dbfs, enhanced_rms_dbfs, sample_rate, duration_ms
    """
    if not _AIC_AVAILABLE:
        raise RuntimeError(
            "aic_sdk not importable. Install it in the backend venv "
            "(same package used in calls/clean_audio.py)."
        )
    if not settings.aic_sdk_license:
        raise RuntimeError(
            "AIC_SDK_LICENSE is not set. Add it to your .env file."
        )

    # Read raw audio from bytes
    raw_buf = io.BytesIO(wav_bytes)
    audio_raw, sample_rate = sf.read(raw_buf, dtype="float32")

    # Ensure shape is (channels, frames) — mono comes in as 1D
    if audio_raw.ndim == 1:
        audio_input = audio_raw.reshape(1, -1)
        num_channels = 1
    else:
        audio_input = audio_raw.T
        num_channels = audio_input.shape[0]

    raw_rms = _rms_dbfs(audio_input)
    duration_ms = int(audio_input.shape[1] / sample_rate * 1000)

    # Load / cache model
    model_path = aic.Model.download(settings.aic_model_id, settings.aic_model_dir)
    model = aic.Model.from_file(model_path)

    config = aic.ProcessorConfig.optimal(
        model, sample_rate=sample_rate, num_channels=num_channels
    )
    processor = aic.Processor(model, settings.aic_sdk_license, config)
    proc_ctx = processor.get_processor_context()
    proc_ctx.reset()

    # Pad start to compensate for algorithmic latency
    latency_samples = proc_ctx.get_output_delay()
    padding = np.zeros((num_channels, latency_samples), dtype=np.float32)
    audio_padded = np.concatenate([padding, audio_input], axis=1)

    num_frames = config.num_frames
    total = audio_padded.shape[1]
    output = np.zeros_like(audio_padded)

    for start in range(0, total, num_frames):
        end = min(start + num_frames, total)
        chunk = audio_padded[:, start:end]
        valid = chunk.shape[1]
        if valid < num_frames:
            buf = np.zeros((num_channels, num_frames), dtype=np.float32)
            buf[:, :valid] = chunk
            processed = processor.process(buf)
            output[:, start : start + valid] = processed[:, :valid]
        else:
            output[:, start:end] = processor.process(chunk)

    enhanced = output[:, latency_samples:]
    enhanced_rms = _rms_dbfs(enhanced)

    # Write enhanced audio back to bytes
    out_buf = io.BytesIO()
    sf.write(out_buf, enhanced.T, sample_rate, format="WAV", subtype="PCM_16")
    out_buf.seek(0)
    return out_buf.read(), raw_rms, enhanced_rms, sample_rate, duration_ms


# ── Public async entry point ──────────────────────────────────────────────────

async def enhance_and_meter(call_id: str, wav_bytes: bytes) -> bytes:
    """Enhance audio, publish metrics + audio_window events, return enhanced WAV bytes.

    Enhancement runs in a thread-pool executor so the event loop stays free.
    Falls back to raw audio if ai-coustics is unavailable, publishing a warning.
    """
    loop = asyncio.get_event_loop()

    try:
        enhanced_wav, raw_rms, enhanced_rms, sample_rate, duration_ms = (
            await loop.run_in_executor(None, _run_enhancement, wav_bytes)
        )
    except Exception as exc:
        await broker.publish(
            call_id,
            "alert",
            {"message": f"Audio enhancement failed: {exc}. Using raw audio.", "severity": "warn"},
        )
        # Fall back to raw audio so STT can still run
        return wav_bytes

    # Compute lift metrics
    lift_db = max(0.0, raw_rms - enhanced_rms)
    raw_linear = 10 ** (raw_rms / 20)
    enh_linear = 10 ** (enhanced_rms / 20)
    speech_pct = min(100.0, (enh_linear / raw_linear) * 100) if raw_linear > 1e-10 else 100.0

    # Persist metrics snapshot
    metrics = MetricsSnapshot(
        audio=AudioMetrics(
            noise_severity=_noise_severity(raw_rms),
            enhancement_lift_db=round(lift_db, 2),
            speech_preservation_pct=round(speech_pct, 1),
            model=settings.aic_model_id,
            enhancement_level=settings.aic_enhancement_level,
        )
    )
    async with SessionLocal() as db:
        await calls_repo.update_metrics(db, call_id, metrics)
        await db.commit()

    # Publish audio_window event (whole-file window for upload mode)
    window = AudioWindow(
        window_ms=duration_ms,
        raw=_AudioWindowSide(rms_dbfs=raw_rms, noise_floor_dbfs=raw_rms),
        enhanced=_AudioWindowSide(rms_dbfs=enhanced_rms, noise_floor_dbfs=enhanced_rms),
        lift=_AudioWindowLift(
            noise_reduction_db=lift_db,
            speech_preservation_pct=speech_pct,
        ),
    )
    await broker.publish(call_id, "audio_window", window.model_dump())
    await broker.publish(call_id, "metrics", metrics.model_dump())

    return enhanced_wav
