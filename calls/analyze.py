#!/usr/bin/env python3
"""
Watch a growing transcript.txt file and call Gemini every 5 seconds
for real-time 911 call analysis. Designed to run alongside stream_transcribe.py.

Usage:
    # Terminal 1: stream the audio
    python stream_transcribe.py caller_audio.wav

    # Terminal 2: analyze as it arrives
    python analyze.py transcript.txt
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime

from dotenv import load_dotenv
from google import genai
from speak import speak

# ─── Configuration ──────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash"
POLL_INTERVAL = 15
ANALYSIS_LOG = "analysis_log.json"

# The system prompt tells Gemini exactly what JSON structure to return.
SYSTEM_PROMPT = """You are an AI assistant helping a 911 dispatcher analyze an emergency call in real time.
Analyze the following transcript and return ONLY a valid JSON object with exactly these fields:

{
  "sentiment": <float from -1.0 (extreme panic/distress) to 1.0 (calm)>,
  "urgency": <"low", "medium", "high", or "critical">,
  "emergency_type": <"fire", "medical", "assault", "missing_person", "accident", or "unknown">,
  "summary": <one sentence describing what is happening>,
  "dispatcher_action": <one short instruction for the dispatcher e.g. "Send fire department to 3401 immediately">,
  "key_info": {
    "address": <extracted address or null>,
    "people_involved": <number or null>,
    "immediate_danger": <true or false>
  }
}

Return only valid JSON. No explanation. No markdown. No backticks."""

# ─── Urgency display helpers ────────────────────────────────────────────────────

URGENCY_SYMBOL = {
    "low": "LOW    🟢",
    "medium": "MEDIUM 🟡",
    "high": "HIGH   🟠",
    "critical": "CRITICAL 🔴",
}

SENTIMENT_LABEL = {
    (0.6, 1.0): "calm",
    (0.2, 0.6): "steady",
    (-0.2, 0.2): "neutral",
    (-0.6, -0.2): "anxious",
    (-1.0, -0.6): "extreme distress",
}


def sentiment_label(value: float) -> str:
    """Convert a sentiment float to a human-readable label."""
    for (lo, hi), label in SENTIMENT_LABEL.items():
        if lo <= value <= hi:
            return label
    return "unknown"


# ─── Transcript watcher ─────────────────────────────────────────────────────────


def read_transcript(path: str) -> str:
    """Read the full transcript file, returning empty string if it doesn't exist yet."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def extract_content_after_header(text: str) -> str:
    """Strip the timestamp header lines from transcript.txt, return just the transcript text."""
    lines = text.strip().splitlines()
    # Skip header lines (everything before the === separator line)
    content_start = 0
    for i, line in enumerate(lines):
        if line.startswith("==="):
            content_start = i + 1
            break
    return "\n".join(lines[content_start:]).strip()


# ─── Gemini API call ─────────────────────────────────────────────────────────────


def call_gemini(client: genai.Client, transcript: str) -> dict | None:
    """Send the transcript to Gemini and parse the JSON response.

    Returns the parsed dict on success, or None on any error.
    """
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"Transcript so far:\n{transcript}",
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.0,
            ),
        )
        raw = response.text.strip()

        # Gemini sometimes wraps JSON in ```json ... ``` blocks — strip those
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]  # remove first line
            raw = raw.rsplit("```", 1)[0]  # remove closing ```
            raw = raw.strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        print(f"      [Gemini] Failed to parse JSON: {e}")
        return None
    except Exception as e:
        print(f"      [Gemini] API error: {e}")
        return None


# ─── Display formatting ─────────────────────────────────────────────────────────


