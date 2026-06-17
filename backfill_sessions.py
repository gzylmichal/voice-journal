#!/usr/bin/env python3
"""
Backfill Session labels — reads all Workout DB rows and re-classifies
the Session property using analytics.classify_session, grouping by date
so the whole day is classified as a unit.

Usage:
    python3 backfill_sessions.py              # dry-run (default, writes nothing)
    python3 backfill_sessions.py --apply      # write Session on differing rows
    python3 backfill_sessions.py --date 2026-06-15   # restrict to one date
"""

import argparse
import logging
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

from pipeline.config import NOTION_TOKEN, NOTION_WORKOUT_DB_ID, NOTION_VERSION
from analytics import classify_session
from models import parse_workout_entry

# ---------------------------------------------------------------------------

LOG_FILE = Path(__file__).parent / "backfill_sessions.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger("backfill_sessions")

WRITE_SLEEP_S = 0.34  # stay under Notion's ~3 req/s limit


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def fetch_all_rows(target_date: "str | None" = None) -> list:
    """Fetch all rows from the Workout DB, returning raw Notion page dicts."""
    url = f"https://api.notion.com/v1/databases/{NOTION_WORKOUT_DB_ID}/query"
    payload: dict = {"page_size": 100}
    if target_date:
        payload["filter"] = {
            "property": "Date",
            "date": {"equals": target_date},
        }

    pages = []
    while True:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Workout DB fetch error {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        pages.extend(data.get("results", []))
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break

    return pages


def patch_session(page_id: str, session_value: str) -> bool:
    """PATCH Session select on a single Notion page. Returns True on success."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "Session": {"select": {"name": session_value}},
        }
    }
    resp = requests.patch(url, headers=_headers(), json=payload, timeout=30)
    if resp.status_code == 200:
        return True
    log.error("PATCH failed for %s: %s %s", page_id, resp.status_code, resp.text[:200])
    return False


def compute_changes(pages: list) -> list:
    """Group pages by date, classify each day, return rows that need updating.

    Returns list of (page_id, date_str, exercise_names, current_session, computed_session)
    for rows where current_session != computed_session.
    """
    by_date: dict = defaultdict(list)
    for page in pages:
        entry = parse_workout_entry(page)
        d = entry.get("date", "")
        if not d:
            continue
        by_date[d].append({
            "page_id": page["id"],
            "exercise": entry.get("exercise", ""),
            "current_session": entry.get("session", ""),
        })

    changes = []
    for d in sorted(by_date.keys()):
        rows = by_date[d]
        exercise_names = [r["exercise"] for r in rows if r["exercise"]]
        computed = classify_session(exercise_names)
        for r in rows:
            if r["current_session"] != computed:
                changes.append(
                    (r["page_id"], d, exercise_names, r["current_session"], computed)
                )

    return changes


def run_dry_run(changes: list) -> None:
    """Print planned changes per date then a summary. Writes nothing."""
    by_date: dict = defaultdict(list)
    for page_id, d, exercise_names, current, computed in changes:
        by_date[d].append((page_id, exercise_names, current, computed))

    for d in sorted(by_date.keys()):
        rows = by_date[d]
        exercise_names = rows[0][1]
        current_values = sorted({r[2] or "—" for r in rows})
        computed = rows[0][3]
        exercises_display = ", ".join(exercise_names)
        print(
            f"{d}: {'/'.join(current_values)} → {computed} ({exercises_display})"
        )

    if changes:
        affected_dates = len({c[1] for c in changes})
        print(f"\n{len(changes)} rows across {affected_dates} date(s) would change")
    else:
        print("No rows need updating.")


def run_apply(changes: list) -> None:
    """PATCH Session on differing rows. Logs each update and prints totals."""
    patched = 0
    failed = 0
    for page_id, d, exercise_names, current, computed in changes:
        exercises_display = ", ".join(exercise_names)
        log.info(
            "%s: %s → %s (page %s) [%s]",
            d, current or "—", computed, page_id, exercises_display,
        )
        if patch_session(page_id, computed):
            patched += 1
        else:
            failed += 1
        time.sleep(WRITE_SLEEP_S)

    log.info("Done — %d rows updated, %d failed", patched, failed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Session labels in the Notion Workout DB"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write changes to Notion (default: dry-run, prints only)",
    )
    parser.add_argument(
        "--date", help="Restrict to one date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    if not NOTION_TOKEN:
        sys.exit("NOTION_TOKEN not set in .env")
    if not NOTION_WORKOUT_DB_ID:
        sys.exit("NOTION_WORKOUT_DB_ID not set in .env")

    if args.date:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            sys.exit(f"Invalid date format: {args.date} (use YYYY-MM-DD)")

    log.info(
        "Fetching rows from Workout DB%s...",
        f" for {args.date}" if args.date else "",
    )
    pages = fetch_all_rows(target_date=args.date)
    log.info("Fetched %d rows total", len(pages))

    changes = compute_changes(pages)

    if args.apply:
        log.info("%d rows need updating — applying...", len(changes))
        run_apply(changes)
    else:
        log.info("Dry-run mode (pass --apply to write changes)")
        run_dry_run(changes)


if __name__ == "__main__":
    main()
