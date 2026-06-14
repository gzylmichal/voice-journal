"""pipeline/brief.py — Pre-workout brief push notification.

Fires once per day on the first workout batch. Deterministic: no LLM.
Iron rule: any failure here must NOT propagate to run_upload_mode.
"""

import logging
from datetime import date
from typing import List, Optional

from analytics import recommend_progression
from pipeline.extractors import _sets_detail_summary
from pipeline.notion_client import fetch_prior_workout_session
from pipeline.notify import send_notification

log = logging.getLogger(__name__)


def _is_first_workout_batch(pending_writes: List[dict]) -> bool:
    """Return True when no earlier batch today already contained a detected workout."""
    detected_count = sum(
        1 for pw in (pending_writes or [])
        if (pw.get("workout") or {}).get("detected")
    )
    return detected_count == 0


def _format_exercise_line(name: str, last_sets_str: str, rec: dict) -> str:
    """Build a compact summary line for one exercise.

    Examples:
        Bench: last 80x8,8,7 → 80, beat 8/8/8
        OHP: last 50x10,10 → 52.5x3x10
        Pull-ups: last BWx8 → ×9
    """
    last = last_sets_str or "—"
    action = rec.get("action")
    weight = rec.get("weight_kg")
    reps = rec.get("target_reps")
    note = rec.get("note") or ""

    if action == "no_recommendation":
        return f"{name}: last {last} (no rec — too few sessions)"

    if action == "progress":
        if weight is None and reps is not None:
            # Pure bodyweight
            return f"{name}: last {last} → ×{reps}"
        if weight is not None and reps is not None:
            return f"{name}: last {last} → {weight}×{reps}"
        return f"{name}: last {last} → progress"

    # repeat
    if weight is not None and reps is not None:
        # Determine set count from last_sets_str
        set_count = len([t for t in last.replace(" ", "").split(",") if t]) if last and last != "—" else 0
        sets_str = f"{set_count}×" if set_count else ""
        target = f"{weight}, beat {'/'.join(str(reps) for _ in range(set_count)) or str(reps)}"
        if note:
            target = f"{target} {note}"
        return f"{name}: last {last} → {target}"
    if note:
        return f"{name}: last {last} → {note}"
    return f"{name}: last {last} → repeat"


def send_preworkout_brief(
    workout: dict,
    recording_date: date,
    pending_writes: Optional[List[dict]] = None,
) -> None:
    """Build and send a pre-workout push notification summarising today's session.

    Trigger conditions:
    - workout.detected is True
    - This is the first workout batch of the day (no earlier pending_write has detected workout)
    - NTFY_TOPIC is set (handled by send_notification)

    Never raises. Any failure is logged and swallowed.
    """
    try:
        if not (workout and workout.get("detected") and workout.get("exercises")):
            return

        if not _is_first_workout_batch(pending_writes or []):
            log.info("brief: not first workout batch today — skipping brief")
            return

        today_exercises = [
            ex.get("name", "").strip()
            for ex in workout["exercises"]
            if ex.get("name", "").strip()
        ]
        if not today_exercises:
            return

        session_name = workout.get("workout_name") or "Workout"

        # Fetch comparison history from Notion (gracefully returns {} on failure)
        history_by_exercise = fetch_prior_workout_session(today_exercises, recording_date)

        lines = []
        for ex in workout["exercises"]:
            name = (ex.get("name") or "").strip()
            if not name:
                continue

            ex_history = history_by_exercise.get(name, [])
            rec = recommend_progression(ex_history) if ex_history else {
                "action": "no_recommendation", "weight_kg": None,
                "target_reps": None, "note": None,
                "last_sets_str": "", "last_date": "",
            }

            _, last_sets_str = _sets_detail_summary(ex)
            # Use history last_sets_str if available (from actual past session)
            display_last = rec.get("last_sets_str") or last_sets_str or "—"

            lines.append(_format_exercise_line(name, display_last, rec))

        if not lines:
            return

        message = f"{session_name}. " + " · ".join(lines) + "."
        send_notification(message, title="Pre-workout brief", priority="high")
        log.info("Pre-workout brief sent: %s", message[:120])

    except Exception as exc:
        log.warning("send_preworkout_brief failed: %s", exc)
