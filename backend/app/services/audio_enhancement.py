"""ai-coustics integration.

Wraps the LiveKit `livekit-plugins-ai-coustics` plugin. Two responsibilities:

1. Run audio through ai-coustics enhancement (model = QUAIL_VF_L by default).
2. Tap raw and enhanced streams in parallel so we can compute lift metrics
   (noise reduction dB, speech preservation %).

Reference setup pattern (LiveKit + ai-coustics):

    from livekit.agents import AgentSession, room_io
    from livekit.plugins import ai_coustics

    session = AgentSession(vad=ai_coustics.VAD())
    await session.start(
        agent=...,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_L,
                    model_parameters=ai_coustics.ModelParameters(
                        enhancement_level=settings.aic_enhancement_level,
                    ),
                    vad_settings=ai_coustics.VadSettings(
                        speech_hold_duration=settings.aic_vad_speech_hold,
                        sensitivity=settings.aic_vad_sensitivity,
                        minimum_speech_duration=settings.aic_vad_min_speech,
                    ),
                )
            )
        ),
    )

For the upload demo path, run a local enhancement pass over the WAV and emit
audio_window events at 1 Hz.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WindowStats:
    rms_dbfs: float
    noise_floor_dbfs: float
    clipping_pct: float = 0.0
    speech_active: bool | None = None


async def enhance_and_meter(call_id: str, pcm_bytes: bytes, sample_rate: int = 16000) -> None:
    """Enhance audio + emit audio_window events. TODO: implement."""
    raise NotImplementedError
