#!/usr/bin/env python3
"""Clean 911 call audio: convert MP3 to 16kHz mono WAV, trim dispatcher intro, then enhance with ai-coustics."""

import argparse
import os
import sys
import tempfile

import numpy as np
import soundfile as sf
from dotenv import load_dotenv
from pydub import AudioSegment
from pydub.silence import detect_silence

import aic_sdk as aic

MODEL_ID = "quail-vf-2.1-l-16khz"
TARGET_SAMPLE_RATE = 16000
# Silence detection parameters for trimming dispatcher intro
SILENCE_MIN_LEN_MS = 400   # minimum pause duration to count as silence
SILENCE_THRESH_DBFS = -40  # volume threshold in dBFS


def convert_mp3_to_wav(mp3_path: str, wav_path: str) -> None:
    """Convert an MP3 file to 16kHz mono WAV using pydub, trimming the dispatcher intro.

    Detects the first silent gap (the natural pause between dispatcher and caller)
    and discards everything before it so ai-coustics optimizes for the caller's voice.
    """
    print(f"[1/5] Converting {mp3_path} to 16kHz mono WAV...")
    audio = AudioSegment.from_mp3(mp3_path)
    original_duration = len(audio) / 1000.0
    print(f"      Original: {original_duration:.1f}s")

    # Convert to 16kHz mono
    audio = audio.set_frame_rate(TARGET_SAMPLE_RATE).set_channels(1)

    # Trim dispatcher intro: find the first silent gap and start from after it
    print(f"[2/5] Detecting silence (min {SILENCE_MIN_LEN_MS}ms, thresh {SILENCE_THRESH_DBFS}dBFS)...")
    silences = detect_silence(
        audio,
        min_silence_len=SILENCE_MIN_LEN_MS,
        silence_thresh=SILENCE_THRESH_DBFS,
    )

    if silences:
        first_pause_start, first_pause_end = silences[0]
        caller_start_ms = first_pause_end
        trimmed = audio[caller_start_ms:]
        print(f"      First silence at {first_pause_start}-{first_pause_end}ms, "
              f"trimming {caller_start_ms}ms of dispatcher intro")
        print(f"      Trimmed: {len(trimmed) / 1000.0:.1f}s (removed "
              f"{caller_start_ms / 1000.0:.1f}s)")
        audio = trimmed
    else:
        print("      No silence detected — using full audio (no dispatcher trim)")

    audio.export(wav_path, format="wav")
    duration = len(audio) / 1000.0
    print(f"      Output: {duration:.1f}s at {TARGET_SAMPLE_RATE}Hz mono")


def enhance_wav(wav_path: str, output_path: str, license_key: str) -> None:
    """Enhance a WAV file using the ai-coustics SDK."""
    print(f"[3/5] Loading model '{MODEL_ID}'...")
    model_path = aic.Model.download(MODEL_ID, "./models")
    model = aic.Model.from_file(model_path)
    print(f"      Model loaded: {model.get_id()}")

    # Load the WAV file
    print(f"[4/5] Processing audio through ai-coustics enhancement...")
    audio_input, sample_rate = sf.read(wav_path, dtype="float32")

    # Ensure shape is (channels, frames) — mono comes in as 1D
    if audio_input.ndim == 1:
        audio_input = audio_input.reshape(1, -1)
        num_channels = 1
    else:
        audio_input = audio_input.T
        num_channels = audio_input.shape[0]

    config = aic.ProcessorConfig.optimal(
        model, sample_rate=sample_rate, num_channels=num_channels
    )
    processor = aic.Processor(model, license_key, config)
    proc_ctx = processor.get_processor_context()
    proc_ctx.reset()

    # Pad the start with silence to compensate for algorithmic latency
    latency_samples = proc_ctx.get_output_delay()
    padding = np.zeros((num_channels, latency_samples), dtype=np.float32)
    audio_padded = np.concatenate([padding, audio_input], axis=1)

    # Process in chunks matching the model's optimal frame size
    num_frames_model = config.num_frames
    num_frames_total = audio_padded.shape[1]
    output = np.zeros_like(audio_padded)

    num_chunks = (num_frames_total + num_frames_model - 1) // num_frames_model
    chunk_idx = 0

    for chunk_start in range(0, num_frames_total, num_frames_model):
        chunk_end = min(chunk_start + num_frames_model, num_frames_total)
        chunk = audio_padded[:, chunk_start:chunk_end]

        # Pad last chunk to full frame size if needed
        valid_samples = chunk.shape[1]
        if valid_samples < num_frames_model:
            process_buffer = np.zeros(
                (num_channels, num_frames_model), dtype=np.float32
            )
            process_buffer[:, :valid_samples] = chunk
            processed = processor.process(process_buffer)
            output[:, chunk_start : chunk_start + valid_samples] = processed[
                :, :valid_samples
            ]
        else:
            processed = processor.process(chunk)
            output[:, chunk_start:chunk_end] = processed

        chunk_idx += 1
        if chunk_idx % 50 == 0 or chunk_idx == num_chunks:
            print(f"      Processed chunk {chunk_idx}/{num_chunks}")

    # Remove the latency padding from the output
    output = output[:, latency_samples:]

    # Write output — soundfile expects (frames, channels)
    sf.write(output_path, output.T, sample_rate)
    duration = output.shape[1] / sample_rate
    print(f"[5/5] Done! Cleaned audio saved to: {output_path}")
    print(f"      Duration: {duration:.1f}s | Sample rate: {sample_rate}Hz | Channels: {num_channels}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert MP3 to 16kHz mono WAV and clean audio with ai-coustics."
    )
    parser.add_argument("input", help="Path to input .mp3 file")
    parser.add_argument(
        "-o", "--output", default=None,
        help="Path for cleaned output WAV file (default: <input>_cleaned.wav)",
    )
    args = parser.parse_args()

    input_path = args.input
    if not os.path.isfile(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        base, _ = os.path.splitext(input_path)
        output_path = f"{base}_cleaned.wav"

    # Load license key from .env
    load_dotenv()
    license_key = os.environ.get("AIC_SDK_LICENSE")
    if not license_key:
        print(
            "Error: AIC_SDK_LICENSE not found. "
            "Add it to your .env file (see .env.example).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Convert MP3 → WAV, then enhance
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav_path = tmp.name

    try:
        convert_mp3_to_wav(input_path, tmp_wav_path)
        enhance_wav(tmp_wav_path, output_path, license_key)
    finally:
        if os.path.exists(tmp_wav_path):
            os.unlink(tmp_wav_path)


if __name__ == "__main__":
    main()