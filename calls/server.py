#!/usr/bin/env python3
"""
Trace911 Flask API Server — bridges the Python backend with the Lovable dashboard.

The frontend dashboard (React, running on a different port) calls these endpoints
to get live transcript data, Gemini analysis results, WER metrics, and server status.

All data comes from files written by the other scripts:
  - transcript.txt   ← stream_transcribe.py writes this in real time
  - analysis_log.json ← analyze.py appends entries as Gemini responds
  - metrics.txt       ← wer.py writes WER comparison results

Usage:
    python server.py           # Start the server on port 5000
    python server.py --test     # Test all endpoints without starting the server
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

# ─── File paths (overridable via .env) ─────────────────────────────────────────
# server.py lives inside calls/ so BASE_DIR is already the calls directory.

load_dotenv()

CALLS_DIR = os.path.dirname(os.path.abspath(__file__))

# File paths — all inside CALLS_DIR
TRANSCRIPT_FILE = os.environ.get(
    "TRANSCRIPT_FILE", os.path.join(CALLS_DIR, "transcript.txt")
)
ANALYSIS_FILE = os.environ.get(
    "ANALYSIS_FILE", os.path.join(CALLS_DIR, "analysis_log.json")
)
METRICS_FILE = os.environ.get("METRICS_FILE", os.path.join(CALLS_DIR, "metrics.txt"))
DEMO_AUDIO_FILE = os.path.join(CALLS_DIR, "enhanced_audio.wav")
TTS_STATUS_FILE = os.path.join(CALLS_DIR, "tts_status.txt")

# Subprocess paths
TRANSCRIBE_SCRIPT = os.path.join(CALLS_DIR, "stream_transcribe.py")
ANALYZE_SCRIPT = os.path.join(CALLS_DIR, "analyze.py")

PORT = int(os.environ.get("PORT", "5000"))

# ─── Flask app setup ───────────────────────────────────────────────────────────
# CORS (Cross-Origin Resource Sharing) is required because the Lovable dashboard
# runs on a different port (e.g. localhost:5173). Without CORS, the browser would
# block requests from the frontend to this API server.

app = Flask(__name__)
CORS(app)  # Allow all origins — safe for local dev


# ─── Endpoint 1: GET /transcript ────────────────────────────────────────────────
# Reads transcript.txt and returns the last 20 lines of clean text.
# The transcript file has lines like: [TRANSCRIPT  0:03] yeah we got a fire
# We strip the timestamp prefix and return only the spoken words.


@app.route("/transcript")
def get_transcript():
    try:
        if not os.path.isfile(TRANSCRIPT_FILE):
            return jsonify({"success": False, "lines": [], "total_words": 0})

        with open(TRANSCRIPT_FILE, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()

        # Strip empty lines and extract clean text
        clean_lines = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            # Strip timestamp prefixes like [TRANSCRIPT  0:03]
            if "]" in line:
                line = line.split("]", 1)[1].strip()
            # Skip header lines (timestamp, duration, === separator)
            if (
                line.startswith("Transcript")
                or line.startswith("Duration")
                or line.startswith("===")
            ):
                continue
            if line:
                clean_lines.append(line)

        # Keep only the last 20 lines
        recent_lines = clean_lines[-20:]
        total_words = sum(len(line.split()) for line in clean_lines)

        return jsonify(
            {
                "success": True,
                "lines": recent_lines,
                "total_words": total_words,
            }
        )

    except Exception:
        return jsonify({"success": False, "lines": [], "total_words": 0})


# ─── Endpoint 2: GET /analysis ─────────────────────────────────────────────────
# Reads analysis_log.json and returns the most recent analysis entry.
# The file is a JSON array — we take the last item for the latest results.


@app.route("/analysis")
def get_analysis():
    # Safe defaults if the file doesn't exist yet or can't be read
    default_response = {
        "success": False,
        "sentiment": 0,
        "urgency": "unknown",
        "emergency_type": "unknown",
        "summary": "Waiting for call data...",
        "dispatcher_action": "",
        "key_info": {
            "address": None,
            "people_involved": None,
            "immediate_danger": False,
        },
    }

    try:
        if not os.path.isfile(ANALYSIS_FILE):
            return jsonify(default_response)

        with open(ANALYSIS_FILE, "r", encoding="utf-8") as f:
            log = json.load(f)

        if not log:
            return jsonify(default_response)

        # Get the most recent entry
        latest = log[-1]
        analysis = latest.get("analysis", {})

        return jsonify(
            {
                "success": True,
                "sentiment": analysis.get("sentiment", 0),
                "urgency": analysis.get("urgency", "unknown"),
                "emergency_type": analysis.get("emergency_type", "unknown"),
                "summary": analysis.get("summary", ""),
                "dispatcher_action": analysis.get("dispatcher_action", ""),
                "key_info": analysis.get(
                    "key_info",
                    {
                        "address": None,
                        "people_involved": None,
                        "immediate_danger": False,
                    },
                ),
                "timestamp": latest.get("timestamp", ""),
            }
        )

    except Exception:
        return jsonify(default_response)


# ─── Endpoint 3: GET /metrics ───────────────────────────────────────────────────
# Reads metrics.txt and parses WER numbers from the text file.


@app.route("/metrics")
def get_metrics():
    default_response = {
        "success": False,
        "wer_with_aic": 0,
        "wer_without_aic": 0,
        "improvement": 0,
        "error_reduction_pct": 0,
        "words_clean": 0,
        "words_noisy": 0,
    }

    try:
        if not os.path.isfile(METRICS_FILE):
            return jsonify(default_response)

        with open(METRICS_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse key values from the metrics text file
        wer_value = 0.0
        words_clean = 0
        words_noisy = 0

        for line in content.splitlines():
            line_lower = line.lower().strip()
            if line_lower.startswith("wer:"):
                # "WER:              3.1%" → extract the number
                num_part = line.split(":")[-1].strip().replace("%", "")
                try:
                    wer_value = float(num_part)
                except ValueError:
                    pass
            elif line_lower.startswith("clean words:"):
                num_part = line.split(":")[-1].strip()
                try:
                    words_clean = int(num_part)
                except ValueError:
                    pass
            elif line_lower.startswith("noisy words:"):
                num_part = line.split(":")[-1].strip()
                try:
                    words_noisy = int(num_part)
                except ValueError:
                    pass

        # WER from the file measures how different noisy is from clean.
        # This represents the error rate WITHOUT ai-coustics (the noisy transcript).
        # wer_with_aic would require a ground-truth reference transcript.
        wer_without_aic = wer_value

        return jsonify(
            {
                "success": True,
                "wer_with_aic": 0,
                "wer_without_aic": round(wer_without_aic, 2),
                "improvement": 0,
                "error_reduction_pct": 0,
                "words_clean": words_clean,
                "words_noisy": words_noisy,
            }
        )

    except Exception:
        return jsonify(default_response)


# ─── Endpoint 4: GET /status ───────────────────────────────────────────────────
# Health check — shows whether each data file exists and when it was last updated.


@app.route("/status")
def get_status():
    try:
        files_info = {}
        for label, path in [
            ("transcript", TRANSCRIPT_FILE),
            ("analysis", ANALYSIS_FILE),
            ("metrics", METRICS_FILE),
        ]:
            if os.path.isfile(path):
                mtime = os.path.getmtime(path)
                last_updated = datetime.fromtimestamp(mtime).strftime("%H:%M:%S")
                files_info[label] = {"exists": True, "last_updated": last_updated}
            else:
                files_info[label] = {"exists": False, "last_updated": None}

        return jsonify(
            {
                "success": True,
                "status": "running",
                "files": files_info,
            }
        )

    except Exception:
        return jsonify(
            {
                "success": True,
                "status": "running",
                "files": {
                    "transcript": {"exists": False, "last_updated": None},
                    "analysis": {"exists": False, "last_updated": None},
                    "metrics": {"exists": False, "last_updated": None},
                },
            }
        )


# ─── Endpoint 5: GET /tts_status ────────────────────────────────────────────────
# Check whether the TTS engine is currently speaking.


@app.route("/tts_status")
def get_tts_status():
    try:
        if os.path.isfile(TTS_STATUS_FILE):
            with open(TTS_STATUS_FILE, "r") as f:
                status = f.read().strip()
            return jsonify({"speaking": status == "speaking"})
    except Exception:
        pass
    return jsonify({"speaking": False})


# ─── Endpoint 6: POST /start ───────────────────────────────────────────────────
# Triggered by the Demo Call button on the dashboard.
# Starts the full pipeline: transcription first, then analysis after a short delay.

# Track running processes so we can stop them later
running_processes = []


@app.route("/start", methods=["POST"])
def start_demo():
    global running_processes

    # Kill any previously running pipeline first
    for proc in running_processes:
        try:
            proc.terminate()
        except Exception:
            pass
    running_processes = []

    # Clear old transcript so dashboard starts fresh
    transcript_path = os.path.join(CALLS_DIR, "transcript.txt")
    if os.path.isfile(transcript_path):
        open(transcript_path, "w").close()

    def run_pipeline():
        global running_processes

        # Start transcription with absolute paths
        transcribe_proc = subprocess.Popen(
            [sys.executable, TRANSCRIBE_SCRIPT, DEMO_AUDIO_FILE], cwd=CALLS_DIR
        )
        running_processes.append(transcribe_proc)

        # Wait 3 seconds for transcript.txt to be created
        time.sleep(3)

        # Start Gemini analysis with absolute paths
        analyze_proc = subprocess.Popen(
            [sys.executable, ANALYZE_SCRIPT, "transcript.txt"], cwd=CALLS_DIR
        )
        running_processes.append(analyze_proc)

        # Wait for both to finish
        transcribe_proc.wait()
        analyze_proc.terminate()

    # Run in background thread so Flask doesn't block
    threading.Thread(target=run_pipeline, daemon=True).start()

    return jsonify({"success": True, "message": "Demo call started"})


# ─── Endpoint 6: POST /stop ───────────────────────────────────────────────────
# Stops all running pipeline processes cleanly.


@app.route("/stop", methods=["POST"])
def stop_demo():
    global running_processes
    for proc in running_processes:
        try:
            proc.terminate()
        except Exception:
            pass
    running_processes = []
    return jsonify({"success": True, "message": "Demo stopped"})


# ─── Endpoint 7: POST /reset ──────────────────────────────────────────────────
# Stops all processes and deletes generated files completely for a fresh start.


@app.route("/reset", methods=["POST"])
def reset_demo():
    global running_processes

    # Step 1 — Kill any running pipeline processes
    for proc in running_processes:
        try:
            proc.terminate()
        except Exception:
            pass
    running_processes = []

    # Step 2 — Delete generated files completely
    files_to_delete = [
        os.path.join(CALLS_DIR, "transcript.txt"),
        os.path.join(CALLS_DIR, "analysis_log.json"),
        os.path.join(CALLS_DIR, "tts_status.txt"),
    ]

    for filepath in files_to_delete:
        if os.path.isfile(filepath):
            os.remove(filepath)
            print(f"[Reset] Deleted: {filepath}")

    print("[Reset] Demo reset complete — ready for next call")
    return jsonify({"success": True, "message": "Demo reset complete"})


# ─── Test mode ─────────────────────────────────────────────────────────────────
# Calls all 4 endpoints locally and prints results without starting the server.


def run_test():
    """Test all endpoints by calling them directly through Flask's test client."""
    client = app.test_client()

    print("\n[TEST] Running endpoint checks...\n")

    # Test /status
    resp = client.get("/status")
    data = resp.get_json()
    status_str = data.get("status", "unknown")
    print(f"[TEST] GET /status     → {'✅' if data['success'] else '❌'} {status_str}")

    # Test /transcript
    resp = client.get("/transcript")
    data = resp.get_json()
    line_count = len(data.get("lines", []))
    word_count = data.get("total_words", 0)
    print(
        f"[TEST] GET /transcript → {'✅' if data['success'] else '❌'} {line_count} lines, {word_count} words"
    )

    # Test /analysis
    resp = client.get("/analysis")
    data = resp.get_json()
    urgency = data.get("urgency", "unknown").upper()
    etype = data.get("emergency_type", "unknown")
    address = data.get("key_info", {}).get("address") or "—"
    print(
        f"[TEST] GET /analysis   → {'✅' if data['success'] else '❌'} {urgency} | {etype} | {address}"
    )

    # Test /metrics
    resp = client.get("/metrics")
    data = resp.get_json()
    wer_clean = data.get("wer_with_aic", 0)
    wer_noisy = data.get("wer_without_aic", 0)
    print(
        f"[TEST] GET /metrics    → {'✅' if data['success'] else '❌'} WER clean: {wer_clean}% | noisy: {wer_noisy}%"
    )

    print()


# ─── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trace911 Flask API Server")
    parser.add_argument(
        "--test", action="store_true", help="Test all endpoints without starting server"
    )
    args = parser.parse_args()

    if args.test:
        run_test()
    else:
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("[Trace911] Flask API Server")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("Endpoints:")
        print(f"  GET  http://localhost:{PORT}/transcript")
        print(f"  GET  http://localhost:{PORT}/analysis")
        print(f"  GET  http://localhost:{PORT}/metrics")
        print(f"  GET  http://localhost:{PORT}/status")
        print(f"  GET  http://localhost:{PORT}/tts_status")
        print(f"  POST http://localhost:{PORT}/start")
        print(f"  POST http://localhost:{PORT}/stop")
        print(f"  POST http://localhost:{PORT}/reset")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
