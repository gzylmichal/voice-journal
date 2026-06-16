"""pipeline/notify.py — ntfy.sh push notification transport.

Iron rule: a notify failure NEVER raises — log warning and return False.
The pipeline must work identically with notifications disabled (NTFY_TOPIC empty).
"""

import logging
import requests
from pipeline import config
from pipeline.extractors import _sets_detail_summary

logger = logging.getLogger(__name__)


def send_notification(message, title="Voice Journal", priority="default"):
    """Send a push notification via ntfy.sh.

    Returns True on success, False if disabled or on any error.
    """
    if not config.NTFY_TOPIC:
        return False
    url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
    try:
        resp = requests.post(
            url,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority},
            timeout=10,
        )
        return resp.status_code < 300
    except Exception as exc:
        logger.warning("ntfy notification failed: %s", exc)
        return False


def send_session_plan(data: dict) -> bool:
    """Push today's prescribed session plan via ntfy. Best-effort, never raises.

    data: output of debrief.collectors.workout_collector.collect_session_plan
    Returns True if the push succeeded, False otherwise (disabled, empty, or error).
    """
    try:
        if not data or not data.get("plan_available"):
            return False
        split = data.get("split", "")
        plan  = data.get("plan", [])
        if not plan:
            return False
        line = _format_session_plan_push(split, plan)
        if not line:
            return False
        return send_notification(line, title="Today's session")
    except Exception as exc:
        logger.warning("send_session_plan failed: %s", exc)
        return False


def _format_session_plan_push(split: str, plan: list) -> str:
    """Compact text for the push notification: slot lines joined by newlines."""
    lines = [f"{split} day"]
    for slot in plan:
        slot_name = slot.get("slot", "?")
        if slot.get("reminder"):
            lines.append(f"  {slot_name} — reminder")
        elif "rec" in slot:
            rec        = slot["rec"]
            exercise   = slot.get("exercise") or slot_name
            last       = slot.get("last_sets_str", "")
            weight_kg  = rec.get("weight_kg")
            target_reps = rec.get("target_reps")
            action     = rec.get("action", "")
            if action == "no_recommendation":
                lines.append(f"  {exercise} (last {last})" if last else f"  {exercise}")
            elif weight_kg is not None:
                tgt = f"{weight_kg}×{target_reps}" if target_reps else f"{weight_kg} kg"
                lines.append(f"  {exercise} → {tgt}" + (f" (last {last})" if last else ""))
            elif target_reps is not None:
                lines.append(f"  {exercise} → BW×{target_reps}" + (f" (last {last})" if last else ""))
            else:
                lines.append(f"  {exercise} (last {last})" if last else f"  {exercise}")
        else:
            exercise  = slot.get("exercise") or slot_name
            last      = slot.get("last_sets_str", "")
            lines.append(f"  {exercise} (last {last})" if last else f"  {exercise}")
    return "\n".join(lines)


def send_batch_summary(workout, tasks, events, bodyweight, transcripts, *, bw_rejected=None):
    """Build and send a one-line push notification summarising the upload batch.

    Sends nothing for empty batches (no workout, tasks, events, or bodyweight).
    Never raises — exceptions are logged and swallowed.
    """
    try:
        segments = []

        if workout and workout.get("detected") and workout.get("exercises"):
            parts = []
            for ex in workout["exercises"]:
                _, weight_str = _sets_detail_summary(ex)
                name = ex.get("name", "?")
                parts.append(f"{name} {weight_str}")
            segments.append("✓ " + " · ".join(parts) + " → Workout DB")

        if tasks:
            n = len(tasks)
            segments.append(f"{n} task{'s' if n != 1 else ''}")

        if events:
            n = len(events)
            segments.append(f"{n} event{'s' if n != 1 else ''}")

        if bw_rejected:
            val = bw_rejected.get("value", "?")
            last = bw_rejected.get("last", "?")
            segments.append(f"BW rejected: {val} kg vs last {last} kg")
        elif bodyweight and bodyweight.get("detected") and bodyweight.get("weight_kg") is not None:
            segments.append(f"BW {bodyweight['weight_kg']:.1f} kg")

        if not segments:
            return

        summary = " · ".join(segments)

        combined = " / ".join(t.get("text", "") for t in (transcripts or []) if t.get("text"))
        if combined:
            snippet = combined[:500]
            if len(combined) > 500:
                snippet += "…"
            message = f"{summary}\n\n{snippet}"
        else:
            message = summary

        send_notification(message)
    except Exception as exc:
        logger.warning("send_batch_summary failed: %s", exc)
