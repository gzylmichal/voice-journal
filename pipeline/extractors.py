"""pipeline/extractors.py — AI extraction for workout, tasks, and calendar events."""

import json
import logging
import re
from datetime import date
from typing import List, Optional, Tuple

import ai_client
from pipeline.config import GCAL_ENABLED, NOTION_ENABLED
from pipeline.prompts import BODYWEIGHT_SYSTEM_PROMPT, CALENDAR_SYSTEM_PROMPT, TASK_SYSTEM_PROMPT, WORKOUT_SYSTEM_PROMPT

_BODYWEIGHT_MIN_KG = 40.0
_BODYWEIGHT_MAX_KG = 250.0
_BODYWEIGHT_MAX_DAY_DELTA_FRAC = 0.05  # 5% of last known weight

log = logging.getLogger(__name__)

# Phrases that indicate the speaker is stating their own body weight.
# If none appear in the combined transcript, skip the LLM call entirely.
BODYWEIGHT_WEIGH_IN_PHRASES = [
    # English
    "i weigh", "my weight", "weighed myself", "body weight is",
    "bodyweight is", "on the scale", "scale says",
    # Polish
    "ważę", "zważyłem", "zważyłam", "moja waga", "waga wynosi", "na wadze",
]

# Order matters: more specific keywords first to avoid mismatch.
MUSCLE_GROUP_RULES = [
    # Back
    ("pull-up",       "Back"),
    ("pullup",        "Back"),
    ("pull up",       "Back"),
    ("pull down",     "Back"),
    ("pulldown",      "Back"),
    ("lat ",          "Back"),
    ("cable row",     "Back"),
    ("barbell row",   "Back"),
    ("bent over row", "Back"),
    ("seated row",    "Back"),
    ("row",           "Back"),
    ("deadlift",      "Back"),
    # Chest
    ("bench press",   "Chest"),
    ("chest press",   "Chest"),
    ("chest fly",     "Chest"),
    ("pec",           "Chest"),
    ("dip",           "Chest"),
    # Shoulders
    ("overhead press", "Shoulders"),
    ("ohp",            "Shoulders"),
    ("shoulder press", "Shoulders"),
    ("lateral raise",  "Shoulders"),
    ("front raise",    "Shoulders"),
    ("face pull",      "Shoulders"),
    # Triceps
    ("push down",     "Triceps"),
    ("pushdown",      "Triceps"),
    ("tricep",        "Triceps"),
    ("skull crusher", "Triceps"),
    ("close grip",    "Triceps"),
    ("narrow grip",   "Triceps"),
    # Biceps
    ("bicep",         "Biceps"),
    ("curl",          "Biceps"),
    ("hammer curl",   "Biceps"),
    ("preacher",      "Biceps"),
    # Legs
    ("squat",         "Legs"),
    ("leg press",     "Legs"),
    ("lunge",         "Legs"),
    ("rdl",           "Legs"),
    ("romanian",      "Legs"),
    ("leg extension", "Legs"),
    ("leg curl",      "Legs"),
    ("calf",          "Legs"),
    ("hip thrust",    "Legs"),
    # Forearms
    ("wrist curl",    "Forearms"),
    ("wrist",         "Forearms"),
    ("forearm",       "Forearms"),
    # Core
    ("plank",         "Core"),
    ("crunch",        "Core"),
    ("ab ",           "Core"),
    ("core",          "Core"),
]

# Longer keywords must match before shorter ones (e.g. "leg curl" before "curl").
MUSCLE_GROUP_RULES = sorted(MUSCLE_GROUP_RULES, key=lambda r: len(r[0]), reverse=True)


def infer_muscle_group(exercise_name: str) -> str:
    """Return the primary muscle group for a given exercise name."""
    name_lower = exercise_name.lower()
    for keyword, group in MUSCLE_GROUP_RULES:
        if keyword in name_lower:
            return group
    return "Other"


def extract_top_weight(weight_str: str) -> Optional[float]:
    """
    Extract the heaviest weight (kg) from a weight string.

    Handles:
      "80 kg"            -> 80.0
      "70x8, 80x5, 90x3" -> 90.0  (pyramid)
      "BW"               -> None   (bodyweight)
    """
    if not weight_str or weight_str.strip() in ("—", "bw", "BW", "bodyweight"):
        return None
    numbers = re.findall(r"(\d+(?:\.\d+)?)\s*(?:x\d+|kg)?", weight_str.lower())
    candidates = [float(n) for n in numbers if float(n) > 0]
    return max(candidates) if candidates else None


