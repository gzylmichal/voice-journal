#!/usr/bin/env python3
"""
Backfill Workout Log — processes all archived audio dates and writes
workout entries to the Notion Workout Log DB.

Skips dates that have already been backfilled (tracked in backfill_done.txt).
Safe to re-run — won't duplicate entries for already-processed dates.

Usage:
    python3 backfill_workouts.py              # all archive dates
    python3 backfill_workouts.py --date 2026-05-18   # single date
    python3 backfill_workouts.py --dry-run    # show what would be processed
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Reuse everything from the main pipeline
sys.path.insert(0, str(Path(__file__).parent))
from voice_journal import (
    GROQ_API_KEY,
    NOTION_WORKOUT_DB_ID,
    ARCHIVE_AUDIO_DIR,
    transcribe_file,
    extract_workout,
    create_notion_workout_entries,
)

try:
    from groq import Groq
except ImportError:
    sys.exit("Missing: pip install groq --break-system-packages")

# ---------------------------------------------------------------------------

LOG_FILE = Path(__file__).parent / "backfill_workouts.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger("backfill")

DONE_FILE = Path(__file__).parent / "backfill_done.txt"
SUPPORTED = {".m4a", ".mp3", ".wav", ".mp4", ".ogg", ".flac", ".webm", ".caf"}


def already_done(d: date) -> bool:
    if not DONE_FILE.exists():
        return False
    return d.isoformat() in DONE_FILE.read_text().splitlines()


def mark_done(d: date):
    with open(DONE_FILE, "a") as f:
        f.write(d.isoformat() + "\n")


def get_archive_dates() -> list[date]:
    if not ARCHIVE_AUDIO_DIR.exists():
        return []
    dates = []
    for p in sorted(ARCHIVE_AUDIO_DIR.iterdir()):
        if p.is_dir():
            try:
                dates.append(date.fromisoformat(p.name))
            except ValueError:
                pass
    return dates


def process_date(groq_client: Groq, d: date, dry_run: bool = False) -> int:
    day_dir = ARCHIVE_AUDIO_DIR / d.isoformat()
    files = sorted([f for f in day_dir.iterdir() if f.suffix.lower() in SUPPORTED])

    if not files:
        log.info(f"{d}: no audio files, skipping")
        return 0

    log.info(f"{d}: found {len(files)} file(s)")

    if dry_run:
        log.info(f"{d}: [dry-run] would transcribe and extract workout")
        return 0

    # Transcribe
    transcripts = [transcribe_file(groq_client, f) for f in files]
    successful = [t for t in transcripts if not t.get("error")]

    if not successful:
        log.warning(f"{d}: all transcriptions failed, skipping")
        return 0

    # Extract workout
    workout = extract_workout(groq_client, successful, d)

    if not workout.get("detected"):
        log.info(f"{d}: no workout detected")
        mark_done(d)
        return 0

    log.info(f"{d}: {workout.get('workout_name')} — {len(workout.get('exercises', []))} exercise(s)")

    # Write to Notion
    written = create_notion_workout_entries(workout, d)
    log.info(f"{d}: {written}/{len(workout.get('exercises', []))} rows written to Notion")

    mark_done(d)
    return written


def main():
    parser = argparse.ArgumentParser(description="Backfill Notion Workout Log from audio archive")
    parser.add_argument("--date", help="Process a single date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without writing")
    parser.add_argument("--force", action="store_true", help="Re-process dates already marked as done")
    args = parser.parse_args()

    if not GROQ_API_KEY:
        sys.exit("GROQ_API_KEY not set in .env")
    if not NOTION_WORKOUT_DB_ID:
        sys.exit("NOTION_WORKOUT_DB_ID not set in .env")

    groq_client = Groq(api_key=GROQ_API_KEY)

    if args.date:
        try:
            dates = [date.fromisoformat(args.date)]
        except ValueError:
            sys.exit(f"Invalid date format: {args.date} (use YYYY-MM-DD)")
    else:
        dates = get_archive_dates()

    log.info(f"Backfill starting — {len(dates)} date(s) to check")

    total_written = 0
    for d in dates:
        if not args.force and already_done(d):
            log.info(f"{d}: already processed, skipping (use --force to redo)")
            continue
        written = process_date(groq_client, d, dry_run=args.dry_run)
        total_written += written

    log.info(f"Backfill complete — {total_written} total rows written to Notion")


if __name__ == "__main__":
    main()
