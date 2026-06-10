#!/usr/bin/env python3
"""
Voice Journal — Audio Receiver
================================
Tiny HTTP endpoint that accepts audio file uploads from the iOS Shortcut.
Authenticates via bearer token, saves files to the inbox directory.

Run directly for testing:
    python3 receiver.py

Production: use the systemd unit (voice-journal-receiver.service)
"""

import os
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UPLOAD_TOKEN  = os.getenv("UPLOAD_TOKEN")   # shared secret with iOS Shortcut
INBOX_DIR     = Path(os.getenv("INBOX_DIR", "/opt/voice-journal/inbox"))
PORT          = int(os.getenv("RECEIVER_PORT", "8675"))
VENV_PYTHON   = Path(os.getenv("VENV_PYTHON", "/opt/voice-journal/venv/bin/python3"))
PIPELINE_SCRIPT = Path(__file__).parent / "voice_journal.py"
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB (Groq free tier limit anyway)

ALLOWED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".mp4", ".ogg", ".flac", ".webm", ".caf"}

PREVIEW_FILES  = {"debrief-preview.html", "weekly-preview.html"}
BASE_DIR       = Path(__file__).parent

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

LOG_FILE = Path(__file__).parent / "receiver.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("receiver")


def verify_token():
    """Check bearer token from Authorization header."""
    if not UPLOAD_TOKEN:
        log.error("UPLOAD_TOKEN not set in .env — rejecting all requests")
        return False
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {UPLOAD_TOKEN}"


def _verify_preview_token() -> bool:
    """Accept token via query param or Authorization header (for browser access)."""
    if not UPLOAD_TOKEN:
        return False
    query_token = request.args.get("token", "")
    header_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return UPLOAD_TOKEN in (query_token, header_token)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Health check — no auth required."""
    return jsonify({"status": "ok", "inbox": str(INBOX_DIR)}), 200


@app.route("/upload", methods=["POST"])
def upload():
    """Accept an audio file upload."""

    # Auth check
    if not verify_token():
        log.warning(f"Unauthorized upload attempt from {request.remote_addr}")
        return jsonify({"error": "unauthorized"}), 401

    # Accept multipart upload (curl/web) or raw binary body (iOS Shortcuts)
    if "file" in request.files:
        file = request.files["file"]
        ext = Path(file.filename).suffix.lower() if file.filename else ".m4a"
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({"error": f"unsupported format: {ext}"}), 400
        audio_data = file.read()
    elif request.data:
        ct_map = {
            "audio/x-m4a": ".m4a", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
            "audio/wav": ".wav", "audio/ogg": ".ogg", "audio/flac": ".flac",
            "audio/webm": ".webm", "audio/x-caf": ".caf",
        }
        ct = (request.content_type or "").split(";")[0].strip()
        ext = ct_map.get(ct, ".m4a")
        audio_data = request.data
    else:
        return jsonify({"error": "no file in request"}), 400

    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_name = f"{timestamp}{ext}"
    dest = INBOX_DIR / safe_name

    # Save
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(audio_data)

    file_size_kb = dest.stat().st_size / 1024
    log.info(f"Received: {safe_name} ({file_size_kb:.0f} KB) from {request.remote_addr}")


    # Trigger the pipeline immediately in the background (non-blocking).
    # --mode upload: transcribes, writes workout/tasks/calendar to Notion/GCal,
    # buffers transcript for the overnight journal consolidation.
    try:
        log_fh = open(Path(__file__).parent / "voice_journal.log", "a")
        subprocess.Popen(
            [str(VENV_PYTHON), str(PIPELINE_SCRIPT), "--mode", "upload"],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
        log_fh.close()
        log.info("Pipeline triggered: --mode upload")
    except Exception as exc:
        log.error(f"Failed to trigger pipeline: {exc}")
        # Don't fail the upload response — file is saved, pipeline can run later

    return jsonify({
        "status": "saved",
        "filename": safe_name,
        "size_kb": round(file_size_kb),
        "pipeline": "triggered"
    }), 200


@app.route("/preview/<filename>", methods=["GET"])
def preview(filename: str):
    """Serve a generated preview HTML file. Auth via ?token= or Authorization header."""
    if filename not in PREVIEW_FILES:
        return jsonify({"error": "not found"}), 404
    if not _verify_preview_token():
        log.warning(f"Unauthorized preview request from {request.remote_addr}")
        return jsonify({"error": "unauthorized"}), 401
    path = BASE_DIR / filename
    if not path.exists():
        return jsonify({"error": f"{filename} not generated yet — run preview first"}), 404
    log.info(f"Preview served: {filename} to {request.remote_addr}")
    return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": f"file too large (max {MAX_FILE_SIZE // 1024 // 1024} MB)"}), 413


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not UPLOAD_TOKEN:
        log.error("UPLOAD_TOKEN not set. Generate one: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        exit(1)

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Receiver starting on port {PORT}")
    log.info(f"Inbox: {INBOX_DIR}")

    # For testing only — production uses gunicorn behind nginx/caddy
    app.run(host="0.0.0.0", port=PORT)