def _col(text, width: int) -> str:
    """Pad or truncate text to fixed width."""
    text = str(text) if text is not None else "—"
    return text[:width].ljust(width)


def _sets_detail_summary(ex: dict) -> Tuple[Optional[int], str]:
    """
    From an exercise dict with the sets_detail schema, return
    (sets_count, weight_display_string).
    Falls back gracefully if old flat schema is present.
    """
    detail = ex.get("sets_detail") or []
    sets = ex.get("sets")

    if detail:
        if sets is None:
            sets = len(detail)
        parts = []
        for s in detail:
            w = s.get("weight") or ""
            r = s.get("reps")
            w_num = w.replace(" kg", "").replace("kg", "").strip()
            if w_num and r is not None:
                parts.append(f"{w_num}x{r}")
            elif w_num:
                parts.append(w_num)
            elif r is not None:
                parts.append(f"{r} reps")
        weight_str = ", ".join(parts) if parts else (ex.get("weight") or "—")
    else:
        weight_str = ex.get("weight") or "—"

    return sets, weight_str


def format_workout_table(workout: dict, recording_date: date) -> str:
    """Convert workout dict to a markdown code-block table appended to journal."""
    if not workout or not workout.get("detected") or not workout.get("exercises"):
        return ""

    name = workout.get("workout_name", "Workout")
    day_label = recording_date.strftime("%A, %B %d")

    lines = [
        f"\n## Workout — {day_label} ({name})\n",
        "```",
        f"{'Exercise':<28} {'Sets':>4}  {'Sets detail (weightxreps)'}",
        "─" * 60,
    ]
    for ex in workout["exercises"]:
        sets, weight_str = _sets_detail_summary(ex)
        lines.append(
            f"{_col(ex.get('name'), 28)} "
            f"{_col(sets, 4)}  "
            f"{weight_str}"
        )
    lines.append("```")
    return "\n".join(lines) + "\n"


def extract_workout(groq_client, transcripts: List[dict], recording_date: date) -> dict:
    """
    Run a dedicated AI pass to detect and extract workout data.
    Returns workout dict, or {"detected": False} on no content or error.
    """
    combined_text = "\n\n".join(
        f"[{t['time']}] {t['text']}"
        for t in transcripts if not t.get("error")
    )
    user_message = (
        f"Recording date: {recording_date.strftime('%A, %B %d, %Y')}\n\n"
        f"{combined_text}"
    )

    log.info("Extracting workout data...")

    try:
        raw = ai_client.call_ai(user_message, WORKOUT_SYSTEM_PROMPT, "Workout extraction", temperature=0)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        raw = raw.strip()

        workout = json.loads(raw)

        if workout.get("detected"):
            count = len(workout.get("exercises", []))
            log.info(f"Workout detected: {workout.get('workout_name')} — {count} exercise(s)")
        else:
            log.info("No workout detected in today's memos")

        return workout

    except json.JSONDecodeError as e:
        log.error(f"Workout extraction: JSON parse failed: {e}")
        return {"detected": False, "exercises": []}
    except Exception as e:
        log.error(f"Workout extraction failed: {e}")
        return {"detected": False, "exercises": []}


def extract_tasks(groq_client, transcripts: List[dict], recording_date: date) -> List[dict]:
    """
    Run a dedicated AI pass to extract action items from transcripts.
    Returns list of task dicts, empty if none found or on error.
    """
    if not NOTION_ENABLED:
        return []

    combined_text = "\n\n".join(
        f"[{t['time']}] {t['text']}"
        for t in transcripts if not t.get("error")
    )
    user_message = (
        f"Recording date: {recording_date.strftime('%A, %B %d, %Y')} "
        f"({recording_date.isoformat()})\n\n"
        f"{combined_text}"
    )

    log.info("Extracting tasks...")

    try:
        raw = ai_client.call_ai(user_message, TASK_SYSTEM_PROMPT, "Task extraction", temperature=0)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        raw = raw.strip()

        tasks = json.loads(raw)
        if not isinstance(tasks, list):
            log.warning("Task extraction returned non-list JSON, skipping")
            return []

        log.info(f"Found {len(tasks)} task(s)")
        return tasks

    except json.JSONDecodeError as e:
        log.error(f"Task extraction: JSON parse failed: {e}")
        return []
    except Exception as e:
        log.error(f"Task extraction failed: {e}")
        return []


