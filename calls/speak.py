#!/usr/bin/env python3
"""
Gradium TTS module — synthesize text to speech and play through speakers.

Usage (standalone):
    python speak.py "Alert: fire on Route 7"

Usage (importable):
    from speak import speak
    speak("Critical alert. Send fire department immediately.")
"""

import argparse
import asyncio
import base64
import json
import os
import sys

import aiohttp
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv

# ─── Configuration ──────────────────────────────────────────────────────────────

GRADIUM_TTS_URL = "wss://us.api.gradium.ai/api/speech/tts"
DEFAULT_VOICE_ID = "YTpq7expH9539ERJ"
DEFAULT_OUTPUT_FORMAT = "wav"


# ─── Async TTS over WebSocket ──────────────────────────────────────────────────

async def _tts_ws(text: str, api_key: str, voice_id: str = DEFAULT_VOICE_ID) -> bytes:
    """Connect to Gradium TTS WebSocket, synthesize text, return WAV bytes."""

    session = aiohttp.ClientSession()
    try:
        ws = await session.ws_connect(
            GRADIUM_TTS_URL,
            headers={"x-api-key": api_key},
        )
    except Exception as e:
        await session.close()
        raise RuntimeError(f"TTS connection failed: {e}") from e

    try:
        # Send setup message
        setup_msg = {
            "type": "setup",
            "model_name": "default",
            "voice_id": voice_id,
            "output_format": DEFAULT_OUTPUT_FORMAT,
        }
        await ws.send_str(json.dumps(setup_msg))

        # Wait for server ready
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "ready":
                    break
                elif data.get("type") == "error":
                    raise RuntimeError(f"TTS setup error: {data}")
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                raise RuntimeError("TTS WebSocket closed during setup")

        # Send text to synthesize
        await ws.send_str(json.dumps({"type": "text", "text": text}))
        await ws.send_str(json.dumps({"type": "end_of_stream"}))

        # Collect audio chunks
        audio_chunks = []
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = data.get("type", "")

                if msg_type == "audio":
                    chunk_bytes = base64.b64decode(data.get("audio", ""))
                    audio_chunks.append(chunk_bytes)
                elif msg_type == "end_of_stream":
                    break
                elif msg_type == "error":
                    raise RuntimeError(f"TTS error: {data}")
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                break

        if not audio_chunks:
            raise RuntimeError("No audio data received from TTS")

        return b"".join(audio_chunks)

    finally:
        await ws.close()
        await session.close()


# ─── Synchronous public API ────────────────────────────────────────────────────

def speak(text: str, api_key: str = None) -> None:
    """Synthesize text and play through speakers. Never crashes on failure.

    Args:
        text: The text to speak.
        api_key: Gradium API key. If None, loads from .env (GRADIUM_API_KEY).
    """
    try:
        if not api_key:
            load_dotenv()
            api_key = os.environ.get("GRADIUM_API_KEY")
        if not api_key:
            print("[TTS] No GRADIUM_API_KEY found — cannot speak", file=sys.stderr)
            print(f"[TTS] Alert text: {text}")
            return

        # Get WAV bytes from Gradium TTS
        wav_bytes = asyncio.run(_tts_ws(text, api_key))

        # Write to a temporary in-memory buffer and play
        import io
        buffer = io.BytesIO(wav_bytes)
        data, sample_rate = sf.read(buffer, dtype="float32")
        sd.play(data, sample_rate)
        sd.wait()  # Block until playback finishes

    except Exception as e:
        print(f"[TTS] Failed: {e}", file=sys.stderr)
        print(f"[TTS] Alert text: {text}")


# ─── Standalone CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gradium TTS — speak text through speakers")
    parser.add_argument("text", help="Text to speak")
    args = parser.parse_args()
    speak(args.text)