def format_time_elapsed(seconds: float) -> str:
    """Format seconds as M:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def print_analysis(analysis: dict, elapsed: float) -> None:
    """Print a formatted analysis block to the terminal."""
    sentiment = analysis.get("sentiment", 0)
    urgency = analysis.get("urgency", "unknown").lower()
    emergency = analysis.get("emergency_type", "unknown")
    summary = analysis.get("summary", "")
    action = analysis.get("dispatcher_action", "")
    key_info = analysis.get("key_info", {})

    address = key_info.get("address")
    people = key_info.get("people_involved")
    danger = key_info.get("immediate_danger", False)

    urgency_display = URGENCY_SYMBOL.get(urgency, urgency.upper())
    danger_display = "YES" if danger else "no"
    address_display = str(address) if address else "—"
    people_display = str(people) if people is not None else "unknown"

    divider = "━" * 40
    print(f"\n{divider}")
    print(f"[ANALYSIS - {format_time_elapsed(elapsed)}]")
    print(f"Urgency:      {urgency_display}")
    print(f"Emergency:    {emergency}")
    print(f"Sentiment:    {sentiment:.1f} ({sentiment_label(sentiment)})")
    print(f"Address:      {address_display}")
    print(f"Danger:       {danger_display}")
    print(f"People:       {people_display}")
    print(f"Summary:      {summary}")
    print(f"Action:       {action}")
    print(divider)


# ─── Analysis log persistence ────────────────────────────────────────────────────


def save_to_log(log_path: str, entry: dict) -> None:
    """Append an analysis entry to the JSON log file."""
    # Load existing log or start fresh
    if os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []
    else:
        log = []

    log.append(entry)

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


# ─── Main loop ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Watch a growing transcript file and analyze it with Gemini in real time."
    )
    parser.add_argument("transcript", help="Path to transcript.txt file to watch")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Path for analysis_log.json (default: same directory as transcript)",
    )
    args = parser.parse_args()

    transcript_path = args.transcript
    if not os.path.isfile(transcript_path):
        # File might not exist yet — we'll wait for it
        print(
            f"Watching for: {transcript_path} (will appear when transcription starts)"
        )

    log_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(transcript_path)), ANALYSIS_LOG
    )

    # Load Gemini API key from .env
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "Error: GEMINI_API_KEY not found. "
            "Add it to your .env file (see .env.example).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load Gradium API key for TTS
    gradium_api_key = os.environ.get("GRADIUM_API_KEY")

    # Initialize Gemini client
    client = genai.Client(api_key=api_key)
    print(f"[Gemini] Connected — model: {GEMINI_MODEL}")
    print(f"[Watch ] Monitoring: {transcript_path}")
    print(f"[Log   ] Saving to: {log_path}")
    print(f"[Poll  ] Checking every {POLL_INTERVAL}s for new transcript content\n")

    last_content = ""  # Track what we've already sent to Gemini
    last_spoken_urgency = None  # Track last spoken urgency to avoid repeats
    auto_dispatched = False  # Track whether we've already auto-dispatched
    start_time = time.time()

    while True:
        try:
            # Read the current transcript file
            raw_text = read_transcript(transcript_path)

            # Extract just the transcript content (skip header)
            current_content = extract_content_after_header(raw_text)

            # Only call Gemini if new text has appeared since last call
            if current_content and current_content != last_content:
                last_content = current_content
                elapsed = time.time() - start_time

                print(
                    f"[{format_time_elapsed(elapsed)}] New transcript text detected — calling Gemini..."
                )
                analysis = call_gemini(client, current_content)

                if analysis:
                    print_analysis(analysis, elapsed)

                    # Save to log
                    log_entry = {
                        "timestamp": datetime.now().isoformat(),
                        "elapsed_s": round(elapsed, 1),
                        "analysis": analysis,
                    }
                    save_to_log(log_path, log_entry)

                    # TTS alerts — only two situations
                    urgency = analysis.get("urgency", "unknown").lower()

                    # Only speak when urgency becomes critical for the first time
                    if urgency == "critical" and last_spoken_urgency != "critical":
                        last_spoken_urgency = "critical"
                        emergency = analysis.get("emergency_type", "emergency")
                        address = analysis.get("key_info", {}).get("address")
                        if address:
                            alert = f"Critical. {emergency}. {address}."
                        else:
                            alert = f"Critical {emergency} detected."
                        threading.Thread(target=speak, args=(alert, gradium_api_key), daemon=True).start()
                        print(f"[TTS] {alert}")

                    # Only speak when auto-dispatching (on a subsequent cycle after critical)
                    elif urgency == "critical" and auto_dispatched is False and last_spoken_urgency == "critical":
                        auto_dispatched = True
                        address = analysis.get("key_info", {}).get("address", "location confirmed")
                        alert = f"Units dispatched to {address}."
                        threading.Thread(target=speak, args=(alert, gradium_api_key), daemon=True).start()
                        print(f"[TTS] {alert}")
                else:
                    print("      [Gemini] No valid response — will retry next cycle")
            # else: no new content, skip this cycle

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n[Stopped] Interrupted by user. Saving final log.")
            sys.exit(0)
        except Exception as e:
            print(f"[Error] {e} — retrying in {POLL_INTERVAL}s", file=sys.stderr)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