def extract_calendar_events(groq_client, transcripts: List[dict], recording_date: date) -> List[dict]:
    """
    Run a second AI pass to extract calendar events from transcripts.
    Returns a list of event dicts, empty if none found or extraction fails.
    """
    if not GCAL_ENABLED:
        return []

    combined_text = "\n\n".join(
        f"[{t['time']}] {t['text']}"
        for t in transcripts if not t.get("error")
    )
    user_message = (
        f"Reference date (when these memos were recorded): "
        f"{recording_date.strftime('%A, %B %d, %Y')} ({recording_date.isoformat()})\n\n"
        f"{combined_text}"
    )

    log.info("Extracting calendar events...")

    try:
        raw = ai_client.call_ai(user_message, CALENDAR_SYSTEM_PROMPT, "Calendar extraction", temperature=0)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        raw = raw.strip()

        events = json.loads(raw)
        if not isinstance(events, list):
            log.warning("Calendar extraction returned non-list JSON, skipping")
            return []

        log.info(f"Found {len(events)} calendar event(s)")
        return events

    except json.JSONDecodeError as e:
        log.error(f"Calendar extraction: JSON parse failed: {e}")
        return []
    except Exception as e:
        log.error(f"Calendar extraction failed: {e}")
        return []


def validate_bodyweight(weight_kg: float, recording_date: date) -> bool:
    """Return True if weight_kg is plausible for a human on recording_date.

    Rejects:
    - Values outside the hard range 40–250 kg.
    - Values that deviate >5% from the most recent recorded bodyweight.
    """
    if not (_BODYWEIGHT_MIN_KG <= weight_kg <= _BODYWEIGHT_MAX_KG):
        log.warning(
            f"Bodyweight validation failed: {weight_kg:.1f} kg outside hard range "
            f"[{_BODYWEIGHT_MIN_KG}–{_BODYWEIGHT_MAX_KG}]"
        )
        return False

    try:
        from pipeline.notion_client import fetch_latest_bodyweight
        last = fetch_latest_bodyweight(recording_date)
    except Exception as e:
        log.warning(f"Bodyweight validation: could not fetch last weight ({e}), accepting on hard range alone")
        return True

    if last is None:
        return True

    delta_frac = abs(weight_kg - last) / last
    if delta_frac > _BODYWEIGHT_MAX_DAY_DELTA_FRAC:
        log.warning(
            f"Bodyweight validation failed: {weight_kg:.1f} kg deviates {delta_frac:.1%} "
            f"from last known {last:.1f} kg (max {_BODYWEIGHT_MAX_DAY_DELTA_FRAC:.0%})"
        )
        return False

    return True


def extract_bodyweight(groq_client, transcripts: List[dict], recording_date: date) -> dict:
    """Extract bodyweight measurement from transcripts. Returns {"detected": True/False, "weight_kg": float}."""
    combined_text = "\n\n".join(
        f"[{t['time']}] {t['text']}"
        for t in transcripts if not t.get("error")
    )
    if not combined_text.strip():
        return {"detected": False}

    text_lower = combined_text.lower()
    if not any(phrase in text_lower for phrase in BODYWEIGHT_WEIGH_IN_PHRASES):
        log.info("Bodyweight: no weigh-in phrase found — skipping LLM call")
        return {"detected": False}

    user_message = (
        f"Recording date: {recording_date.strftime('%A, %B %d, %Y')}\n\n"
        f"{combined_text}"
    )

    try:
        raw = ai_client.call_ai(user_message, BODYWEIGHT_SYSTEM_PROMPT, "Bodyweight extraction", temperature=0)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        raw = raw.strip()

        data = json.loads(raw)
        if data.get("detected") and isinstance(data.get("weight_kg"), (int, float)):
            log.info(f"Bodyweight detected: {data['weight_kg']:.1f} kg")
            return {"detected": True, "weight_kg": float(data["weight_kg"])}
        return {"detected": False}

    except json.JSONDecodeError as e:
        log.error(f"Bodyweight extraction: JSON parse failed: {e}")
        return {"detected": False}
    except Exception as e:
        log.error(f"Bodyweight extraction failed: {e}")
        return {"detected": False}
