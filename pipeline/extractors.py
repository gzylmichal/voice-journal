"""pipeline/extractors.py — AI extraction for workout, tasks, and calendar events."""

import json
import logging
import re
from datetime import date
from typing import List, Optional, Tuple

import ai_client
from pipeline.config import GCAL_ENABLED, NOTION_ENABLED
from pipeline.prompts import (
    BODYWEIGHT_SYSTEM_PROMPT,
    CALENDAR_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    TASK_SYSTEM_PROMPT,
    WORKOUT_SYSTEM_PROMPT,
)

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


def _parse_json_response(raw: str):
    """Strip markdown fences and parse JSON. Raises json.JSONDecodeError on failure."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])
    return json.loads(raw.strip())


def _empty_extraction() -> dict:
    return {
        "workout": {"detected": False, "exercises": []},
        "tasks": [],
        "events": [],
        "bodyweight": {"detected": False},
    }


def extract_all(transcripts: List[dict], recording_date: date) -> dict:
    """Single LLM call extracting workout, tasks, events, and bodyweight."""
    combined_text = "\n\n".join(
        f"[{t['time']}] {t['text']}"
        for t in transcripts if not t.get("error")
    )
    if not combined_text.strip():
        return _empty_extraction()

    has_weigh_in = any(phrase in combined_text.lower() for phrase in BODYWEIGHT_WEIGH_IN_PHRASES)

    user_message = (
        f"Recording date: {recording_date.strftime('%A, %B %d, %Y')} "
        f"({recording_date.isoformat()})\n\n"
        f"{combined_text}"
    )

    log.info("Running unified extraction (workout + tasks + events + bodyweight)...")

    try:
        raw = ai_client.call_ai(
            user_message, EXTRACTION_SYSTEM_PROMPT, "Unified extraction", temperature=0
        )
        result = _parse_json_response(raw)

        if not isinstance(result, dict):
            log.error("Unified extraction: response is not a dict")
            return _empty_extraction()

        workout = result.get("workout") or {"detected": False, "exercises": []}
        tasks = result.get("tasks") or []
        events = result.get("events") or []
        bodyweight = result.get("bodyweight") or {"detected": False}

        if not isinstance(tasks, list):
            tasks = []
        if not isinstance(events, list):
            events = []
        if not isinstance(bodyweight, dict):
            bodyweight = {"detected": False}

        # A1 bodyweight keyword pre-filter applied post-hoc
        if not has_weigh_in:
            log.info("Bodyweight: no weigh-in phrase found — forcing detected: false")
            bodyweight = {"detected": False}
        elif bodyweight.get("detected"):
            log.info(f"Bodyweight detected: {bodyweight.get('weight_kg')} kg")

        if workout.get("detected"):
            log.info(f"Workout: {workout.get('workout_name')} — {len(workout.get('exercises', []))} exercise(s)")
        if tasks:
            log.info(f"Tasks: {len(tasks)} found")
        if events:
            log.info(f"Events: {len(events)} found")

        return {"workout": workout, "tasks": tasks, "events": events, "bodyweight": bodyweight}

    except json.JSONDecodeError as e:
        log.error(f"Unified extraction: JSON parse failed: {e}")
        return _empty_extraction()
    except Exception as e:
        log.error(f"Unified extraction failed: {e}")
        return _empty_extraction()


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
    """Thin wrapper: returns the workout key from extract_all."""
    return extract_all(transcripts, recording_date)["workout"]


def extract_tasks(groq_client, transcripts: List[dict], recording_date: date) -> List[dict]:
    """Thin wrapper: returns the tasks key from extract_all."""
    if not NOTION_ENABLED:
        return []
    return extract_all(transcripts, recording_date)["tasks"]


def extract_calendar_events(groq_client, transcripts: List[dict], recording_date: date) -> List[dict]:
    """Thin wrapper: returns the events key from extract_all."""
    if not GCAL_ENABLED:
        return []
    return extract_all(transcripts, recording_date)["events"]


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
    """Thin wrapper: returns the bodyweight key from extract_all.
    Pre-filter preserved: skip the LLM entirely if no weigh-in phrase found.
    """
    combined_text = "\n\n".join(
        f"[{t['time']}] {t['text']}"
        for t in transcripts if not t.get("error")
    )
    if not combined_text.strip():
        return {"detected": False}
    if not any(phrase in combined_text.lower() for phrase in BODYWEIGHT_WEIGH_IN_PHRASES):
        log.info("Bodyweight: no weigh-in phrase found — skipping LLM call")
        return {"detected": False}
    return extract_all(transcripts, recording_date)["bodyweight"]
