"""Tests for debrief/collectors/task_collector.py — task aging section."""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

DEBRIEF_DIR = Path(__file__).parent.parent / "debrief"
sys.path.insert(0, str(DEBRIEF_DIR))
sys.path.insert(0, str(DEBRIEF_DIR / "collectors"))

from task_collector import collect_stale_tasks, to_text


def _make_page(title: str, created_days_ago: int) -> dict:
    created = (datetime.now(timezone.utc) - timedelta(days=created_days_ago)).isoformat()
    return {
        "created_time": created,
        "properties": {
            "Task": {
                "type": "title",
                "title": [{"plain_text": title}],
            }
        },
    }


def _cfg(configured=True, aging_days=7):
    if not configured:
        return {"notion_api_key": "", "notion_task_db_id": ""}
    return {
        "notion_api_key": "secret_key",
        "notion_task_db_id": "db123",
        "task_aging_days": aging_days,
    }


def _mock_response(pages: list) -> MagicMock:
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = {"results": pages}
    return m


# ── Not configured ─────────────────────────────────────────────────────────

def test_not_configured_returns_empty():
    result = collect_stale_tasks(_cfg(configured=False))
    assert result["configured"] is False
    assert result["tasks"] == []


def test_to_text_not_configured_returns_empty_string():
    assert to_text({"configured": False, "tasks": []}) == ""


# ── Aging threshold ─────────────────────────────────────────────────────────

def test_task_6_days_excluded():
    pages = [_make_page("buy filters", 6)]
    with patch("requests.post", return_value=_mock_response(pages)):
        result = collect_stale_tasks(_cfg(aging_days=7))
    assert result["tasks"] == []


def test_task_7_days_included():
    pages = [_make_page("buy filters", 7)]
    with patch("requests.post", return_value=_mock_response(pages)):
        result = collect_stale_tasks(_cfg(aging_days=7))
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["title"] == "buy filters"
    assert result["tasks"][0]["age_days"] == 7


def test_task_8_days_included():
    pages = [_make_page("clean garage", 8)]
    with patch("requests.post", return_value=_mock_response(pages)):
        result = collect_stale_tasks(_cfg(aging_days=7))
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["age_days"] == 8


# ── Cap at 3, oldest first ──────────────────────────────────────────────────

def test_cap_at_3_oldest_first():
    pages = [
        _make_page("task A", 10),
        _make_page("task B", 20),
        _make_page("task C", 15),
        _make_page("task D", 30),
    ]
    with patch("requests.post", return_value=_mock_response(pages)):
        result = collect_stale_tasks(_cfg(aging_days=7))
    tasks = result["tasks"]
    assert len(tasks) == 3
    assert tasks[0]["title"] == "task D"   # oldest (30d)
    assert tasks[1]["title"] == "task B"   # 20d
    assert tasks[2]["title"] == "task C"   # 15d


def test_fewer_than_3_tasks_returned_as_is():
    pages = [_make_page("solo task", 10)]
    with patch("requests.post", return_value=_mock_response(pages)):
        result = collect_stale_tasks(_cfg(aging_days=7))
    assert len(result["tasks"]) == 1


# ── Fetch error degrades gracefully ────────────────────────────────────────

def test_fetch_error_returns_empty_no_crash():
    with patch("requests.post", side_effect=Exception("connection refused")):
        result = collect_stale_tasks(_cfg())
    assert result["configured"] is True
    assert result["tasks"] == []
    assert "error" in result


# ── to_text formatting ──────────────────────────────────────────────────────

def test_to_text_formats_correctly():
    data = {
        "configured": True,
        "tasks": [
            {"title": "buy filters", "age_days": 12},
        ],
    }
    text = to_text(data)
    assert "buy filters" in text
    assert "12" in text
    assert "Still relevant?" in text


def test_to_text_empty_tasks_returns_empty():
    assert to_text({"configured": True, "tasks": []}) == ""


def test_to_text_multiple_tasks():
    data = {
        "configured": True,
        "tasks": [
            {"title": "task A", "age_days": 30},
            {"title": "task B", "age_days": 20},
            {"title": "task C", "age_days": 15},
        ],
    }
    text = to_text(data)
    lines = text.strip().split("\n")
    assert len(lines) == 3
    assert "task A" in lines[0]
    assert "task B" in lines[1]
