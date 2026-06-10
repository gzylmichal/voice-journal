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


# ---------------------------------------------------------------------------
# A1: keyword pre-filter — LLM must not be called on workout-only transcripts
# ---------------------------------------------------------------------------

def test_pre_filter_workout_only_skips_llm():
    """Workout memo with no weigh-in phrase → no AI call."""
    with patch("ai_client.call_ai") as mock_ai:
        from pipeline.extractors import extract_bodyweight
        transcripts = [{"time": "18:00", "text": "Bench press 80 kg 8 reps, 3 sets"}]
        result = extract_bodyweight(None, transcripts, date(2026, 5, 20))
        assert result == {"detected": False}
        mock_ai.assert_not_called()


def test_pre_filter_weigh_in_phrase_calls_llm():
    """Transcript with 'i weigh' → LLM IS called."""
    with patch("ai_client.call_ai", return_value='{"detected": true, "weight_kg": 82.0}') as mock_ai:
        from pipeline.extractors import extract_bodyweight
        transcripts = [{"time": "18:00", "text": "I weigh 82 kilos today"}]
        result = extract_bodyweight(None, transcripts, date(2026, 5, 20))
        assert result == {"detected": True, "weight_kg": 82.0}
        mock_ai.assert_called_once()


def test_pre_filter_polish_phrase_calls_llm():
    """Polish weigh-in phrase → LLM IS called."""
    with patch("ai_client.call_ai", return_value='{"detected": true, "weight_kg": 84.0}') as mock_ai:
        from pipeline.extractors import extract_bodyweight
        transcripts = [{"time": "07:00", "text": "Zważyłem się rano, 84 kilo"}]
        result = extract_bodyweight(None, transcripts, date(2026, 5, 20))
        assert result["detected"] is True
        mock_ai.assert_called_once()


def test_pre_filter_polish_workout_skips_llm():
    """Polish workout memo without any weigh-in phrase → no AI call."""
    with patch("ai_client.call_ai") as mock_ai:
        from pipeline.extractors import extract_bodyweight
        transcripts = [{"time": "18:00", "text": "Wyciskanie 80 kilo, 8 powtórzeń, 3 serie"}]
        result = extract_bodyweight(None, transcripts, date(2026, 5, 20))
        assert result == {"detected": False}
        mock_ai.assert_not_called()


# ---------------------------------------------------------------------------
# A3: validate_bodyweight
# ---------------------------------------------------------------------------

def test_validate_bodyweight_accepts_small_delta():
    """80 → 81 kg (1.25% delta) — should be accepted."""
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "results": [{"properties": {"Weight (kg)": {"number": 80.0}}}]
        }
        from pipeline.extractors import validate_bodyweight
        assert validate_bodyweight(81.0, date(2026, 5, 20)) is True


def test_validate_bodyweight_rejects_large_delta():
    """80 → 95 kg (18.75% delta) — should be rejected."""
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "results": [{"properties": {"Weight (kg)": {"number": 80.0}}}]
        }
        from pipeline.extractors import validate_bodyweight
        assert validate_bodyweight(95.0, date(2026, 5, 20)) is False


def test_validate_bodyweight_rejects_out_of_range():
    """300 kg is outside hard range — rejected regardless of history."""
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"results": []}
        from pipeline.extractors import validate_bodyweight
        assert validate_bodyweight(300.0, date(2026, 5, 20)) is False


def test_validate_bodyweight_no_history_accepts_within_range():
    """No previous weight in DB — accept any value within 40–250 kg."""
    with patch("pipeline.notion_client.requests.post") as mock_post, \
         patch("pipeline.notion_client.NOTION_TOKEN", "tok"), \
         patch("pipeline.notion_client.NOTION_BODYWEIGHT_DB_ID", "db-bw"):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"results": []}
        from pipeline.extractors import validate_bodyweight
        assert validate_bodyweight(82.0, date(2026, 5, 20)) is True


# ---------------------------------------------------------------------------
# A2: Prompt content — negative-rule keywords must be present
# ---------------------------------------------------------------------------

def test_bodyweight_prompt_has_negative_rules():
    from pipeline.prompts import BODYWEIGHT_SYSTEM_PROMPT
    prompt_lower = BODYWEIGHT_SYSTEM_PROMPT.lower()
    assert "exercise" in prompt_lower or "workout" in prompt_lower
    assert "never" in prompt_lower or "not" in prompt_lower
    assert "ważę" in prompt_lower or "zważyłem" in prompt_lower


def test_bodyweight_prompt_has_polish_examples():
    from pipeline.prompts import BODYWEIGHT_SYSTEM_PROMPT
    assert "ważę" in BODYWEIGHT_SYSTEM_PROMPT.lower() or "zważył" in BODYWEIGHT_SYSTEM_PROMPT.lower()
