#!/usr/bin/env python3
"""smoke_test.py — Offline end-to-end check of the whole upload→overnight path.

Unlike the unit tests (which mock at the function level and can silently encode
wrong assumptions), this exercises the REAL wiring: receiver endpoint → inbox →
run_upload_mode → buffer/archive → run_overnight_mode → markdown. Only the
network boundary (Groq, Notion HTTP) is faked.

Run:    python3 smoke_test.py
Exit 0 = pass, 1 = fail. No network, no real API keys needed.

MUST pass before any change is considered done, and before every deploy.
"""

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Isolated environment — must be set BEFORE any pipeline import.
# load_dotenv() does not override existing env vars, so a real .env is ignored.
# ---------------------------------------------------------------------------
TMP = Path(tempfile.mkdtemp(prefix="vj-smoke-"))
os.environ.update({
    "BASE_DIR": str(TMP),
    "INBOX_DIR": str(TMP / "inbox"),
    "GROQ_API_KEY": "smoke-test-key",
    "UPLOAD_TOKEN": "smoke-test-token",
    "NOTION_TOKEN": "smoke-test-token",
    "NOTION_DATABASE_ID": "db-journal",
    "NOTION_WORKOUT_DB_ID": "db-workout",
    "NOTION_TASK_DB_ID": "db-task",
    "NOTION_BODYWEIGHT_DB_ID": "db-bw",
    "AI_PROVIDER": "groq",
})
sys.path.insert(0, str(Path(__file__).parent))

import voice_journal  # noqa: E402
from pipeline import config  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    print(f"  [{'ok' if cond else 'FAIL'}] {name}{' — ' + detail if detail and not cond else ''}")
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Fakes — keep these matching the REAL API response shapes.
# Groq verbose_json: object with .text and .segments (list of dicts).
# Notion: requests.Response with .status_code and .json().
# ---------------------------------------------------------------------------

class FakeTranscription:
    text = "Bench press 80 kilos, 8 reps, 3 sets. I weighed myself today, 82.5 kilos. Thanks for watching."
    segments = [
        {"text": " Bench press 80 kilos, 8 reps, 3 sets.",
         "no_speech_prob": 0.01, "avg_logprob": -0.25, "compression_ratio": 1.4},
        {"text": " I weighed myself today, 82.5 kilos.",
         "no_speech_prob": 0.02, "avg_logprob": -0.30, "compression_ratio": 1.3},
        # Classic silence hallucination — the filter must drop this:
        {"text": " Thanks for watching.",
         "no_speech_prob": 0.95, "avg_logprob": -0.80, "compression_ratio": 1.1},
    ]


class FakeGroq:
    def __init__(self, api_key=None):
        self.audio = MagicMock()
        self.audio.transcriptions.create = MagicMock(return_value=FakeTranscription())


_CANNED_WORKOUT = {
    "detected": True,
    "workout_name": "Push day",
    "exercises": [{
        "name": "Bench press", "sets": 3,
        "sets_detail": [{"reps": 8, "weight": "80 kg"}] * 3,
        "is_bodyweight": False, "added_weight_kg": None,
        "rpe": 8.0, "pain_note": "left shoulder twinge",
    }],
}

CANNED_AI = {
    # Unified extraction (upload mode + wrapper calls from overnight)
    "Unified extraction": json.dumps({
        "workout": _CANNED_WORKOUT,
        "tasks": [],
        "events": [],
        "bodyweight": {"detected": True, "weight_kg": 82.5},
    }),
    # Legacy individual labels kept for any direct wrapper calls
    "Workout extraction": json.dumps(_CANNED_WORKOUT),
    "Task extraction": "[]",
    "Calendar extraction": "[]",
    "Bodyweight extraction": json.dumps({"detected": True, "weight_kg": 82.5}),
    "Journal": "## Smoke day\n\nDid a push day.\n\n*[1 memos · processed]*",
}


def fake_call_ai(user_message, system_prompt, label="AI", **kwargs):
    return CANNED_AI.get(label, "[]")


def fake_notion_post(url, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"results": [], "id": "fake-page-id"}
    return resp


notion_posts = []


def recording_notion_post(url, **kwargs):
    notion_posts.append((url, kwargs.get("json", {})))
    return fake_notion_post(url, **kwargs)


# ---------------------------------------------------------------------------
# Stage 1: receiver — POST raw audio the way the iOS Shortcut does
# ---------------------------------------------------------------------------

def stage_receiver() -> bool:
    print("\n[1/3] Receiver: raw-body upload (iOS Shortcut style)")
    import receiver
    with patch.object(receiver, "subprocess") as fake_subprocess:
        client = receiver.app.test_client()

        r = client.post("/upload", data=b"fake-audio-bytes",
                        content_type="audio/x-m4a",
                        headers={"Authorization": "Bearer smoke-test-token"})
        check("raw-body upload returns 200", r.status_code == 200, f"got {r.status_code}: {r.get_data(as_text=True)[:200]}")
        check("pipeline subprocess triggered", fake_subprocess.Popen.called)

        r2 = client.post("/upload", data=b"x", content_type="audio/x-m4a",
                         headers={"Authorization": "Bearer wrong"})
        check("bad token rejected (401)", r2.status_code == 401)

    inbox_files = list((TMP / "inbox").glob("*.m4a"))
    check("audio file landed in inbox", len(inbox_files) >= 1, f"inbox: {list((TMP / 'inbox').iterdir()) if (TMP / 'inbox').exists() else 'missing'}")
    return len(FAILURES) == 0


# ---------------------------------------------------------------------------
# Stage 2: upload mode — full pipeline over the file the receiver saved
# ---------------------------------------------------------------------------

