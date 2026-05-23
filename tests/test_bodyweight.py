import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from pipeline.notion_client import (
    store_bodyweight,
    fetch_latest_bodyweight,
    fetch_bodyweight_entries,
)


# ---------------------------------------------------------------------------
# store_bodyweight
# ---------------------------------------------------------------------------

def test_store_bodyweight_success():
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        mock_post.return_value.status_code = 200
        result = store_bodyweight(82.5, date(2026, 5, 20))
        assert result is True
        payload = mock_post.call_args[1]["json"]
        assert payload["parent"]["database_id"] == "db-bw"
        assert payload["properties"]["Date"]["date"]["start"] == "2026-05-20"
        assert payload["properties"]["Weight (kg)"]["number"] == 82.5


def test_store_bodyweight_api_failure():
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "error"
        result = store_bodyweight(82.5, date(2026, 5, 20))
        assert result is False


def test_store_bodyweight_no_config():
    with patch("pipeline.notion_client.NOTION_TOKEN", ""), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", ""):
        result = store_bodyweight(82.5, date(2026, 5, 20))
        assert result is False


# ---------------------------------------------------------------------------
# fetch_latest_bodyweight
# ---------------------------------------------------------------------------

def test_fetch_latest_bodyweight_returns_weight():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{"properties": {"Weight (kg)": {"number": 82.5}}}]
    }
    with patch("pipeline.notion_client.requests.post", return_value=mock_resp), \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        result = fetch_latest_bodyweight(date(2026, 5, 20))
        assert result == 82.5


def test_fetch_latest_bodyweight_empty():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": []}
    with patch("pipeline.notion_client.requests.post", return_value=mock_resp), \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        result = fetch_latest_bodyweight(date(2026, 5, 20))
        assert result is None


# ---------------------------------------------------------------------------
# fetch_bodyweight_entries
# ---------------------------------------------------------------------------

def test_fetch_bodyweight_entries_returns_list():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {"properties": {"Date": {"date": {"start": "2026-05-18"}}, "Weight (kg)": {"number": 83.0}}},
            {"properties": {"Date": {"date": {"start": "2026-05-19"}}, "Weight (kg)": {"number": 82.5}}},
        ]
    }
    with patch("pipeline.notion_client.requests.post", return_value=mock_resp), \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        result = fetch_bodyweight_entries(4)
        assert result == [("2026-05-18", 83.0), ("2026-05-19", 82.5)]


def test_fetch_bodyweight_entries_no_config():
    with patch("pipeline.notion_client.NOTION_TOKEN", ""), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", ""):
        result = fetch_bodyweight_entries(4)
        assert result == []


# ---------------------------------------------------------------------------
# Prompt content checks
# ---------------------------------------------------------------------------

def test_bodyweight_system_prompt_is_defined():
    from pipeline.prompts import BODYWEIGHT_SYSTEM_PROMPT
    assert "weight_kg" in BODYWEIGHT_SYSTEM_PROMPT
    assert "detected" in BODYWEIGHT_SYSTEM_PROMPT
    assert len(BODYWEIGHT_SYSTEM_PROMPT) > 100


def test_workout_prompt_has_bodyweight_fields():
    from pipeline.prompts import WORKOUT_SYSTEM_PROMPT
    assert "is_bodyweight" in WORKOUT_SYSTEM_PROMPT
    assert "added_weight_kg" in WORKOUT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# extract_bodyweight
# ---------------------------------------------------------------------------

def test_extract_bodyweight_detected():
    with patch("ai_client.call_ai", return_value='{"detected": true, "weight_kg": 82.5}'):
        from pipeline.extractors import extract_bodyweight
        transcripts = [{"time": "18:00", "text": "I weigh 82.5 kilos tonight"}]
        result = extract_bodyweight(None, transcripts, date(2026, 5, 20))
        assert result == {"detected": True, "weight_kg": 82.5}


def test_extract_bodyweight_not_detected():
    with patch("ai_client.call_ai", return_value='{"detected": false}'):
        from pipeline.extractors import extract_bodyweight
        transcripts = [{"time": "18:00", "text": "Did chest today, three sets of bench"}]
        result = extract_bodyweight(None, transcripts, date(2026, 5, 20))
        assert result == {"detected": False}


def test_extract_bodyweight_json_parse_failure():
    with patch("ai_client.call_ai", return_value="not json"):
        from pipeline.extractors import extract_bodyweight
        transcripts = [{"time": "18:00", "text": "Whatever"}]
        result = extract_bodyweight(None, transcripts, date(2026, 5, 20))
        assert result == {"detected": False}


def test_extract_bodyweight_empty_transcripts():
    from pipeline.extractors import extract_bodyweight
    result = extract_bodyweight(None, [], date(2026, 5, 20))
    assert result == {"detected": False}


