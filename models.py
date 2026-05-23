"""models.py — Shared data-structure definitions for the Voice Journal pipeline.

All types are TypedDicts so they interoperate with plain dicts and require
no runtime overhead. Fields that Notion may return as None are Optional.
"""

from typing import Optional
from typing import TypedDict


class WorkoutEntry(TypedDict, total=False):
    """One exercise row as returned by the Notion Workout Log DB."""
    exercise:     str
    date:         str           # ISO date string, e.g. "2026-05-18"
    session:      str           # "Chest", "Deadlift", "Squat", "Arms", "Other"
    muscle_group: str
    sets:         Optional[int]
    reps:         Optional[int]
    weight:       str           # raw weight string, e.g. "80x5, 85x3"
    top_set_kg:   Optional[float]


class Transcript(TypedDict, total=False):
    """Output of a single voice-memo transcription pass."""
    file:  str
    time:  str    # HH:MM string
    text:  str
    error: bool


class Task(TypedDict, total=False):
    """Action item extracted from voice memos."""
    title:       str
    priority:    str   # "High", "Normal", "Low"
    type:        str   # "Work", "Personal", etc.
    description: str
    due_date:    str   # ISO date string YYYY-MM-DD


class CalendarEvent(TypedDict, total=False):
    """Calendar event extracted from voice memos."""
    title:            str
    date:             str   # ISO date string YYYY-MM-DD
    time:             str   # HH:MM, optional
    duration_minutes: int
    notes:            str


# ---------------------------------------------------------------------------
# Notion page → WorkoutEntry parser
# ---------------------------------------------------------------------------

def parse_workout_entry(page: dict) -> WorkoutEntry:
    """Convert a raw Notion Workout Log DB page into a WorkoutEntry dict."""
    props = page.get("properties", {})

    def _title(p: dict) -> str:
        items = p.get("title", [])
        return items[0]["plain_text"] if items else ""

    def _date(p: dict) -> str:
        d = p.get("date", {})
        return d.get("start", "") if d else ""

    def _select(p: dict) -> str:
        s = p.get("select")
        return s["name"] if s else ""

    def _number(p: dict) -> Optional[float]:
        return p.get("number")

    def _rich_text(p: dict) -> str:
        items = p.get("rich_text", [])
        return items[0]["plain_text"] if items else ""

    return WorkoutEntry(
        exercise=     _title(props.get("Exercise", {})),
        date=         _date(props.get("Date", {})),
        session=      _select(props.get("Session", {})),
        muscle_group= _select(props.get("Muscle Group", {})),
        sets=         _number(props.get("Sets", {})),
        reps=         _number(props.get("Reps", {})),
        weight=       _rich_text(props.get("Weight", {})),
        top_set_kg=   _number(props.get("Top Set (kg)", {})),
    )