def stage_upload() -> bool:
    print("\n[2/3] Upload mode: transcribe → extract → buffer → Notion writes")
    before = len(FAILURES)
    with patch.object(voice_journal, "Groq", FakeGroq), \
         patch("ai_client.call_ai", side_effect=fake_call_ai), \
         patch("pipeline.notion_client.requests.post", side_effect=recording_notion_post):
        voice_journal.run_upload_mode()

    today = date.today()
    buf_path = TMP / "buffer" / f"{today.isoformat()}.json"
    check("buffer JSON created", buf_path.exists())
    if not buf_path.exists():
        return False

    buf = json.loads(buf_path.read_text())
    check("buffer schema: transcripts + pending_writes",
          isinstance(buf.get("transcripts"), list) and isinstance(buf.get("pending_writes"), list),
          f"keys: {list(buf.keys())}")

    t = buf["transcripts"][0]
    for key in ("file", "time", "text", "raw_text", "error"):
        check(f"transcript dict has '{key}'", key in t, f"keys: {list(t.keys())}")
    check("segment filter dropped hallucination", "Thanks for watching" not in t["text"], t["text"])
    check("raw_text preserves hallucination (audit)", "Thanks for watching" in t.get("raw_text", ""))

    pw = buf["pending_writes"][0]
    for key in ("batch_id", "workout", "tasks", "events", "bodyweight",
                "workout_written_at", "tasks_written_at", "events_written_at", "bodyweight_written_at"):
        check(f"pending_writes has '{key}'", key in pw, f"keys: {list(pw.keys())}")
    check("workout marked written", pw.get("workout_written_at") is not None)
    check("bodyweight marked written", pw.get("bodyweight_written_at") is not None)

    dbs_written = {p.get("parent", {}).get("database_id") for _, p in notion_posts}
    check("workout row posted to Notion", "db-workout" in dbs_written, f"dbs: {dbs_written}")
    check("bodyweight row posted to Notion", "db-bw" in dbs_written, f"dbs: {dbs_written}")

    bw_payloads = [p for _, p in notion_posts if p.get("parent", {}).get("database_id") == "db-bw"]
    if bw_payloads:
        check("bodyweight value is 82.5 (not the bench 80!)",
              bw_payloads[0]["properties"]["Weight (kg)"]["number"] == 82.5,
              str(bw_payloads[0]["properties"]))

    wk_payloads = [p for _, p in notion_posts if p.get("parent", {}).get("database_id") == "db-workout"]
    if wk_payloads:
        wk_props = wk_payloads[0]["properties"]
        check("RPE written to Notion workout row",
              wk_props.get("RPE", {}).get("number") == 8.0,
              str(wk_props))
        check("Pain note written to Notion workout row",
              "left shoulder twinge" in str(wk_props.get("Pain note", "")),
              str(wk_props))

    audio_archive = TMP / "archive" / "audio" / today.isoformat()
    check("audio archived", audio_archive.exists() and any(audio_archive.iterdir()))
    check("inbox emptied", not any((TMP / "inbox").glob("*.m4a")))
    tx_archive = TMP / "archive" / "transcripts" / today.isoformat()
    check("raw transcript archived", tx_archive.exists() and any(tx_archive.glob("*.txt")))
    return len(FAILURES) == before


# ---------------------------------------------------------------------------
# Stage 3: overnight mode — consolidate yesterday's buffer into a journal
# ---------------------------------------------------------------------------

def stage_overnight() -> bool:
    print("\n[3/3] Overnight mode: buffer → journal markdown → Notion")
    before = len(FAILURES)
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Overnight processes *yesterday*; move today's buffer there.
    buf_today = TMP / "buffer" / f"{today.isoformat()}.json"
    buf_yest = TMP / "buffer" / f"{yesterday.isoformat()}.json"
    buf_today.rename(buf_yest)

    overnight_ai_labels: list = []

    def tracking_call_ai(user_message, system_prompt, label="AI", **kwargs):
        overnight_ai_labels.append(label)
        return fake_call_ai(user_message, system_prompt, label, **kwargs)

    with patch.object(voice_journal, "Groq", FakeGroq), \
         patch("ai_client.call_ai", side_effect=tracking_call_ai), \
         patch("pipeline.notion_client.requests.post", side_effect=recording_notion_post), \
         patch("pipeline.notion_client.requests.patch", side_effect=fake_notion_post):
        voice_journal.run_overnight_mode()

    check(
        "no Workout extraction AI call (buffer path used)",
        "Workout extraction" not in overnight_ai_labels,
        f"AI calls made: {overnight_ai_labels}",
    )

    md_files = list((TMP / "archive" / "markdown").glob(f"{yesterday.isoformat()}*.md"))
    check("journal markdown saved", len(md_files) == 1, str(list((TMP / 'archive' / 'markdown').iterdir())))
    if md_files:
        md = md_files[0].read_text()
        check("journal contains AI entry", "Smoke day" in md)
        check("workout table appended", "Workout —" in md and "Bench press" in md, md[:400])
    check("buffer archived after overnight",
          not buf_yest.exists() and (TMP / "buffer" / "archive" / buf_yest.name).exists())
    return len(FAILURES) == before


# ---------------------------------------------------------------------------

def main():
    print(f"Smoke test sandbox: {TMP}")
    stage_receiver()
    stage_upload()
    stage_overnight()

    print()
    if FAILURES:
        print(f"SMOKE TEST FAILED — {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print("SMOKE TEST PASSED — pipeline wiring is intact.")
    sys.exit(0)


if __name__ == "__main__":
    main()
