"""pipeline/storage.py — Local file I/O: markdown save, audio archive, transcript buffer."""

import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

from pipeline.config import ARCHIVE_AUDIO_DIR, ARCHIVE_MD_DIR, ARCHIVE_TRANSCRIPTS_DIR, BUFFER_DIR

log = logging.getLogger(__name__)


def save_markdown(content: str, today: date) -> Path:
    """Save journal entry as a .md file in the archive."""
    filename = f"{today.isoformat()}-journal.md"
    filepath = ARCHIVE_MD_DIR / filename
    filepath.write_text(content, encoding="utf-8")
    log.info(f"Saved markdown: {filepath}")
    return filepath


def archive_transcript(transcript: dict, today: date):
    """Write a raw + filtered transcript txt file for audit purposes.

    File path: archive/transcripts/YYYY-MM-DD/<audio-stem>.txt
    Contains: filename, timestamp, raw Whisper text, filtered text, dropped segment count.
    """
    filename = transcript.get("file", "unknown")
    stem = Path(filename).stem
    day_dir = ARCHIVE_TRANSCRIPTS_DIR / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    txt_path = day_dir / f"{stem}.txt"

    raw_text = transcript.get("raw_text", "")
    filtered_text = transcript.get("text", "")
    timestamp = transcript.get("time", "")

    lines = [
        f"file: {filename}",
        f"timestamp: {timestamp}",
        f"date: {today.isoformat()}",
        "",
        "--- raw whisper output ---",
        raw_text,
        "",
        "--- filtered output ---",
        filtered_text,
    ]
    try:
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"Transcript archived: {txt_path}")
    except Exception as e:
        log.error(f"Failed to archive transcript for {filename}: {e}")


def archive_files(files: List[Path], today: date, transcripts: Optional[List[dict]] = None):
    """Move processed audio files into a dated subdirectory of the audio archive.

    If transcripts is provided, also writes a raw+filtered txt for each file.
    """
    day_dir = ARCHIVE_AUDIO_DIR / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    transcript_map = {}
    if transcripts:
        transcript_map = {t.get("file"): t for t in transcripts if t.get("file")}

    for f in files:
        dest = day_dir / f.name
        try:
            shutil.move(str(f), str(dest))
            log.info(f"Archived: {f.name} → {dest}")
        except Exception as e:
            log.error(f"Failed to archive {f.name}: {e}")

        if f.name in transcript_map:
            archive_transcript(transcript_map[f.name], today)


def get_buffer_path(d: date) -> Path:
    return BUFFER_DIR / f"{d.isoformat()}.json"


def load_buffer(d: date) -> Tuple[List[dict], List[dict]]:
    """Load buffered transcripts and pending writes for a given date.

    Returns (transcripts, pending_writes). Both empty lists if no buffer.
    Backward compatible: old flat-array buffer files are returned as (list, []).
    """
    path = get_buffer_path(d)
    if not path.exists():
        return [], []
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data, []
        return data.get("transcripts", []), data.get("pending_writes", [])
    except Exception as e:
        log.error(f"Failed to load buffer {path}: {e}")
        return [], []


def append_to_buffer(
    transcripts: List[dict],
    d: date,
    extracted: Optional[dict] = None,
) -> Optional[str]:
    """Append transcripts to the day's buffer file, skipping duplicates by filename.

    If extracted is provided ({workout, tasks, events}), stores it as a pending_write
    entry with per-resource written_at timestamps all null.

    Returns the batch_id string if extracted was stored, else None.
    """
    BUFFER_DIR.mkdir(parents=True, exist_ok=True)
    existing_transcripts, pending_writes = load_buffer(d)

    seen_files = {t.get("file") for t in existing_transcripts if t.get("file")}
    added = 0
    for t in transcripts:
        if t.get("file") and t["file"] in seen_files:
            log.info(f"Buffer: skipping duplicate {t['file']}")
            continue
        existing_transcripts.append(t)
        seen_files.add(t.get("file"))
        added += 1

    batch_id = None
    if extracted is not None:
        batch_id = datetime.now().isoformat(timespec="seconds")
        pending_writes.append({
            "batch_id":              batch_id,
            "workout":               extracted.get("workout"),
            "tasks":                 extracted.get("tasks", []),
            "events":                extracted.get("events", []),
            "bodyweight":            extracted.get("bodyweight"),
            "workout_written_at":    None,
            "tasks_written_at":      None,
            "events_written_at":     None,
            "bodyweight_written_at": None,
        })

    path = get_buffer_path(d)
    data = {"transcripts": existing_transcripts, "pending_writes": pending_writes}
    with open(path, "w") as f:
        json.dump(data, f, default=str, indent=2)
    log.info(f"Buffer updated: {path.name} ({added} new transcripts, {len(existing_transcripts)} total)")
    return batch_id


def mark_written(d: date, batch_id: str, resource: str):
    """Mark a specific resource as written for a pending buffer entry.

    resource must be one of: 'workout', 'tasks', 'events'.
    No-op if batch_id not found or buffer file doesn't exist.
    """
    path = get_buffer_path(d)
    if not path.exists():
        return
    transcripts, pending_writes = load_buffer(d)
    for entry in pending_writes:
        if entry.get("batch_id") == batch_id:
            entry[f"{resource}_written_at"] = datetime.now().isoformat()
            break
    data = {"transcripts": transcripts, "pending_writes": pending_writes}
    with open(path, "w") as f:
        json.dump(data, f, default=str, indent=2)


def clear_buffer(d: date):
    """Move the day's buffer to an archive subfolder after overnight processing."""
    path = get_buffer_path(d)
    if not path.exists():
        return
    archive_path = BUFFER_DIR / "archive" / path.name
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(archive_path))
    log.info(f"Buffer archived: {path.name}")
