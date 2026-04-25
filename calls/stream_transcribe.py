#!/usr/bin/env python3
"""
Stream a WAV file to Gradium's STT WebSocket API as if it were live microphone audio,
and print the transcript word-by-word to the terminal.

Usage:
    python stream_transcribe.py caller_audio.wav

Requires a .env file with GRADIUM_API_KEY=your_key_here
"""

import argparse
import base64
import json
import os
import sys
import wave
from datetime import datetime

import aiohttp
import asyncio
from dotenv import load_dotenv
from pydub import AudioSegment

# ─── Configuration ──────────────────────────────────────────────────────────────
# Gradium WebSocket endpoint (US region)
GRADIUM_WS_URL = "wss://us.api.gradium.ai/api/speech/asr"

# Gradium expects PCM audio at 24kHz, 16-bit signed, mono.
# We read the WAV at its native rate and resample if needed.
GRADIUM_SAMPLE_RATE = 24000
GRADIUM_FRAME_SIZE = 1920  # samples per chunk = 80ms at 24kHz
CHUNK_DURATION_S = GRADIUM_FRAME_SIZE / GRADIUM_SAMPLE_RATE  # 0.08s

# How long to wait for remaining transcript messages after end_of_stream
FINAL_WAIT_TIMEOUT = 3.0

# Progress indicator interval (seconds of audio streamed)
PROGRESS_INTERVAL_S = 5.0


# ─── Step 1: Load and validate the WAV file ────────────────────────────────────

