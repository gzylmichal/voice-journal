import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import date
from unittest.mock import patch

import pytest

from pipeline.extractors import extract_all


_DATE = date(2026, 5, 20)

_FULL_RESPONSE = {
    "workout": {
        "detected": True,
        "workout_name": "Push day",
        "exercises": [{
            "name": "Bench press",
            "sets": 3,
            "sets_detail": [{"reps": 8, "weight": "80 kg"}] * 3,
            "is_bodyweight": False,
            "added_weight_kg": None,
        }],
    },
    "tasks": [{"title": "Call dentist", "description": None, "due_date": None, "priority": "Normal", "type": "Personal"}],
    "events": [{"title": "Doctor", "date": "2026-05-21", "time": "10:00", "duration_minutes": None, "notes": None}],
    "bodyweight": {"detected": True, "weight_kg": 82.5},
}


def _transcripts(text: str):
    return [{"time": "18:00", "text": text}]


# ---------------------------------------------------------------------------
# Happy path: canned combined JSON → all four sub-results correct
# ---------------------------------------------------------------------------

def test_extract_all_parses_all_four_keys():
    with patch("ai_client.call_ai", return_value=json.dumps(_FULL_RESPONSE)):
        result = extract_all(
            _transcripts("Bench press 80 kg. I weighed myself, 82.5 kg. Call dentist."),
            _DATE,
        )
    assert result["workout"]["detected"] is True
    assert result["workout"]["workout_name"] == "Push day"
    assert len(result["workout"]["exercises"]) == 1
    assert result["tasks"] == _FULL_RESPONSE["tasks"]
    assert result["events"] == _FULL_RESPONSE["events"]
    assert result["bodyweight"] == {"detected": True, "weight_kg": 82.5}


def test_extract_all_returns_with_json_fences():
    fenced = "```json\n" + json.dumps(_FULL_RESPONSE) + "\n```"
    with patch("ai_client.call_ai", return_value=fenced):
        result = extract_all(_transcripts("I weigh 82.5 kg"), _DATE)
    assert result["bodyweight"]["detected"] is True


# ---------------------------------------------------------------------------
# Malformed JSON → safe empty defaults per category
# ---------------------------------------------------------------------------

def test_extract_all_malformed_json_returns_empty_defaults():
    with patch("ai_client.call_ai", return_value="not valid json at all"):
        result = extract_all(_transcripts("some text"), _DATE)
    assert result["workout"] == {"detected": False, "exercises": []}
    assert result["tasks"] == []
    assert result["events"] == []
    assert result["bodyweight"] == {"detected": False}


def test_extract_all_non_dict_response_returns_empty_defaults():
    with patch("ai_client.call_ai", return_value="[]"):
        result = extract_all(_transcripts("some text"), _DATE)
    assert result["workout"]["detected"] is False
    assert result["tasks"] == []


def test_extract_all_partial_keys_returns_safe_defaults():
    """A response missing some keys should fill missing ones with safe defaults."""
    partial = json.dumps({"workout": {"detected": False, "exercises": []}, "tasks": []})
    with patch("ai_client.call_ai", return_value=partial):
        result = extract_all(_transcripts("some text"), _DATE)
    assert result["events"] == []
    assert result["bodyweight"] == {"detected": False}


def test_extract_all_tasks_not_list_coerced_to_empty():
    bad = json.dumps({"workout": {"detected": False}, "tasks": "oops", "events": [], "bodyweight": {"detected": False}})
    with patch("ai_client.call_ai", return_value=bad):
        result = extract_all(_transcripts("some text"), _DATE)
    assert result["tasks"] == []


# ---------------------------------------------------------------------------
# A1 bodyweight pre-filter — forced off when no weigh-in phrase
# ---------------------------------------------------------------------------

def test_extract_all_no_weigh_in_phrase_forces_bodyweight_undetected():
    """Model returns bodyweight detected, but transcript has no weigh-in phrase → forced off."""
    response = dict(_FULL_RESPONSE)
    # bodyweight claims detected even though transcript is workout-only
    with patch("ai_client.call_ai", return_value=json.dumps(response)):
        result = extract_all(
            _transcripts("Bench press 80 kg 8 reps, 3 sets"),
            _DATE,
        )
    assert result["bodyweight"] == {"detected": False}
    # workout is NOT affected
    assert result["workout"]["detected"] is True


def test_extract_all_weigh_in_phrase_present_keeps_bodyweight():
    """Transcript contains weigh-in phrase → bodyweight result is kept as-is."""
    with patch("ai_client.call_ai", return_value=json.dumps(_FULL_RESPONSE)):
        result = extract_all(
            _transcripts("I weighed myself today 82.5 kg. Also bench press 80 kg."),
            _DATE,
        )
    assert result["bodyweight"]["detected"] is True
    assert result["bodyweight"]["weight_kg"] == 82.5


# ---------------------------------------------------------------------------
# Empty transcripts → no LLM call, empty defaults
# ---------------------------------------------------------------------------

def test_extract_all_empty_transcripts_skips_llm():
    with patch("ai_client.call_ai") as mock_ai:
        result = extract_all([], _DATE)
    mock_ai.assert_not_called()
    assert result == {"workout": {"detected": False, "exercises": []}, "tasks": [], "events": [], "bodyweight": {"detected": False}}


def test_extract_all_error_transcripts_only_skips_llm():
    transcripts = [{"time": "18:00", "text": "", "error": "failed"}]
    with patch("ai_client.call_ai") as mock_ai:
        result = extract_all(transcripts, _DATE)
    mock_ai.assert_not_called()
    assert result["workout"]["detected"] is False
