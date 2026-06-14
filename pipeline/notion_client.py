"""pipeline/notion_client.py — Notion API write operations."""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

from pipeline.config import (
    NOTION_API_URL,
    NOTION_BODYWEIGHT_DB_ID,
    NOTION_DATABASE_ID,
    NOTION_ENABLED,
    NOTION_TASK_DB_ID,
    NOTION_TOKEN,
    NOTION_VERSION,
    NOTION_WORKOUT_DB_ID,
)
from pipeline.extractors import _sets_detail_summary, extract_top_weight, infer_muscle_group
from models import parse_workout_entry

log = logging.getLogger(__name__)


def create_notion_workout_entries(workout: dict, recording_date: date, resolved_bodyweight: Optional[float] = None) -> int:
    """
    Write each exercise in the workout dict as a row in the Notion Workout Log DB.
    Returns the number of rows successfully created.
    """
    if not NOTION_TOKEN or not NOTION_WORKOUT_DB_ID:
        log.warning("NOTION_TOKEN or NOTION_WORKOUT_DB_ID not set — skipping workout DB write")
        return 0

    if not workout.get("detected") or not workout.get("exercises"):
        return 0

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    session_type = workout.get("workout_name", "Other")
    SESSION_MAP = {
        "chest":    "Chest",
        "push":     "Chest",
        "deadlift": "Deadlift",
        "pull":     "Deadlift",
        "squat":    "Squat",
        "leg":      "Squat",
        "arm":      "Arms",
        "upper":    "Other",
    }
    session_normalised = "Other"
    for key, val in SESSION_MAP.items():
        if key in session_type.lower():
            session_normalised = val
            break

    created = 0
    for ex in workout["exercises"]:
        name = (ex.get("name") or "").strip()
        if not name:
            continue

        muscle_group = infer_muscle_group(name)
        sets, weight_str = _sets_detail_summary(ex)
        if ex.get("is_bodyweight"):
            added = ex.get("added_weight_kg") or 0.0
            weight_str = f"BW + {added:.0f}kg" if added else "BW"
            top_weight = (resolved_bodyweight + added) if resolved_bodyweight is not None else None
        else:
            if weight_str == "—":
                weight_str = ""
            top_weight = extract_top_weight(weight_str)
        detail = ex.get("sets_detail") or []
        reps_values = [s.get("reps") for s in detail if s.get("reps") is not None]
        reps = max(set(reps_values), key=reps_values.count) if reps_values else ex.get("reps")

        properties: dict = {
            "Exercise":     {"title": [{"text": {"content": name[:2000]}}]},
            "Date":         {"date": {"start": recording_date.isoformat()}},
            "Session":      {"select": {"name": session_normalised}},
            "Muscle Group": {"select": {"name": muscle_group}},
        }

        if sets is not None:
            properties["Sets"] = {"number": sets}
        if reps is not None:
            properties["Reps"] = {"number": reps}
        if weight_str:
            properties["Weight"] = {"rich_text": [{"text": {"content": weight_str[:2000]}}]}
        if top_weight is not None:
            properties["Top Set (kg)"] = {"number": top_weight}
        if ex.get("rpe") is not None:
            properties["RPE"] = {"number": float(ex["rpe"])}
        if ex.get("pain_note"):
            properties["Pain note"] = {"rich_text": [{"text": {"content": ex["pain_note"][:2000]}}]}

        payload = {
            "parent": {"database_id": NOTION_WORKOUT_DB_ID},
            "properties": properties,
        }

        try:
            resp = requests.post(NOTION_API_URL, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                weight_display = f" @ {weight_str}" if weight_str else ""
                top_display    = f" (top {top_weight}kg)" if top_weight else ""
                log.info(f"Workout entry: {name} [{muscle_group}] {sets}×{reps or '—'}{weight_display}{top_display}")
                created += 1
            else:
                log.error(f"Workout DB error {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            log.error(f"Failed to write workout entry '{name}': {e}")

    return created


def create_notion_tasks(tasks: List[dict]) -> int:
    """
    Create tasks in Notion task database.
    Returns count of successfully created tasks.
    """
    if not tasks or not NOTION_ENABLED:
        return 0

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    created = 0
    for task in tasks:
        title = task.get("title", "").strip()
        if not title:
            continue

        properties = {
            "Task":           {"title": [{"text": {"content": title}}]},
            "Priority Level": {"select": {"name": task.get("priority", "Normal")}},
            "Type":           {"select": {"name": task.get("type", "Personal")}},
            "Done":           {"checkbox": False},
        }

        if task.get("description"):
            properties["Description"] = {
                "rich_text": [{"text": {"content": task["description"][:2000]}}]
            }

        if task.get("due_date"):
            try:
                datetime.strptime(task["due_date"], "%Y-%m-%d")
                properties["Due Date"] = {"date": {"start": task["due_date"]}}
            except ValueError:
                log.warning(f"Invalid due_date for task '{title}': {task.get('due_date')}")

        payload = {
            "parent": {"database_id": NOTION_TASK_DB_ID},
            "properties": properties,
        }

        try:
            resp = requests.post(NOTION_API_URL, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                log.info(f"Task created: '{title}' [{task.get('type')}]")
                created += 1
            else:
                log.error(f"Notion task API error {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            log.error(f"Failed to create task '{title}': {e}")

    return created


def find_and_archive_draft(target_date: date) -> bool:
    """
    Find a draft journal page for target_date in Notion and archive it.
    Returns True if at least one page was archived.
    """
    if not NOTION_ENABLED:
        return False

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    query_payload = {
        "filter": {
            "property": "Date",
            "date": {"equals": target_date.isoformat()},
        },
        "page_size": 10,
    }

    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
            headers=headers,
            json=query_payload,
            timeout=15,
        )
        resp.raise_for_status()
        pages = resp.json().get("results", [])

        archived = 0
        for page in pages:
            page_id = page["id"]
            archive_resp = requests.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=headers,
                json={"archived": True},
                timeout=15,
            )
            if archive_resp.status_code == 200:
                log.info(f"Archived draft page: {page_id}")
                archived += 1
            else:
                log.warning(f"Failed to archive page {page_id}: {archive_resp.status_code}")

        return archived > 0

    except Exception as e:
        log.error(f"Error archiving draft: {e}")
        return False


def markdown_to_notion_blocks(md_content: str) -> List[dict]:
    """Convert markdown text to Notion API block objects."""
    blocks = []
    lines = md_content.split("\n")

    if lines and lines[0].strip() == "---":
        try:
            end_idx = lines.index("---", 1)
            lines = lines[end_idx + 1:]
        except ValueError:
            pass

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            i += 1
            continue

        # Code fence: collect lines until closing ```
        if stripped.startswith("```"):
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip the closing ```
            code_content = "\n".join(code_lines).strip()
            if code_content:
                blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": code_content[:2000]}}],
                        "language": "plain text",
                    },
                })
            continue

        if stripped.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": stripped[3:].strip()[:2000]}}]}})
            i += 1; continue

        if stripped.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": stripped[4:].strip()[:2000]}}]}})
            i += 1; continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            text = stripped[2:].strip().removeprefix("[ ] ").removeprefix("[x] ")
            blocks.append({"object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}})
            i += 1; continue

        if stripped in ("---", "***", "___"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1; continue

        if stripped.startswith("*") and stripped.endswith("*") and len(stripped) > 2:
            blocks.append({"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text",
                    "text": {"content": stripped[1:-1][:2000]},
                    "annotations": {"italic": True, "color": "gray"}}]}})
            i += 1; continue

        para_lines = []
        while i < len(lines):
            l = lines[i].strip()
            if (not l or l.startswith("#") or l.startswith("- ") or
                    l.startswith("* ") or l in ("---", "***", "___") or
                    (l.startswith("*") and l.endswith("*"))):
                break
            para_lines.append(l)
            i += 1

        if para_lines:
            full_text = " ".join(para_lines)
            for chunk_start in range(0, len(full_text), 2000):
                blocks.append({"object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text",
                        "text": {"content": full_text[chunk_start:chunk_start + 2000]}}]}})
            continue

        i += 1

    return blocks


def extract_title(md_content: str) -> str:
    for line in md_content.split("\n"):
        if line.strip().startswith("## "):
            return line.strip()[3:].strip()
    return f"Journal — {date.today().strftime('%B %d, %Y')}"


def upload_to_notion(md_content: str, today: date) -> bool:
    title  = extract_title(md_content)
    blocks = markdown_to_notion_blocks(md_content)

    if len(blocks) > 100:
        log.warning(f"Entry has {len(blocks)} blocks, truncating to 100")
        blocks = blocks[:100]

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
            "Date": {"date": {"start": today.isoformat()}}
        },
        "children": blocks
    }

    try:
        resp = requests.post(
            NOTION_API_URL,
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            log.info(f"Notion page created: {title} → {resp.json().get('url', '')}")
            return True
        else:
            log.error(f"Notion API error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        log.error(f"Notion upload failed: {e}")
        return False


def store_bodyweight(weight_kg: float, recording_date: date) -> bool:
    """Write a bodyweight reading to the Notion Bodyweight Log DB. Returns True on success."""
    if not NOTION_TOKEN or not NOTION_BODYWEIGHT_DB_ID:
        log.warning("NOTION_TOKEN or NOTION_BODYWEIGHT_DB_ID not set — skipping bodyweight write")
        return False
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    payload = {
        "parent": {"database_id": NOTION_BODYWEIGHT_DB_ID},
        "properties": {
            "Date":        {"date":   {"start": recording_date.isoformat()}},
            "Weight (kg)": {"number": weight_kg},
        },
    }
    try:
        resp = requests.post(NOTION_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            log.info(f"Bodyweight stored: {weight_kg} kg on {recording_date}")
            return True
        log.error(f"Bodyweight DB error {resp.status_code}: {resp.text[:300]}")
        return False
    except Exception as e:
        log.error(f"Failed to store bodyweight: {e}")
        return False


def fetch_latest_bodyweight(before_date: date) -> Optional[float]:
    """Return the most recent bodyweight (kg) recorded on or before before_date, or None."""
    if not NOTION_TOKEN or not NOTION_BODYWEIGHT_DB_ID:
        return None
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    url = f"https://api.notion.com/v1/databases/{NOTION_BODYWEIGHT_DB_ID}/query"
    payload = {
        "filter": {"property": "Date", "date": {"on_or_before": before_date.isoformat()}},
        "sorts":  [{"property": "Date", "direction": "descending"}],
        "page_size": 1,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            log.error(f"Bodyweight fetch error {resp.status_code}: {resp.text[:200]}")
            return None
        results = resp.json().get("results", [])
        if not results:
            return None
        props = results[0].get("properties", {})
        weight = props.get("Weight (kg)", {}).get("number")
        return float(weight) if weight is not None else None
    except Exception as e:
        log.error(f"Failed to fetch latest bodyweight: {e}")
        return None


def fetch_prior_workout_session(
    today_exercises: List[str],
    before_date: date,
    lookback_days: int = 90,
) -> Dict[str, List[dict]]:
    """Return prior Notion workout rows for comparison in the pre-workout brief.

    Finds the most recent workout date (strictly before before_date) that shares
    at least one exercise with today_exercises. Falls back to the most recent
    workout day when there is no exercise overlap.

    Returns dict mapping exercise_name → list of all history rows for that exercise
    (sorted ascending by date), or {} on missing config / API error.
    """
    if not NOTION_TOKEN or not NOTION_WORKOUT_DB_ID:
        log.info("NOTION_WORKOUT_DB_ID not configured — skipping comparison fetch")
        return {}

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    cutoff = (before_date - timedelta(days=lookback_days)).isoformat()
    url = f"https://api.notion.com/v1/databases/{NOTION_WORKOUT_DB_ID}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "Date", "date": {"on_or_after": cutoff}},
                {"property": "Date", "date": {"before": before_date.isoformat()}},
            ]
        },
        "sorts": [{"property": "Date", "direction": "descending"}],
        "page_size": 200,
    }

    try:
        pages: List[dict] = []
        while True:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            if resp.status_code != 200:
                log.warning("Workout DB fetch error %s: %s", resp.status_code, resp.text[:200])
                return {}
            data = resp.json()
            pages.extend(data.get("results", []))
            if data.get("has_more"):
                payload["start_cursor"] = data["next_cursor"]
            else:
                break
    except Exception as exc:
        log.warning("fetch_prior_workout_session failed: %s", exc)
        return {}

    if not pages:
        return {}

    entries = [parse_workout_entry(p) for p in pages]
    # entries are sorted descending by date

    today_lower = {n.lower() for n in today_exercises}

    # Find most recent date that overlaps with today's exercises
    overlap_date: Optional[str] = None
    for entry in entries:
        if entry.get("exercise", "").lower() in today_lower:
            overlap_date = entry.get("date")
            break

    # Fall back to most recent workout day if no overlap found
    comparison_date = overlap_date or (entries[0].get("date") if entries else None)
    if not comparison_date:
        return {}

    # Collect all history rows per exercise (ascending) for recommend_progression
    history_by_exercise: Dict[str, List[dict]] = {}
    for entry in reversed(entries):  # ascending now
        name = entry.get("exercise") or ""
        if not name:
            continue
        history_by_exercise.setdefault(name, []).append(dict(entry))

    log.info(
        "Comparison session: %s (overlap=%s, %d exercises in history)",
        comparison_date, bool(overlap_date), len(history_by_exercise),
    )
    return history_by_exercise


def fetch_bodyweight_entries(weeks: int) -> List[Tuple[str, float]]:
    """Return (date_str, kg) pairs from the last N weeks, sorted ascending."""
    if not NOTION_TOKEN or not NOTION_BODYWEIGHT_DB_ID:
        return []
    if weeks <= 0:
        weeks = 1
    cutoff = (date.today() - timedelta(weeks=weeks)).isoformat()
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    url = f"https://api.notion.com/v1/databases/{NOTION_BODYWEIGHT_DB_ID}/query"
    payload = {
        "filter": {"property": "Date", "date": {"on_or_after": cutoff}},
        "sorts":  [{"property": "Date", "direction": "ascending"}],
        "page_size": 100,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            log.error(f"Bodyweight entries fetch error {resp.status_code}: {resp.text[:200]}")
            return []
        entries = []
        for r in resp.json().get("results", []):
            props = r.get("properties", {})
            d  = (props.get("Date") or {}).get("date", {}).get("start")
            kg = (props.get("Weight (kg)") or {}).get("number")
            if d and kg is not None:
                entries.append((d, float(kg)))
        return entries
    except Exception as e:
        log.error(f"Failed to fetch bodyweight entries: {e}")
        return []
