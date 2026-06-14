"""
Task aging collector — surfaces open Notion tasks that have been open too long.

Queries the shared Task DB for pages where Done == false, computes age from
page created_time, and returns tasks open ≥ task_aging_days (cap 3, oldest first).
Degrades gracefully: not configured or fetch error → empty result, no crash.
"""

import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger("debrief.tasks")

NOTION_VERSION = "2022-06-28"


def collect_stale_tasks(cfg: dict) -> dict:
    api_key = cfg.get("notion_api_key", "")
    db_id   = cfg.get("notion_task_db_id", "")
    aging_days = int(cfg.get("task_aging_days", 7))

    if not api_key or not db_id:
        return {"configured": False, "tasks": []}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    payload = {
        "filter": {
            "property": "Done",
            "checkbox": {"equals": False},
        },
        "page_size": 100,
    }

    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=headers,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        pages = resp.json().get("results", [])
    except Exception as exc:
        logger.warning("Task DB fetch failed (non-fatal): %s", exc)
        return {"configured": True, "tasks": [], "error": str(exc)}

    now = datetime.now(timezone.utc)
    stale = []
    for page in pages:
        created_raw = page.get("created_time", "")
        try:
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            age_days = (now - created).days
        except Exception:
            continue

        if age_days < aging_days:
            continue

        title = _extract_title(page)
        stale.append({"title": title, "age_days": age_days})

    stale.sort(key=lambda t: t["age_days"], reverse=True)
    stale = stale[:3]

    return {"configured": True, "tasks": stale, "aging_days": aging_days}


def _extract_title(page: dict) -> str:
    for prop_val in page.get("properties", {}).values():
        if prop_val.get("type") == "title":
            parts = prop_val.get("title", [])
            return "".join(t.get("plain_text", "") for t in parts)
    return "(untitled)"


def to_text(data: dict) -> str:
    if not data or not data.get("configured"):
        return ""
    tasks = data.get("tasks", [])
    if not tasks:
        return ""
    lines = []
    for t in tasks:
        lines.append(f"{t['title']} — open {t['age_days']} days. Still relevant?")
    return "\n".join(lines)