def load_and_prepare_wav(wav_path: str) -> tuple[bytes, int]:
    """Load a WAV file, validate/convert to the format Gradium expects.

    Returns (raw_pcm_bytes, sample_rate) where pcm bytes are 16-bit signed
    little-endian mono at the target sample rate (24kHz for Gradium).
    """
    print(f"[1/5] Loading WAV file: {wav_path}")

    # Try reading with the wave module to check format
    needs_conversion = False
    try:
        with wave.open(wav_path, "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()  # in bytes (2 = 16-bit)
            framerate = wf.getframerate()
            n_frames = wf.getnframes()

            print(f"      Channels: {channels} | Sample width: {sample_width*8}-bit | "
                  f"Rate: {framerate}Hz | Frames: {n_frames}")

            if channels != 1 or sample_width != 2 or framerate != GRADIUM_SAMPLE_RATE:
                needs_conversion = True

            duration = n_frames / framerate
            print(f"      Duration: {duration:.1f}s")
    except wave.Error:
        print("      Not a valid WAV file or unsupported format — will convert with pydub")
        needs_conversion = True

    if needs_conversion:
        print(f"      Converting to {GRADIUM_SAMPLE_RATE}Hz mono 16-bit PCM "
              f"(required by Gradium)...")
        audio = AudioSegment.from_file(wav_path)
        audio = audio.set_frame_rate(GRADIUM_SAMPLE_RATE).set_channels(1).set_sample_width(2)
        pcm_bytes = audio.raw_data  # already 16-bit signed LE mono at 24kHz
        sample_rate = GRADIUM_SAMPLE_RATE
        duration = len(audio) / 1000.0
        print(f"      Converted: {duration:.1f}s at {sample_rate}Hz mono 16-bit")
    else:
        # File is already in the right format — read raw PCM frames
        with wave.open(wav_path, "rb") as wf:
            pcm_bytes = wf.readframes(wf.getnframes())
        sample_rate = GRADIUM_SAMPLE_RATE
        duration = len(pcm_bytes) // 2 / sample_rate  # 2 bytes per sample
        print(f"      Already in correct format — {duration:.1f}s")

    total_samples = len(pcm_bytes) // 2
    print(f"      Total samples: {total_samples:,} | "
          f"Chunks to stream: {total_samples // GRADIUM_FRAME_SIZE}")
    return pcm_bytes, sample_rate, duration


# ─── Step 2: Connect to Gradium WebSocket ────────────────────────────────────────

async def connect_to_gradium(api_key: str) -> aiohttp.ClientWebSocketResponse:
    """Open a WebSocket connection to Gradium STT with API key authentication.

    The x-api-key header is how Gradium authenticates WebSocket connections.
    This is sent during the HTTP upgrade handshake, not as a message.
    """
    print("[2/5] Connecting to Gradium STT WebSocket...")
    session = aiohttp.ClientSession()
    try:
        ws = await session.ws_connect(
            GRADIUM_WS_URL,
            headers={"x-api-key": api_key},
        )
        print(f"      Connected to {GRADIUM_WS_URL}")
        return ws, session
    except aiohttp.ClientResponseError as e:
        print(f"      Connection failed: {e.status} {e.message}", file=sys.stderr)
        await session.close()
        sys.exit(1)
    except Exception as e:
        print(f"      Connection error: {e}", file=sys.stderr)
        await session.close()
        sys.exit(1)


# ─── Step 3: Stream audio chunks ────────────────────────────────────────────────

async def send_setup(ws: aiohttp.ClientWebSocketResponse) -> bool:
    """Send the setup message and wait for the server's "ready" response.

    This runs ALONE — no other receiver is active. Only after we get
    "ready" do we start the concurrent send/receive phase.
    """
    setup_msg = {
        "type": "setup",
        "model_name": "default",
        "input_format": "pcm",
        "json_config": {"language": "en"},
    }
    await ws.send_str(json.dumps(setup_msg))
    print("[3/5] Setup message sent — waiting for server ready...")

    # Simple loop: we are the only reader right now, so no concurrency issues
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("type") == "ready":
                print(f"      Server ready — sample_rate={data.get('sample_rate')}, "
                      f"frame_size={data.get('frame_size')}")
                return True
            elif data.get("type") == "error":
                print(f"      Server error during setup: {data}", file=sys.stderr)
                return False
        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
            print("      WebSocket closed during setup", file=sys.stderr)
            return False

    return False


async def send_audio(
    ws: aiohttp.ClientWebSocketResponse,
    pcm_data: bytes,
    duration: float,
) -> None:
    """Stream audio chunks in real time — SEND ONLY, never reads from the WebSocket.

    Each chunk is 1920 samples (80ms at 24kHz), sent as a base64-encoded
    JSON message. We sleep 80ms between chunks to simulate live microphone
    input so the server processes audio at natural speed.
    """
    print("[4/5] Streaming audio...")

    # Each sample is 2 bytes (16-bit), so frame_size samples = frame_size * 2 bytes
    bytes_per_chunk = GRADIUM_FRAME_SIZE * 2
    total_bytes = len(pcm_data)
    offset = 0
    chunk_num = 0
    # Track progress — print every PROGRESS_INTERVAL_S seconds of audio streamed
    next_progress = PROGRESS_INTERVAL_S
    # Flag so main() knows if the server closed early
    ws_closed_early = False

    while offset < total_bytes:
        chunk = pcm_data[offset : offset + bytes_per_chunk]
        # Pad the last chunk with zeros if it's smaller than frame_size
        if len(chunk) < bytes_per_chunk:
            chunk = chunk + b"\x00" * (bytes_per_chunk - len(chunk))

        # Gradium expects audio as base64 inside a JSON message
        audio_msg = {
            "type": "audio",
            "audio": base64.b64encode(chunk).decode("ascii"),
        }
        try:
            await ws.send_str(json.dumps(audio_msg))
        except (aiohttp.ClientConnectionError,
                aiohttp.WSServerHandshakeError,
                ConnectionResetError,
                BrokenPipeError):
            # Server closed the WebSocket mid-stream — stop sending gracefully
            ws_closed_early = True
            break

        offset += bytes_per_chunk
        chunk_num += 1

        # Calculate how many seconds of audio we've streamed so far
        seconds_streamed = (offset // 2) / GRADIUM_SAMPLE_RATE

        # Print progress every 5 seconds
        if seconds_streamed >= next_progress:
            print(f"      [{seconds_streamed:.0f}s / {duration:.0f}s] "
                  f"streamed — chunk #{chunk_num}")
            next_progress += PROGRESS_INTERVAL_S

        # Sleep to simulate real-time streaming (80ms per chunk)
        await asyncio.sleep(CHUNK_DURATION_S)

    if ws_closed_early:
        seconds_streamed = (offset // 2) / GRADIUM_SAMPLE_RATE
        print(f"      [Stream closed by server — saving transcript...] "
              f"(sent {seconds_streamed:.1f}s of {duration:.1f}s)")
    else:
        # ── Signal end of stream ──
        # Tell Gradium we're done sending audio. It will process any remaining
        # buffered audio and send final transcript results.
        try:
            await ws.send_str(json.dumps({"type": "end_of_stream"}))
            print(f"      Audio stream complete — {duration:.1f}s sent in {chunk_num} chunks")
        except (aiohttp.ClientConnectionError,
                aiohttp.WSServerHandshakeError,
                ConnectionResetError,
                BrokenPipeError):
            print("      [Stream closed by server — saving transcript...]")


# ─── Step 4: Receive and display transcript ──────────────────────────────────────

async def receive_transcript(
    ws: aiohttp.ClientWebSocketResponse,
) -> str:
    """Listen for transcript and VAD messages from Gradium concurrently.

    This runs alongside stream_audio using asyncio.gather. It collects:
      - "text" messages: partial or final transcript text with timestamps
      - "end_text" messages: speaker turn boundaries — we print a newline
      - "step" messages: VAD events (not printed, but available for debugging)

    Returns the accumulated transcript string.
    """
    full_transcript = ""

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            msg_type = data.get("type", "")

            if msg_type == "text":
                # Transcript text arrived — print it with timestamp
                text = data.get("text", "")
                start_s = data.get("start_s", 0)
                print(f"      [TRANSCRIPT] {start_s:6.2f}s | {text}")
                full_transcript += text + " "

            elif msg_type == "end_text":
                # Speaker finished a turn — separate sentences with a newline
                stop_s = data.get("stop_s", 0)
                print(f"      [END TURN   ] {stop_s:.2f}s")
                full_transcript = full_transcript.strip() + "\n"

            elif msg_type == "step":
                # VAD step — not printed to avoid clutter, but available
                # You can uncomment this to see VAD activity:
                # vad = data.get("vad", [])
                # if vad and vad[-1].get("inactivity_prob", 0) > 0.5:
                #     print(f"      [VAD] Speaker pause detected")
                pass

            elif msg_type == "flushed":
                # Confirmation that a flush request was processed
                pass

            elif msg_type == "error":
                print(f"      [ERROR] {data}", file=sys.stderr)

            elif msg_type == "end_of_stream":
                # Server confirmed it finished processing
                print("      Server confirmed end of stream")
                break

        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
            print("      WebSocket connection closed", file=sys.stderr)
            break

    return full_transcript.strip()


# ─── Step 5: Save transcript and finish ─────────────────────────────────────────

def save_transcript(transcript: str, duration: float, output_path: str = None) -> str:
    """Save the accumulated transcript to a file with a header."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    word_count = len(transcript.split()) if transcript.strip() else 0

    if output_path is None:
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcript.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"Transcript — {timestamp}\n")
        f.write(f"Duration: {duration:.1f}s | Words: {word_count}\n")
        f.write("=" * 60 + "\n\n")
        f.write(transcript + "\n")

    print(f"\n[5/5] Transcript saved!")
    print(f"      Duration streamed: {duration:.1f}s")
    print(f"      Total words: {word_count}")
    print(f"      Saved to: {output_path}")
    return output_path


# ─── Main: orchestrate everything ───────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Stream a WAV file to Gradium STT and print live transcript."
    )
    parser.add_argument("input", help="Path to input .wav file")
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Path for transcript output file (default: transcript.txt in script directory)",
    )
    args = parser.parse_args()

    input_path = args.input
    if not os.path.isfile(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load API key from .env
    load_dotenv()
    api_key = os.environ.get("GRADIUM_API_KEY")
    if not api_key:
        print(
            "Error: GRADIUM_API_KEY not found. "
            "Add it to your .env file (see .env.example).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Step 1: Load and prepare audio
    pcm_data, sample_rate, duration = load_and_prepare_wav(input_path)

    transcript = ""

    try:
        # Step 2: Connect to Gradium
        ws, session = await connect_to_gradium(api_key)

        try:
            # Step 3: Send setup and wait for "ready" — solo, no other reader active
            if not await send_setup(ws):
                print("      Setup failed — aborting", file=sys.stderr)
                sys.exit(1)

            # Step 4: Now start concurrent send + receive.
            # send_audio() ONLY writes to the WebSocket (never reads).
            # receive_transcript() is the SOLE reader for the rest of the session.
            # asyncio.gather runs both at the same time so we see live transcript
            # output as audio chunks are being sent.
            #
            # If send_audio() hits a ConnectionClosed error, it returns early.
            # receive_transcript() will see the closed connection and also return
            # with whatever transcript it collected. asyncio.gather waits for
            # BOTH to finish, so we always get the full transcript even on early close.
            _, transcript = await asyncio.gather(
                send_audio(ws, pcm_data, duration),
                receive_transcript(ws),
            )
        except Exception as e:
            # Catch-all for truly unexpected errors (not connection close)
            print(f"\nError during streaming: {e}", file=sys.stderr)
            # transcript may have partial data from before the error
        finally:
            await ws.close()
            await session.close()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)

    # Step 5: Save transcript — even if something failed mid-stream,
    # we save whatever we collected.
    if not transcript.strip():
        print("\nNo transcript text received from Gradium.", file=sys.stderr)
        # Still create the file so the user knows the script ran
        transcript = "(no transcript received — connection may have closed early)"

    save_transcript(transcript, duration, args.output)


if __name__ == "__main__":
    asyncio.run(main())