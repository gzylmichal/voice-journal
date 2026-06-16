#!/usr/bin/env python3
"""healthcheck.py — Daily self-test for the Voice Journal pipeline.

All green → logs one line, sends nothing.
Any failure → one ntfy push (priority high) listing all failures.

Exit code: 0 = all green, 1 = one or more failures.

Run manually:  python3 healthcheck.py
Systemd:       voice-journal-healthcheck.timer (08:00 daily)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import smtplib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import config
from pipeline.notify import send_notification

logger = logging.getLogger(__name__)

_TIMER_NAMES = [
    "voice-journal-process.timer",
    "voice-journal-debrief.timer",
    "voice-journal-weekly.timer",
]

_STATE_FILE = config.BUFFER_DIR / ".healthcheck_state.json"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_state(state_file: Path) -> dict:
    try:
        if state_file.exists():
            return json.loads(state_file.read_text())
    except Exception:
        pass
    return {}


def _save_state(state: dict, state_file: Path) -> None:
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state))
    except Exception as exc:
        logger.warning("Could not save healthcheck state: %s", exc)


# ---------------------------------------------------------------------------
# Individual checks — each returns (ok: bool, detail: str).
# All accept explicit parameters so they are trivially testable.
# ---------------------------------------------------------------------------

def check_groq(api_key: str):
    if not api_key:
        return False, "GROQ_API_KEY not set"
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 401:
            return False, "Groq key invalid (401)"
        if resp.status_code >= 400:
            return False, f"Groq key check failed ({resp.status_code})"
        return True, "ok"
    except Exception as exc:
        return False, f"Groq unreachable: {exc}"


def check_notion(token: str):
    if not token:
        return True, "skipped (not configured)"
    try:
        resp = requests.get(
            "https://api.notion.com/v1/users/me",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
            },
            timeout=10,
        )
        if resp.status_code == 401:
            return False, "Notion token invalid (401)"
        if resp.status_code >= 400:
            return False, f"Notion token check failed ({resp.status_code})"
        return True, "ok"
    except Exception as exc:
        return False, f"Notion unreachable: {exc}"


def check_ai_key(anthropic_key: str, google_key: str):
    """Check whichever AI key is configured (Anthropic preferred)."""
    if anthropic_key:
        try:
            resp = requests.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=10,
            )
            if resp.status_code == 401:
                return False, "Anthropic key invalid (401)"
            if resp.status_code >= 400:
                return False, f"Anthropic key check failed ({resp.status_code})"
            return True, "Anthropic ok"
        except Exception as exc:
            return False, f"Anthropic unreachable: {exc}"
    elif google_key:
        try:
            resp = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={google_key}",
                timeout=10,
            )
            if resp.status_code in (400, 403):
                return False, f"Gemini key invalid ({resp.status_code})"
            if resp.status_code >= 400:
                return False, f"Gemini key check failed ({resp.status_code})"
            return True, "Gemini ok"
        except Exception as exc:
            return False, f"Gemini unreachable: {exc}"
    else:
        return True, "skipped (no AI key configured)"


def check_smtp(host: str, port: int, user: str, password: str):
    if not host or not user or not password:
        return True, "skipped (not configured)"
    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, password)
        return True, "ok"
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed"
    except Exception as exc:
        return False, f"SMTP unreachable: {exc}"


def check_gcal_token(token_file: Path):
    if not token_file.exists():
        return True, "skipped (token file not present)"
    try:
        data = json.loads(token_file.read_text())
    except Exception as exc:
        return False, f"GCal token unreadable: {exc}"
    if not data.get("refresh_token"):
        return False, "GCal token missing refresh_token — re-run gcal_auth.py"
    # The access token expires ~hourly by design; the pipeline refreshes it on use.
    # What actually matters is whether the refresh_token can still mint a new one,
    # so attempt a real refresh rather than flagging the stale access-token expiry.
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials.from_authorized_user_info(
            data, ["https://www.googleapis.com/auth/calendar"]
        )
        if creds.valid:
            return True, "ok"
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_file.write_text(creds.to_json())  # persist so it self-heals
            return True, "ok (refreshed)"
        return False, "GCal token invalid — re-run gcal_auth.py"
    except Exception as exc:
        return False, f"GCal refresh failed ({exc}) — re-run gcal_auth.py"


def check_inbox_backlog(inbox_dir: Path, max_age_hours: int = 2):
    if not inbox_dir.exists():
        return True, "inbox dir not present (ok off-VPS)"
    _AUDIO_EXT = {".m4a", ".mp3", ".wav", ".mp4", ".ogg", ".flac", ".webm", ".caf"}
    now = datetime.now(timezone.utc).timestamp()
    old_files = []
    for f in inbox_dir.iterdir():
        if f.suffix.lower() in _AUDIO_EXT:
            age_hours = (now - f.stat().st_mtime) / 3600
            if age_hours > max_age_hours:
                old_files.append((f.name, f.stat().st_mtime))
    if old_files:
        oldest_name, oldest_mtime = min(old_files, key=lambda x: x[1])
        oldest_ts = datetime.fromtimestamp(oldest_mtime).strftime("%Y-%m-%d %H:%M")
        return False, f"{len(old_files)} memo(s) stuck, oldest: {oldest_name} from {oldest_ts}"
    return True, "ok"


def check_env_integrity(env_file: Path, example_file: Path, state: dict):
    """All key names in .env.example must exist in .env; warn if .env mtime changed."""
    if not env_file.exists():
        return False, ".env file not found"
    if not example_file.exists():
        return True, "skipped (.env.example not found)"

    def _key_names(path: Path):
        keys = set()
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                keys.add(line.split("=", 1)[0].strip())
        return keys

    example_keys = _key_names(example_file)
    env_keys = _key_names(env_file)
    missing = example_keys - env_keys

    current_mtime = env_file.stat().st_mtime
    last_mtime = state.get("env_mtime")
    mtime_changed = (last_mtime is not None) and (current_mtime != last_mtime)
    state["env_mtime"] = current_mtime

    issues = []
    if missing:
        issues.append(f"missing keys: {', '.join(sorted(missing))}")
    if mtime_changed:
        issues.append(".env was modified since last healthcheck")

    if issues:
        return False, "; ".join(issues)
    return True, "ok"


def check_timers(timer_names: list):
    """Verify systemd timers are enabled. Skips gracefully when systemctl absent."""
    failed = []
    for name in timer_names:
        try:
            result = subprocess.run(
                ["systemctl", "is-enabled", name],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                failed.append(f"{name}: not enabled")
        except FileNotFoundError:
            return True, "skipped (no systemctl)"
        except Exception as exc:
            return True, f"skipped ({exc})"
    if failed:
        return False, "; ".join(failed)
    return True, "ok"


def check_disk(path: Path, min_free_gb: float = 1.0):
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < min_free_gb:
            return False, f"only {free_gb:.1f} GB free (need {min_free_gb:.0f} GB)"
        return True, f"{free_gb:.1f} GB free"
    except Exception as exc:
        return False, f"disk check error: {exc}"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_healthcheck(state_file: Path = _STATE_FILE):
    """Run all checks. Returns list of (name, ok, detail)."""
    state = _load_state(state_file)

    base_dir = config.BASE_DIR if config.BASE_DIR.exists() else Path("/")
    env_file = Path(__file__).parent / ".env"
    example_file = Path(__file__).parent / ".env.example"

    results = [
        ("Groq key",       *check_groq(config.GROQ_API_KEY)),
        ("Notion token",   *check_notion(config.NOTION_TOKEN)),
        ("AI key",         *check_ai_key(config.ANTHROPIC_API_KEY, config.GOOGLE_API_KEY)),
        ("SMTP",           *check_smtp(
            os.getenv("SMTP_HOST", ""),
            int(os.getenv("SMTP_PORT", "587")),
            os.getenv("SMTP_USER", ""),
            os.getenv("SMTP_PASSWORD", ""),
        )),
        ("GCal token",     *check_gcal_token(config.GCAL_TOKEN_FILE)),
        ("Inbox backlog",  *check_inbox_backlog(config.INBOX_DIR)),
        (".env integrity", *check_env_integrity(env_file, example_file, state)),
        ("Systemd timers", *check_timers(_TIMER_NAMES)),
        ("Disk space",     *check_disk(base_dir)),
    ]

    _save_state(state, state_file)
    return results


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    results = run_healthcheck()

    failures = [(name, detail) for name, ok, detail in results if not ok]

    if not failures:
        print("healthcheck: all green")
        return 0

    lines = ["Health check FAILED:"] + [f"  - {name}: {detail}" for name, detail in failures]
    message = "\n".join(lines)
    print(message)
    send_notification(message, title="Voice Journal Alert", priority="high")
    return 1


if __name__ == "__main__":
    sys.exit(main())
