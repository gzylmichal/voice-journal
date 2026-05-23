"""
Notion collector — journal summary & to-do items.

Reads yesterday's structured journal summary from Notion.
Returns structured dict.
"""

import requests
from datetime import datetime, timedelta


NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def collect_notion(cfg: dict) -> dict:
    """Fetch yesterday's journal page, return structured data."""

    api_key = cfg.get("notion_api_key", "")
    db_id = cfg.get("notion_journal_db_id", "")

    if not api_key or not db_id:
        return {"configured": False, "blocks": [], "title": None, "date": None}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    query_payload = {
        "filter": {
            "property": "Date",
            "date": {"equals": yesterday},
        },
        "page_size": 1,
    }

    resp = requests.post(
        f"{NOTION_API_URL}/databases/{db_id}/query",
        headers=headers,
        json=query_payload,
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])

    if not results:
        return {
            "configured": True, "found": False,
            "blocks": [], "title": None, "date": yesterday,
        }

    page = results[0]
    title = _extract_title(page)

    blocks_resp = requests.get(
        f"{NOTION_API_URL}/blocks/{page['id']}/children?page_size=100",
        headers=headers,
        timeout=15,
    )
    blocks_resp.raise_for_status()
    raw_blocks = blocks_resp.json().get("results", [])

    blocks = _normalize_blocks(raw_blocks)

    return {
        "configured": True,
        "found": True,
        "title": title,
        "date": yesterday,
        "blocks": blocks,
    }


def _extract_title(page: dict) -> str:
    for prop_val in page.get("properties", {}).values():
        if prop_val.get("type") == "title":
            title_parts = prop_val.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_parts)
    return ""


def _rich_text_to_str(rich_text: list) -> str:
    return "".join(t.get("plain_text", "") for t in rich_text)


def _normalize_blocks(blocks: list) -> list[dict]:
    """Convert Notion blocks into simple [{type, text, checked}] structures."""
    out = []
    for block in blocks:
        bt = block.get("type", "")
        bd = block.get(bt, {})
        text = _rich_text_to_str(bd.get("rich_text", []))
        if not text and bt != "divider":
            continue

        if bt == "paragraph":
            out.append({"type": "paragraph", "text": text})
        elif bt in ("heading_1", "heading_2", "heading_3"):
            out.append({"type": "heading", "text": text, "level": int(bt[-1])})
        elif bt == "bulleted_list_item":
            out.append({"type": "bullet", "text": text})
        elif bt == "numbered_list_item":
            out.append({"type": "number", "text": text})
        elif bt == "to_do":
            out.append({"type": "todo", "text": text, "checked": bd.get("checked", False)})
        elif bt == "toggle":
            out.append({"type": "toggle", "text": text})
        elif bt == "callout":
            out.append({"type": "callout", "text": text})
        elif bt == "code":
            out.append({"type": "code", "text": _rich_text_to_str(bd.get("rich_text", []))})
        elif bt == "divider":
            out.append({"type": "divider", "text": ""})
    return out


def collect_notion_week(cfg: dict) -> dict:
    """
    Fetch the last 7 days of journal pages for the weekly digest.
    Returns list of {date, title, summary} dicts.
    """
    api_key = cfg.get("notion_api_key", "")
    db_id   = cfg.get("notion_journal_db_id", "")

    if not api_key or not db_id:
        return {"configured": False, "entries": []}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    query_payload = {
        "filter": {
            "property": "Date",
            "date": {"on_or_after": since},
        },
        "sorts": [{"property": "Date", "direction": "ascending"}],
        "page_size": 10,
    }

    resp = requests.post(
        f"{NOTION_API_URL}/databases/{db_id}/query",
        headers=headers,
        json=query_payload,
        timeout=15,
    )
    resp.raise_for_status()
    pages = resp.json().get("results", [])

    entries = []
    for page in pages:
        title = _extract_title(page)
        date_val = ""
        date_prop = page.get("properties", {}).get("Date", {}).get("date")
        if date_prop:
            date_val = date_prop.get("start", "")

        # Fetch first 6 blocks for a text snippet
        try:
            blocks_resp = requests.get(
                f"{NOTION_API_URL}/blocks/{page['id']}/children?page_size=6",
                headers=headers,
                timeout=10,
            )
            raw_blocks = blocks_resp.json().get("results", [])
            blocks = _normalize_blocks(raw_blocks)
            # Build a plain-text summary: first 3 non-heading blocks
            snippets = [
                b["text"] for b in blocks
                if b["type"] not in ("heading", "divider") and b.get("text")
            ][:3]
            summary = " ".join(snippets)[:400]
        except Exception:
            summary = ""

        entries.append({"date": date_val, "title": title, "summary": summary})

    return {"configured": True, "entries": entries}


def to_text(data: dict) -> str:
    if not data or not data.get("configured"):
        return "[Notion not configured]"
    if not data.get("found"):
        return f"[No journal entry for {data.get('date')}]"
    lines = [f"Journal: {data['date']}" + (f" — {data['title']}" if data['title'] else "")]
    for b in data["blocks"]:
        if b["type"] == "heading":
            lines.append(f"[{b['text']}]")
        elif b["type"] == "bullet":
            lines.append(f"  • {b['text']}")
        elif b["type"] == "number":
            lines.append(f"  - {b['text']}")
        elif b["type"] == "todo":
            marker = "[x]" if b["checked"] else "[ ]"
            lines.append(f"  {marker} {b['text']}")
        elif b["type"] == "toggle":
            lines.append(f"  ▸ {b['text']}")
        elif b["type"] == "callout":
            lines.append(f"  ⓘ {b['text']}")
        elif b["type"] == "divider":
            lines.append("---")
        else:
            lines.append(b["text"])
    return "\n".join(lines)
