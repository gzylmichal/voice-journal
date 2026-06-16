"""Tests for Phase N2: collect_session_plan, render_session_plan_text,
render_session_plan (HTML), and send_session_plan push.
"""
import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import pytest

# Make debrief/ importable
DEBRIEF_DIR = Path(__file__).parent.parent / "debrief"
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(DEBRIEF_DIR))
sys.path.insert(0, str(DEBRIEF_DIR / "collectors"))
sys.path.insert(0, str(PROJECT_ROOT))

from workout_collector import (
    collect_session_plan,
    render_session_plan_text,
    _format_plan_line,
    _format_slot_with_rec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = date.today()

_CHEST_TEMPLATE = [
    {"slot": "Bench press", "type": "main",
     "match": ["bench", "bench press"]},
    {"slot": "Pull-ups",    "type": "main",
     "match": ["pull-up", "pullup"]},
    {"slot": "Triceps",     "type": "accessory", "muscle": "Triceps",
     "match": ["tricep", "pushdown"]},
    {"slot": "Biceps",      "type": "accessory", "muscle": "Biceps",
     "match": ["bicep", "curl"]},
]

_PLAN_CFG = {
    "cycle": ["Chest", "Deadlift", "Squat"],
    "templates": {"Chest": _CHEST_TEMPLATE},
}


def _cfg():
    return {"notion_api_key": "key", "notion_workout_db_id": "db"}


def _wo(exercise, days_ago, weight, reps=5, session="Squat"):
    # session="Squat" means next_split returns "Chest" (our only template)
    return {
        "exercise": exercise,
        "date": (_TODAY - timedelta(days=days_ago)).isoformat(),
        "weight": weight,
        "reps": reps,
        "sets": 3,
        "session": session,
        "top_set_kg": None,
        "muscle_group": "",
    }


def _history_result(entries):
    return {
        "configured": True,
        "entries": entries,
        "sessions": 1,
        "session_dates": [],
        "session_types": {},
    }


def _plan_from_history(entries):
    """Helper: collect_session_plan with canned history + plan config."""
    with patch("workout_collector.collect_workout", return_value=_history_result(entries)), \
         patch("workout_collector._load_plan_config_fn", return_value=lambda: _PLAN_CFG), \
         patch("workout_collector._load_analytics") as mock_analytics:
        from analytics import build_session_plan, next_split
        mock_analytics.return_value = (build_session_plan, next_split)
        return collect_session_plan(_cfg())


# ---------------------------------------------------------------------------
# collect_session_plan
# ---------------------------------------------------------------------------

def test_not_configured_returns_false():
    result = collect_session_plan({"notion_api_key": "", "notion_workout_db_id": ""})
    assert result["configured"] is False


def test_no_plan_config_returns_plan_unavailable():
    with patch("workout_collector.collect_workout", return_value=_history_result([])), \
         patch("workout_collector._load_plan_config_fn", return_value=lambda: None), \
         patch("workout_collector._load_analytics") as mock_analytics:
        from analytics import build_session_plan, next_split
        mock_analytics.return_value = (build_session_plan, next_split)
        result = collect_session_plan(_cfg())
    assert result["configured"] is True
    assert result.get("plan_available") is False


def test_plan_built_from_history():
    entries = [
        _wo("Bench Press", 14, "70x5, 70x5, 70x5"),
        _wo("Bench Press",  7, "70x5, 70x5, 70x5"),
    ]
    result = _plan_from_history(entries)
    assert result["configured"] is True
    assert result.get("plan_available") is True
    assert result.get("split") == "Chest"
    plan = result.get("plan", [])
    assert any(s["slot"] == "Bench press" for s in plan)


def test_variation_swap_picks_latest():
    entries = [
        _wo("Bench Press",             14, "70x5, 70x5"),
        _wo("Bench Press",              7, "70x5, 70x5"),
        _wo("Smith Machine Bench",      3, "65x8, 65x8"),
        _wo("Smith Machine Bench",      1, "65x8, 65x8"),
    ]
    result = _plan_from_history(entries)
    bench = next(s for s in result["plan"] if s["slot"] == "Bench press")
    assert bench.get("exercise") == "Smith Machine Bench"


def test_too_few_sessions_main_no_rec():
    entries = [_wo("Bench Press", 5, "70x5, 70x5")]
    result = _plan_from_history(entries)
    bench = next(s for s in result["plan"] if s["slot"] == "Bench press")
    assert bench.get("suggestion") is None
    assert "rec" not in bench
    assert bench.get("last_sets_str") == "70x5, 70x5"


def test_accessory_with_history_in_plan():
    entries = [
        _wo("Triceps Pushdown", 14, "30x12, 30x12"),
        _wo("Triceps Pushdown",  7, "30x12, 30x12"),
    ]
    result = _plan_from_history(entries)
    tri = next(s for s in result["plan"] if s["slot"] == "Triceps")
    assert "rec" in tri


def test_accessory_no_history_reminder():
    result = _plan_from_history([])
    tri = next(s for s in result["plan"] if s["slot"] == "Triceps")
    assert tri.get("reminder") is True


def test_empty_history_still_returns_plan():
    result = _plan_from_history([])
    assert result.get("plan_available") is True
    assert len(result["plan"]) == len(_CHEST_TEMPLATE)


def test_history_fetch_error_degrades():
    with patch("workout_collector.collect_workout", side_effect=Exception("timeout")), \
         patch("workout_collector._load_plan_config_fn", return_value=lambda: _PLAN_CFG), \
         patch("workout_collector._load_analytics") as mock_analytics:
        from analytics import build_session_plan, next_split
        mock_analytics.return_value = (build_session_plan, next_split)
        result = collect_session_plan(_cfg())
    assert result.get("plan_available") is False


# ---------------------------------------------------------------------------
# render_session_plan_text / _format_plan_line
# ---------------------------------------------------------------------------

def test_render_text_omitted_when_no_plan():
    assert render_session_plan_text(None) == ""
    assert render_session_plan_text({}) == ""
    assert render_session_plan_text({"plan_available": False}) == ""


def test_render_text_main_with_rec():
    plan = [
        {
            "slot": "Bench press", "type": "main", "exercise": "Bench Press",
            "rec": {"action": "progress", "weight_kg": 72.5, "target_reps": 5,
                    "note": None, "last_sets_str": "70x5, 70x5"},
            "last_sets_str": "70x5, 70x5",
        },
        {"slot": "Triceps", "type": "accessory", "reminder": True},
    ]
    text = _format_plan_line("Chest", plan)
    assert text.startswith("Chest day →")
    assert "Bench Press" in text
    assert "72.5×5" in text
    assert "last 70x5, 70x5" in text
    assert "Triceps" in text


def test_render_text_last_only_no_rec():
    plan = [
        {
            "slot": "Bench press", "type": "main", "exercise": "Bench Press",
            "suggestion": None, "last_sets_str": "70x5, 70x5",
        },
    ]
    text = _format_plan_line("Chest", plan)
    assert "Bench Press" in text
    assert "last 70x5, 70x5" in text


def test_render_text_multiple_reminders_joined():
    plan = [
        {"slot": "Triceps", "type": "accessory", "reminder": True},
        {"slot": "Biceps",  "type": "accessory", "reminder": True},
    ]
    text = _format_plan_line("Chest", plan)
    assert "Triceps + Biceps" in text


def test_render_text_bw_exercise():
    plan = [
        {
            "slot": "Pull-ups", "type": "main", "exercise": "Pull-ups",
            "rec": {"action": "progress", "weight_kg": None, "target_reps": 9,
                    "note": None, "last_sets_str": "BW×8, BW×8"},
            "last_sets_str": "BW×8, BW×8",
        },
    ]
    text = _format_plan_line("Chest", plan)
    assert "BW×9" in text


# ---------------------------------------------------------------------------
# render_session_plan HTML (formatter)
# ---------------------------------------------------------------------------

def test_html_renders_when_plan_available():
    from formatter import render_session_plan
    data = {
        "configured": True,
        "plan_available": True,
        "split": "Chest",
        "plan": [
            {
                "slot": "Bench press", "type": "main", "exercise": "Bench Press",
                "rec": {"action": "progress", "weight_kg": 72.5, "target_reps": 5,
                        "note": None, "last_sets_str": "70x5"},
                "last_sets_str": "70x5",
            },
            {"slot": "Triceps", "type": "accessory", "reminder": True},
        ],
    }
    html = render_session_plan(data)
    assert "Today" in html and "session" in html
    assert "Chest day" in html
    assert "Bench Press" in html


def test_html_omits_when_plan_unavailable_and_no_fallback():
    from formatter import render_session_plan
    result = render_session_plan({"configured": True, "plan_available": False})
    assert result == ""


def test_html_falls_back_to_training_suggestion_when_no_plan():
    from formatter import render_session_plan
    fallback = {"configured": True, "suggestion": "Deadlift", "last_date": "Jun 14"}
    html = render_session_plan(None, fallback_suggestion=fallback)
    assert "Training suggestion" in html
    assert "Deadlift" in html


def test_html_plan_supersedes_training_suggestion():
    from formatter import render_session_plan
    data = {
        "configured": True,
        "plan_available": True,
        "split": "Deadlift",
        "plan": [
            {
                "slot": "Deadlift", "type": "main", "exercise": "Deadlift",
                "rec": {"action": "progress", "weight_kg": 120.0, "target_reps": 5,
                        "note": None, "last_sets_str": "115x5"},
                "last_sets_str": "115x5",
            },
        ],
    }
    fallback = {"configured": True, "suggestion": "SomethingElse", "last_date": ""}
    html = render_session_plan(data, fallback_suggestion=fallback)
    assert "Today" in html and "session" in html
    assert "SomethingElse" not in html
