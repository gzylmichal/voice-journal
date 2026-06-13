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
