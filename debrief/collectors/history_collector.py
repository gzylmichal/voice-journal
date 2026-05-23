"""
On This Day collector — Muffinlabs / Wikipedia.

Returns 3 notable historical events for today's date.
No API key required.
Docs: http://history.muffinlabs.com/
"""

import logging
import requests
from datetime import datetime

logger = logging.getLogger("debrief.history")

API_URL = "http://history.muffinlabs.com/date"

# Skip very ancient or trivial entries
SKIP_KEYWORDS = ("b.", "d.", "died", "born")


def _is_notable(text: str) -> bool:
    """Basic filter — prefer events over births/deaths, skip very short entries."""
    if len(text) < 30:
        return False
    return True


def collect_history(cfg: dict) -> dict:
    today = datetime.now()

    try:
        resp = requests.get(
            f"{API_URL}/{today.month}/{today.day}",
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("History API failed: %s", exc)
        return {"available": False, "events": [], "date": today.strftime("%B %d")}

    events_raw = data.get("data", {}).get("Events", [])

    # Pick 3 notable events, prefer ones with Wikipedia links
    events = []
    for e in events_raw:
        text = e.get("text", "").strip()
        year = e.get("year", "")
        links = e.get("links", [])
        wiki_url = links[0].get("link", "") if links else ""

        if not _is_notable(text):
            continue

        events.append({
            "year": year,
            "text": text,
            "url": wiki_url,
        })

        if len(events) >= 3:
            break

    return {
        "available": True,
        "date": today.strftime("%B %d"),
        "events": events,
    }


def to_text(data: dict) -> str:
    if not data or not data.get("available"):
        return "[History unavailable]"
    lines = [f"ON THIS DAY ({data['date']}):"]
    for e in data.get("events", []):
        lines.append(f"  {e['year']} — {e['text']}")
    return "\n".join(lines)
