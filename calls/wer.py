#!/usr/bin/env python3
"""
WER (Word Error Rate) measurement script — compare transcription quality
between ai-coustics enhanced audio and original/noisy audio.

Usage:
    python wer.py --clean cleaned.wav --noisy original.wav

Requires a .env file with GRADIUM_API_KEY=your_key_here
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime

import aiohttp
import editdistance
from dotenv import load_dotenv
from pydub import AudioSegment

# Reuse core functions from stream_transcribe
from stream_transcribe import (
    load_and_prepare_wav,
    connect_to_gradium,
    send_setup,
    send_audio,
    receive_transcript,
)


# ─── Configuration ──────────────────────────────────────────────────────────────

GRADIUM_WS_URL = "wss://us.api.gradium.ai/api/speech/asr"
METRICS_FILE = "metrics.txt"
FLASK_PORT = 5001


# ─── MP3 → WAV conversion ─────────────────────────────────────────────────────

def ensure_wav(filepath: str) -> str:
    """Convert mp3 to wav if needed. Returns path to wav file."""
    if filepath.endswith(".mp3"):
        print(f"[WER] Converting {filepath} to WAV...")
        audio = AudioSegment.from_mp3(filepath)
        audio = audio.set_frame_rate(16000).set_channels(1)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        audio.export(tmp.name, format="wav")
        print(f"[WER] Converted to {tmp.name}")
        return tmp.name
    return filepath


# ─── WER Computation ───────────────────────────────────────────────────────────

def compute_wer(reference: str, hypothesis: str) -> float:
    """Compute Word Error Rate as a percentage.

    WER = (edit_distance / len(reference)) * 100

    The 'reference' is treated as ground truth (typically the clean transcript).
    """
    ref_words = reference.lower().split()
    hyp_words = hypothesis.lower().split()
    if not ref_words:
        return 0.0 if not hyp_words else 100.0
    distance = editdistance.eval(ref_words, hyp_words)
    return (distance / len(ref_words)) * 100


# ─── Transcribe a single WAV via Gradium STT ────────────────────────────────────

async def transcribe_file(wav_path: str, api_key: str, label: str) -> str:
    """Run the full Gradium STT pipeline on a WAV file and return the transcript text."""
    print(f"\n{'='*60}")
    print(f"[WER] Transcribing {label}: {wav_path}")
    print(f"{'='*60}")

    # Load and prepare audio
    pcm_data, sample_rate, duration = load_and_prepare_wav(wav_path)

    transcript = ""
    try:
        ws, session = await connect_to_gradium(api_key)
        try:
            if not await send_setup(ws):
                print(f"[WER] Setup failed for {label}", file=sys.stderr)
                return ""

            _, transcript = await asyncio.gather(
                send_audio(ws, pcm_data, duration),
                receive_transcript(ws),
            )
        finally:
            await ws.close()
            await session.close()
    except Exception as e:
        print(f"[WER] Error transcribing {label}: {e}", file=sys.stderr)

    if not transcript.strip():
        print(f"[WER] No transcript received for {label}", file=sys.stderr)

    return transcript.strip()


def save_transcript_to_file(transcript: str, path: str, duration: float) -> None:
    """Save transcript to a custom file path (not using stream_transcribe's hardcoded path)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    word_count = len(transcript.split()) if transcript.strip() else 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Transcript — {timestamp}\n")
        f.write(f"Duration: {duration:.1f}s | Words: {word_count}\n")
        f.write("=" * 60 + "\n\n")
        f.write(transcript + "\n")
    print(f"[WER] Saved transcript to: {path}")


# ─── Main WER Pipeline ─────────────────────────────────────────────────────────

async def run_wer(clean_path: str, noisy_path: str) -> dict:
    """Run the full WER pipeline: transcribe both files, compute metrics."""
    load_dotenv()
    api_key = os.environ.get("GRADIUM_API_KEY")
    if not api_key:
        print("Error: GRADIUM_API_KEY not found in .env", file=sys.stderr)
        sys.exit(1)

    # Convert MP3 files to WAV if needed
    clean_wav = ensure_wav(clean_path)
    noisy_wav = ensure_wav(noisy_path)

    # Transcribe both files sequentially
    clean_transcript = await transcribe_file(clean_wav, api_key, "clean")
    noisy_transcript = await transcribe_file(noisy_wav, api_key, "noisy")

    # Clean up temporary files
    for path, original in [(clean_wav, clean_path), (noisy_wav, noisy_path)]:
        if path != original:
            os.unlink(path)

    # Save transcripts
    save_transcript_to_file(clean_transcript, "transcript_clean.txt", 0)
    save_transcript_to_file(noisy_transcript, "transcript_noisy.txt", 0)

    # Compute WER — clean is reference (should be more accurate)
    wer_clean_vs_noisy = compute_wer(clean_transcript, noisy_transcript)

    metrics = {
        "timestamp": datetime.now().isoformat(),
        "clean_file": clean_path,
        "noisy_file": noisy_path,
        "clean_transcript": clean_transcript,
        "noisy_transcript": noisy_transcript,
        "clean_word_count": len(clean_transcript.split()) if clean_transcript else 0,
        "noisy_word_count": len(noisy_transcript.split()) if noisy_transcript else 0,
        "wer_percent": round(wer_clean_vs_noisy, 2),
    }

    return metrics


def print_metrics(metrics: dict) -> None:
    """Print a formatted metrics report to the terminal."""
    divider = "━" * 50
    print(f"\n{divider}")
    print("[WER METRICS REPORT]")
    print(divider)
    print(f"  Clean file:      {metrics['clean_file']}")
    print(f"  Noisy file:       {metrics['noisy_file']}")
    print(f"  Clean words:      {metrics['clean_word_count']}")
    print(f"  Noisy words:      {metrics['noisy_word_count']}")
    print(f"  WER:              {metrics['wer_percent']}%")
    print(divider)
    print(f"\n  Clean transcript:\n    {metrics['clean_transcript']}")
    print(f"\n  Noisy transcript:\n    {metrics['noisy_transcript']}")
    print()


def save_metrics(metrics: dict, path: str = METRICS_FILE) -> None:
    """Save metrics dict to a text file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"WER Metrics Report — {metrics['timestamp']}\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Clean file:      {metrics['clean_file']}\n")
        f.write(f"Noisy file:       {metrics['noisy_file']}\n")
        f.write(f"Clean words:      {metrics['clean_word_count']}\n")
        f.write(f"Noisy words:      {metrics['noisy_word_count']}\n")
        f.write(f"WER:              {metrics['wer_percent']}%\n\n")
        f.write(f"Clean transcript:\n{metrics['clean_transcript']}\n\n")
        f.write(f"Noisy transcript:\n{metrics['noisy_transcript']}\n")
    print(f"[WER] Metrics saved to: {path}")


# ─── Flask metrics endpoint ────────────────────────────────────────────────────

def start_metrics_server(metrics: dict) -> None:
    """Start a simple Flask server exposing the /metrics endpoint."""
    from flask import Flask, jsonify

    app = Flask(__name__)

    @app.route("/metrics")
    def get_metrics():
        return jsonify(metrics)

    print(f"[WER] Metrics server running at http://localhost:{FLASK_PORT}/metrics")
    app.run(host="0.0.0.0", port=FLASK_PORT)


# ─── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Measure Word Error Rate between clean and noisy transcriptions."
    )
    parser.add_argument("--clean", required=True, help="Path to ai-coustics enhanced WAV file")
    parser.add_argument("--noisy", required=True, help="Path to original/noisy WAV file")
    parser.add_argument("--serve", action="store_true", help="Start Flask metrics server after WER computation")
    args = parser.parse_args()

    # Validate files exist
    for path, label in [(args.clean, "clean"), (args.noisy, "noisy")]:
        if not os.path.isfile(path):
            print(f"Error: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    # Run the WER pipeline
    metrics = asyncio.run(run_wer(args.clean, args.noisy))

    # Display and save results
    print_metrics(metrics)
    save_metrics(metrics)

    # Optionally start Flask server
    if args.serve:
        start_metrics_server(metrics)


if __name__ == "__main__":
    main()