"""Tests for collect_training_suggestion() in workout_collector."""
import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import pytest

DEBRIEF_DIR = Path(__file__).parent.parent / "debrief"
sys.path.insert(0, str(DEBRIEF_DIR))
sys.path.insert(0, str(DEBRIEF_DIR / "collectors"))

from workout_collector import (
    collect_training_suggestion,
    _infer_next_in_cycle,
    _days_since_each_split,
)


def _cfg(configured=True):
    if not configured:
        return {"notion_api_key": "", "notion_workout_db_id": ""}
    return {
        "notion_api_key": "secret_key",
        "notion_workout_db_id": "db456",
    }


def _date(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _mock_collect_workout(session_map: dict):
    """Return a mock collect_workout result for the given {date: session} map."""
    return {
        "configured": True,
        "entries": [],
        "sessions": len(session_map),
        "session_dates": sorted(session_map.keys()),
        "session_types": session_map,
    }


# ── Not configured ──────────────────────────────────────────────────────────

def test_not_configured():
    result = collect_training_suggestion(_cfg(configured=False))
    assert result["configured"] is False


# ── Empty history → section omitted ────────────────────────────────────────

def test_empty_history_returns_no_suggestion():
    with patch("workout_collector.collect_workout", return_value=_mock_collect_workout({})):
        result = collect_training_suggestion(_cfg())
    assert result["configured"] is True
    assert "suggestion" not in result
    assert "fallback" not in result


# ── Clean PPL cycle → correct next suggestion ───────────────────────────────

def test_ppl_cycle_suggests_next():
    """Push → Pull → Legs repeating should suggest the next one."""
    session_map = {
        _date(11): "Push",
        _date(9):  "Pull",
        _date(7):  "Legs",
        _date(5):  "Push",
        _date(3):  "Pull",
        _date(1):  "Legs",
    }
    with patch("workout_collector.collect_workout", return_value=_mock_collect_workout(session_map)):
        result = collect_training_suggestion(_cfg())
    assert result.get("suggestion") == "Push"
    assert result.get("last_date") != ""


def test_two_session_cycle_detected():
    """A/B alternating cycle."""
    session_map = {
        _date(8): "Chest",
        _date(6): "Deadlift",
        _date(4): "Chest",
        _date(2): "Deadlift",
    }
    with patch("workout_collector.collect_workout", return_value=_mock_collect_workout(session_map)):
        result = collect_training_suggestion(_cfg())
    assert result.get("suggestion") == "Chest"


# ── Messy history → fallback to days-since ─────────────────────────────────

def test_messy_history_falls_back_to_days_since():
    """Non-repeating session order → no rotation detected → fallback."""
    session_map = {
        _date(12): "Chest",
        _date(10): "Arms",
        _date(8):  "Deadlift",
        _date(6):  "Chest",
        _date(4):  "Squat",
        _date(2):  "Other",
    }
    with patch("workout_collector.collect_workout", return_value=_mock_collect_workout(session_map)):
        result = collect_training_suggestion(_cfg())
    # Should have fallback, no suggestion
    assert "fallback" in result
    assert "suggestion" not in result


# ── _infer_next_in_cycle unit tests ────────────────────────────────────────

def test_infer_cycle_length_3():
    sessions = ["Push", "Pull", "Legs", "Push", "Pull", "Legs"]
    assert _infer_next_in_cycle(sessions) == "Push"


def test_infer_cycle_length_2():
    sessions = ["A", "B", "A", "B"]
    assert _infer_next_in_cycle(sessions) == "A"


def test_infer_no_cycle_returns_none():
    sessions = ["A", "B", "C", "D", "A", "C"]
    assert _infer_next_in_cycle(sessions) is None


def test_infer_single_session_returns_none():
    assert _infer_next_in_cycle(["Push"]) is None


def test_infer_empty_returns_none():
    assert _infer_next_in_cycle([]) is None


# ── _days_since_each_split unit tests ──────────────────────────────────────

def test_days_since_each_split():
    dated = [
        (_date(5), "Chest"),
        (_date(3), "Deadlift"),
        (_date(1), "Squat"),
    ]
    result = _days_since_each_split(dated)
    assert result["Chest"] == 5
    assert result["Deadlift"] == 3
    assert result["Squat"] == 1


def test_days_since_uses_most_recent_for_repeated_sessions():
    dated = [
        (_date(10), "Chest"),
        (_date(3),  "Chest"),
    ]
    result = _days_since_each_split(dated)
    assert result["Chest"] == 3


# ── Fetch error degrades gracefully ────────────────────────────────────────

def test_fetch_error_no_crash():
    with patch("workout_collector.collect_workout", side_effect=Exception("timeout")):
        result = collect_training_suggestion(_cfg())
    assert result["configured"] is True
    assert "suggestion" not in result
    assert "fallback" not in result
