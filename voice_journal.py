#!/usr/bin/env python3
"""
Voice Journal Pipeline (VPS Edition)
=====================================
Thin orchestrator — all domain logic lives in pipeline/*.

Flow:
  upload mode  — transcribe inbox files, write workout/tasks/calendar to Notion/GCal,
                 buffer transcript for overnight consolidation
  overnight mode — load buffer, format journal, push to Notion

Scheduled at 02:00 Europe/Warsaw via systemd timer.
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

try:
    from groq import Groq
except ImportError:
    sys.exit("Missing dependency: pip install groq --break-system-packages")

load_dotenv(Path(__file__).parent / ".env")

import ai_client
from pipeline.config import (
    ARCHIVE_AUDIO_DIR,
    ARCHIVE_MD_DIR,
    BUFFER_DIR,
    GCAL_ENABLED,
    GOOGLE_CALENDAR_ID,
    GROQ_API_KEY,
    INBOX_DIR,
    NOTION_BODYWEIGHT_DB_ID,
    NOTION_ENABLED,
    NOTION_TASK_DB_ID,
    NOTION_WORKOUT_DB_ID,
)
from pipeline.audio import get_inbox_files, transcribe_file
from pipeline.journal import format_journal_entry
from pipeline.extractors import (
    extract_all,
    extract_bodyweight,
    extract_calendar_events,
    extract_tasks,
    extract_workout,
    format_workout_table,
    validate_bodyweight,
)
from pipeline.notion_client import (
    create_notion_tasks,
    create_notion_workout_entries,
    fetch_latest_bodyweight,
    find_and_archive_draft,
    store_bodyweight,
    upload_to_notion,
)
from pipeline.gcal_client import create_gcal_events
from pipeline.storage import (
    append_to_buffer,
    archive_files,
    clear_buffer,
    load_buffer,
    mark_written,
    save_markdown,
)
from pipeline.lock import pipeline_lock, PipelineLocked

LOG_FILE = Path(__file__).parent / "voice_journal.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("voice_journal")


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_config():
    if not GROQ_API_KEY:
        log.error("Missing required env var: GROQ_API_KEY")
        log.error(f"Set it in {Path(__file__).parent / '.env'}")
        sys.exit(1)

    if NOTION_ENABLED:
        log.info("Delivery: Notion API ✓")
    else:
        log.info("Delivery: Local .md files (Notion API not configured)")

    if GCAL_ENABLED:
        log.info(f"Calendar: Google Calendar ✓ ({GOOGLE_CALENDAR_ID})")
    else:
        log.info("Calendar: disabled (google-api-python-client not installed or token missing)")

    log.info(f"AI provider: {ai_client.resolve_provider().upper()}")


# ---------------------------------------------------------------------------
# Upload mode — runs immediately after each audio upload
# ---------------------------------------------------------------------------

def run_upload_mode():
    """
    Triggered immediately after each audio upload (by iOS Shortcut or receiver.py).

    Per-memo pipeline:
      1. Transcribe new inbox files via Whisper
      2. Extract workout / tasks / calendar events from transcripts
      3. Save transcripts + extracted data to day's buffer (data is safe here)
      4. Write workout → Notion Workout DB; mark written
      5. Write tasks   → Notion Task DB; mark written
      6. Write events  → Google Calendar; mark written
      7. Archive audio files

    Does NOT create a journal page — that happens at midnight via overnight mode.
    Any write step that fails leaves its pending_writes entry un-marked so the
    overnight pass will retry it.
    """
    try:
        with pipeline_lock(BUFFER_DIR):
            _run_upload_locked()
    except PipelineLocked:
        log.info("Pipeline busy — another upload is in progress; file stays in inbox for next trigger")


def _run_upload_locked():
    recording_date = date.today()

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    BUFFER_DIR.mkdir(parents=True, exist_ok=True)

    files = get_inbox_files()
    if not files:
        log.info("No voice memos found in inbox. Nothing to process.")
        return

    log.info(f"Found {len(files)} voice memo(s) to process")

    groq_client = Groq(api_key=GROQ_API_KEY)
    transcripts = [transcribe_file(groq_client, f) for f in files]
    successful  = [t for t in transcripts if not t.get("error")]

    if not successful:
        log.error("All transcriptions failed. Aborting.")
        return

    log.info(f"Successfully transcribed {len(successful)}/{len(transcripts)} memos")

    # Skip memos whose Whisper output was entirely removed by the hallucination filter.
    non_empty = [t for t in successful if t.get("text", "").strip()]
    for t in successful:
        if not t.get("text", "").strip():
            log.warning(f"Memo {t.get('file')!r} produced an empty filtered transcript — skipping extraction, audio archived")

    if not non_empty:
        log.warning("All transcripts are empty after filtering — archiving audio, nothing to extract.")
        archive_files(files, recording_date, transcripts=successful)
        return

    # Extract structured data from this batch — single LLM call for all four categories
    extracted  = extract_all(non_empty, recording_date)
    workout    = extracted["workout"]
    tasks      = extracted["tasks"] if NOTION_ENABLED else []
    cal_events = extracted["events"] if GCAL_ENABLED else []
    bodyweight = extracted["bodyweight"]

    # Buffer non-empty transcripts + extracted data — data is safe from here on
    batch_id = append_to_buffer(
        non_empty,
        recording_date,
        extracted={"workout": workout, "tasks": tasks, "events": cal_events, "bodyweight": bodyweight},
    )

    # Resolve bodyweight once for the entire batch
    resolved_bodyweight = (
        bodyweight.get("weight_kg") if bodyweight.get("detected") else None
    ) or fetch_latest_bodyweight(recording_date)

    # Store bodyweight if newly detected and passes plausibility check
    if bodyweight.get("detected") and NOTION_BODYWEIGHT_DB_ID and batch_id:
        if validate_bodyweight(bodyweight["weight_kg"], recording_date):
            ok = store_bodyweight(bodyweight["weight_kg"], recording_date)
            if ok:
                mark_written(recording_date, batch_id, "bodyweight")
        else:
            log.warning(f"Bodyweight {bodyweight['weight_kg']:.1f} kg failed validation — not stored")

    # Write workout to DB — pass resolved bodyweight for bodyweight exercises
    wk_created = 0
    if workout.get("detected") and NOTION_WORKOUT_DB_ID:
        wk_created = create_notion_workout_entries(workout, recording_date, resolved_bodyweight=resolved_bodyweight)
        log.info(f"Workout DB: {wk_created}/{len(workout.get('exercises', []))} entries written")
        if batch_id and wk_created == len(workout.get("exercises", [])):
            mark_written(recording_date, batch_id, "workout")

    tasks_created = 0
    if tasks and NOTION_TASK_DB_ID:
        tasks_created = create_notion_tasks(tasks)
        log.info(f"Tasks: {tasks_created}/{len(tasks)} created in Notion")
        if batch_id and tasks_created == len(tasks):
            mark_written(recording_date, batch_id, "tasks")

    cal_created = 0
    if cal_events:
        cal_created = create_gcal_events(cal_events)
        if batch_id:
            mark_written(recording_date, batch_id, "events")
    elif GCAL_ENABLED:
        log.info("No calendar events detected")
        if batch_id:
            mark_written(recording_date, batch_id, "events")

    archive_files(files, recording_date, transcripts=successful)

    wk_info   = f" · Workout: {workout.get('workout_name', '?')} ({wk_created} rows)" if workout.get("detected") else ""
    task_info = f" · {tasks_created}/{len(tasks)} tasks" if tasks else ""
    cal_info  = f" · {cal_created}/{len(cal_events)} events → GCal" if cal_events else ""
    log.info("=" * 60)
    log.info(f"Upload done. {len(non_empty)} memo(s) buffered{wk_info}{task_info}{cal_info}")
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Overnight mode — consolidates buffer into a journal entry
# ---------------------------------------------------------------------------

def run_overnight_mode():
    """
    Runs at end of day (02:00 via systemd timer).

    Consolidates all of the day's buffered transcripts into a single journal entry
    and pushes it to Notion. Retries any pending DB writes from upload passes that
    failed before completing.

    Falls back to inbox files if no buffer exists (legacy behaviour / manual runs).
    """
    try:
        with pipeline_lock(BUFFER_DIR):
            _run_overnight_locked()
    except PipelineLocked:
        log.info("Pipeline busy — overnight run skipped (manual retry: --mode overnight)")


def _run_overnight_locked():
    recording_date = date.today() - timedelta(days=1)

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_MD_DIR.mkdir(parents=True, exist_ok=True)
    BUFFER_DIR.mkdir(parents=True, exist_ok=True)

    groq_client = Groq(api_key=GROQ_API_KEY)

    transcripts, pending_writes = load_buffer(recording_date)
    legacy_files = []
    write_structured_data = False

    if transcripts:
        log.info(f"Loaded {len(transcripts)} buffered transcript(s) for {recording_date}")
    else:
        log.info("No buffer found — falling back to inbox files (legacy mode)")
        legacy_files = get_inbox_files()
        if not legacy_files:
            log.info("No voice memos in inbox either. Nothing to process.")
            return
        raw = [transcribe_file(groq_client, f) for f in legacy_files]
        transcripts = [t for t in raw if not t.get("error")]
        if not transcripts:
            log.error("All transcriptions failed. Aborting.")
            return
        write_structured_data = True

    # Retry any pending writes from failed upload passes
    for entry in pending_writes:
        batch_id = entry["batch_id"]

        workout = entry.get("workout") or {}
        if entry.get("workout_written_at") is None and workout.get("detected") and NOTION_WORKOUT_DB_ID:
            cnt = create_notion_workout_entries(workout, recording_date)
            mark_written(recording_date, batch_id, "workout")
            log.info(f"Retry workout write (batch {batch_id}): {cnt} entries")

        tasks = entry.get("tasks") or []
        if entry.get("tasks_written_at") is None and tasks and NOTION_TASK_DB_ID:
            cnt = create_notion_tasks(tasks)
            mark_written(recording_date, batch_id, "tasks")
            log.info(f"Retry tasks write (batch {batch_id}): {cnt} tasks")

        events = entry.get("events") or []
        if entry.get("events_written_at") is None and events:
            cnt = create_gcal_events(events)
            mark_written(recording_date, batch_id, "events")
            log.info(f"Retry events write (batch {batch_id}): {cnt} events")

        bw = entry.get("bodyweight") or {}
        if entry.get("bodyweight_written_at") is None and bw.get("detected") and NOTION_BODYWEIGHT_DB_ID:
            if validate_bodyweight(bw["weight_kg"], recording_date):
                ok = store_bodyweight(bw["weight_kg"], recording_date)
                if ok:
                    mark_written(recording_date, batch_id, "bodyweight")
                log.info(f"Retry bodyweight write (batch {batch_id}): {'ok' if ok else 'failed'}")
            else:
                log.warning(f"Retry bodyweight {bw['weight_kg']:.1f} kg failed validation — not stored (batch {batch_id})")

    journal_md = format_journal_entry(groq_client, transcripts, recording_date)

    # Append workout table to journal
    workout = extract_workout(groq_client, transcripts, recording_date)
    if workout.get("detected"):
        workout_table = format_workout_table(workout, recording_date)
        if workout_table:
            journal_md += workout_table
            log.info("Workout table appended to journal")

    wk_created = tasks_created = cal_created = 0
    if write_structured_data:
        if workout.get("detected") and NOTION_WORKOUT_DB_ID:
            wk_created = create_notion_workout_entries(workout, recording_date)
        tasks = extract_tasks(groq_client, transcripts, recording_date)
        if tasks and NOTION_TASK_DB_ID:
            tasks_created = create_notion_tasks(tasks)
        cal_events = extract_calendar_events(groq_client, transcripts, recording_date)
        if cal_events:
            cal_created = create_gcal_events(cal_events)

    md_path = save_markdown(journal_md, recording_date)

    notion_ok = False
    if NOTION_ENABLED:
        archived = find_and_archive_draft(recording_date)
        if archived:
            log.info("Archived existing entry for this date — replacing with new run")
        notion_ok = upload_to_notion(journal_md, recording_date)
        if not notion_ok:
            log.warning("Notion upload failed — .md saved locally as backup")
    else:
        log.info("Notion not configured — .md is your deliverable")

    if legacy_files:
        archive_files(legacy_files, recording_date)
    clear_buffer(recording_date)

    provider  = ai_client.resolve_provider()
    delivery  = "Notion ✓" if notion_ok else ("Notion ✗" if NOTION_ENABLED else ".md saved")
    log.info("=" * 60)
    log.info(f"Done. {len(transcripts)} memos → {provider.upper()} → {md_path.name} → {delivery}")
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Voice Journal Pipeline")
    parser.add_argument(
        "--mode",
        choices=["upload", "overnight", "morning"],
        default="overnight",
        help=(
            "upload: process new inbox files immediately — transcribe, write workout/"
            "tasks/calendar to Notion/GCal, buffer transcript for journal;\n"
            "overnight: consolidate today's buffered transcripts into a journal entry "
            "and push to Notion (runs at 02:00 via systemd);\n"
            "morning: legacy alias for overnight"
        )
    )
    args = parser.parse_args()

    log.info("=" * 60)
    log.info(f"Voice Journal Pipeline — Starting (mode: {args.mode})")
    log.info("=" * 60)

    validate_config()

    if args.mode == "upload":
        run_upload_mode()
    else:
        run_overnight_mode()  # overnight + morning (legacy) both consolidate


if __name__ == "__main__":
    main()