# ---------------------------------------------------------------------------
# create_notion_workout_entries — bodyweight exercise handling
# ---------------------------------------------------------------------------

def _make_workout(is_bodyweight=True, added_weight_kg=None):
    return {
        "detected": True,
        "workout_name": "Pull day",
        "exercises": [{
            "name": "Pull-ups",
            "sets": 3,
            "reps": 8,
            "is_bodyweight": is_bodyweight,
            "added_weight_kg": added_weight_kg,
            "sets_detail": [{"reps": 8, "weight": "bodyweight"}],
        }]
    }


def test_bodyweight_exercise_uses_resolved_weight():
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", "db-wk"):
        mock_post.return_value.status_code = 200
        from pipeline.notion_client import create_notion_workout_entries
        create_notion_workout_entries(_make_workout(), date(2026, 5, 20), resolved_bodyweight=82.0)
        payload = mock_post.call_args[1]["json"]
        assert payload["properties"]["Top Set (kg)"]["number"] == 82.0
        assert payload["properties"]["Weight"]["rich_text"][0]["text"]["content"] == "BW"


def test_bodyweight_exercise_with_added_weight():
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", "db-wk"):
        mock_post.return_value.status_code = 200
        from pipeline.notion_client import create_notion_workout_entries
        create_notion_workout_entries(_make_workout(added_weight_kg=10.0), date(2026, 5, 20), resolved_bodyweight=82.0)
        payload = mock_post.call_args[1]["json"]
        assert payload["properties"]["Top Set (kg)"]["number"] == 92.0
        assert payload["properties"]["Weight"]["rich_text"][0]["text"]["content"] == "BW + 10kg"


def test_bodyweight_exercise_no_resolved_weight_omits_top_set():
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", "db-wk"):
        mock_post.return_value.status_code = 200
        from pipeline.notion_client import create_notion_workout_entries
        create_notion_workout_entries(_make_workout(), date(2026, 5, 20), resolved_bodyweight=None)
        payload = mock_post.call_args[1]["json"]
        assert "Top Set (kg)" not in payload["properties"]
        assert payload["properties"]["Weight"]["rich_text"][0]["text"]["content"] == "BW"


# ---------------------------------------------------------------------------
# append_to_buffer — bodyweight in pending_writes
# ---------------------------------------------------------------------------

def test_append_to_buffer_includes_bodyweight(tmp_path):
    import pipeline.storage as storage_mod
    from unittest.mock import patch as _patch
    with _patch.object(storage_mod, "BUFFER_DIR", tmp_path):
        from pipeline.storage import append_to_buffer
        extracted = {
            "workout": {"detected": False},
            "tasks": [],
            "events": [],
            "bodyweight": {"detected": True, "weight_kg": 82.5},
        }
        append_to_buffer(
            [{"file": "test.m4a", "time": "18:00", "text": "hi"}],
            date(2026, 5, 20),
            extracted=extracted,
        )
        import json
        data = json.loads((tmp_path / "2026-05-20.json").read_text())
        pw = data["pending_writes"][0]
        assert pw["bodyweight"] == {"detected": True, "weight_kg": 82.5}
        assert pw["bodyweight_written_at"] is None


# ---------------------------------------------------------------------------
# _build_weight_svg
# ---------------------------------------------------------------------------

def test_build_weight_svg_returns_empty_for_single_point():
    import sys, importlib
    sys.path.insert(0, ".")
    import weekly_report
    importlib.reload(weekly_report)
    result = weekly_report._build_weight_svg([("2026-05-20", 82.0)])
    assert result == ""


def test_build_weight_svg_returns_svg_for_multiple_points():
    import sys, importlib
    sys.path.insert(0, ".")
    import weekly_report
    importlib.reload(weekly_report)
    entries = [("2026-05-18", 83.0), ("2026-05-19", 82.5), ("2026-05-20", 82.0)]
    result = weekly_report._build_weight_svg(entries)
    assert "<svg" in result
    assert "polyline" in result
    assert "82.0 kg" in result
    assert "▼" in result  # losing weight


# ---------------------------------------------------------------------------
# _build_muscle_pie_svg
# ---------------------------------------------------------------------------

def test_build_muscle_pie_svg_empty_input():
    import sys, importlib
    sys.path.insert(0, ".")
    import weekly_report
    importlib.reload(weekly_report)
    assert weekly_report._build_muscle_pie_svg({}) == ""


def test_build_muscle_pie_svg_returns_svg():
    import sys, importlib
    sys.path.insert(0, ".")
    import weekly_report
    importlib.reload(weekly_report)
    sets = {"Chest": 12, "Back": 10, "Legs": 8, "Shoulders": 6}
    result = weekly_report._build_muscle_pie_svg(sets)
    assert "<svg" in result
    assert "Chest" in result
    assert "33%" in result or "34%" in result  # 12/36 ≈ 33%
    assert "Last 7 Days" in result
