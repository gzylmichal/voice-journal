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
    "metrics": {"sleep": "good", "energy": "high", "note": None},
    "query": {"detected": False, "question": None},
}


def _transcripts(text: str):
    return [{"time": "18:00", "text": text}]


# ---------------------------------------------------------------------------
# Happy path: canned combined JSON → all five sub-results correct
# ---------------------------------------------------------------------------

def test_extract_all_parses_all_five_keys():
    with patch("ai_client.call_ai", return_value=json.dumps(_FULL_RESPONSE)):
        result = extract_all(
            _transcripts("Bench press 80 kg. I weighed myself, 82.5 kg. Call dentist. Slept well."),
            _DATE,
        )
    assert result["workout"]["detected"] is True
    assert result["workout"]["workout_name"] == "Push day"
    assert len(result["workout"]["exercises"]) == 1
    assert result["tasks"] == _FULL_RESPONSE["tasks"]
    assert result["events"] == _FULL_RESPONSE["events"]
    assert result["bodyweight"] == {"detected": True, "weight_kg": 82.5}
    assert result["metrics"]["sleep"] == "good"
    assert result["metrics"]["energy"] == "high"


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
    assert result["metrics"] == {"sleep": None, "energy": None, "note": None}


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
    assert result == {
        "workout": {"detected": False, "exercises": []},
        "tasks": [],
        "events": [],
        "bodyweight": {"detected": False},
        "metrics": {"sleep": None, "energy": None, "note": None},
        "query": {"detected": False, "question": None},
    }


def test_extract_all_error_transcripts_only_skips_llm():
    transcripts = [{"time": "18:00", "text": "", "error": "failed"}]
    with patch("ai_client.call_ai") as mock_ai:
        result = extract_all(transcripts, _DATE)
    mock_ai.assert_not_called()
    assert result["workout"]["detected"] is False


# ---------------------------------------------------------------------------
# Phase I: rpe + pain_note pass through extraction unchanged
# ---------------------------------------------------------------------------

_RESPONSE_WITH_RPE = {
    "workout": {
        "detected": True,
        "workout_name": "Push day",
        "exercises": [{
            "name": "Bench press",
            "sets": 3,
            "sets_detail": [{"reps": 8, "weight": "80 kg"}] * 3,
            "is_bodyweight": False,
            "added_weight_kg": None,
            "rpe": 8.0,
            "pain_note": "left shoulder twinge",
        }],
    },
    "tasks": [],
    "events": [],
    "bodyweight": {"detected": False},
}


def test_extract_all_rpe_and_pain_note_pass_through():
    """rpe and pain_note in AI response are preserved in result unchanged."""
    with patch("ai_client.call_ai", return_value=json.dumps(_RESPONSE_WITH_RPE)):
        result = extract_all(_transcripts("Bench press, RPE 8, shoulder twinge"), _DATE)
    ex = result["workout"]["exercises"][0]
    assert ex.get("rpe") == 8.0
    assert ex.get("pain_note") == "left shoulder twinge"


def test_extract_all_null_rpe_pain_preserved():
    """Null rpe/pain_note also pass through without errors."""
    response = dict(_FULL_RESPONSE)
    response["workout"]["exercises"][0]["rpe"] = None
    response["workout"]["exercises"][0]["pain_note"] = None
    with patch("ai_client.call_ai", return_value=json.dumps(response)):
        result = extract_all(
            _transcripts("I weighed myself today 82.5 kg. Also bench press 80 kg."),
            _DATE,
        )
    ex = result["workout"]["exercises"][0]
    assert ex.get("rpe") is None
    assert ex.get("pain_note") is None


def test_extract_all_old_schema_no_rpe_key_ok():
    """Exercise dict without rpe/pain_note keys (old schema) causes no errors."""
    with patch("ai_client.call_ai", return_value=json.dumps(_FULL_RESPONSE)):
        result = extract_all(
            _transcripts("I weighed myself today 82.5 kg. Also bench press 80 kg. Slept well."),
            _DATE,
        )
    ex = result["workout"]["exercises"][0]
    # Old schema: keys simply absent — no KeyError, no crash
    assert "name" in ex
    assert result["workout"]["detected"] is True


# ---------------------------------------------------------------------------
# Phase J: metrics pre-filter + extraction
# ---------------------------------------------------------------------------

_RESPONSE_WITH_METRICS = {
    "workout": {"detected": False, "workout_name": None, "exercises": []},
    "tasks": [],
    "events": [],
    "bodyweight": {"detected": False},
    "metrics": {"sleep": "bad", "energy": "low", "note": "rough night"},
}


def test_metrics_extracted_when_sleep_phrase_present():
    """Sleep phrase in transcript → metrics pass through pre-filter."""
    with patch("ai_client.call_ai", return_value=json.dumps(_RESPONSE_WITH_METRICS)):
        result = extract_all(_transcripts("Słabo spałem dzisiaj, padnięty"), _DATE)
    assert result["metrics"]["sleep"] == "bad"
    assert result["metrics"]["energy"] == "low"


def test_metrics_forced_null_when_no_sleep_phrase():
    """No sleep/energy phrase → metrics forced to all nulls regardless of LLM output."""
    with patch("ai_client.call_ai", return_value=json.dumps(_RESPONSE_WITH_METRICS)):
        result = extract_all(_transcripts("Bench press 80 kg, 3 sets of 8"), _DATE)
    assert result["metrics"]["sleep"] is None
    assert result["metrics"]["energy"] is None
    assert result["metrics"]["note"] is None


def test_metrics_invalid_enum_coerced_to_null():
    """If LLM returns an unexpected enum value, it is coerced to None."""
    bad = dict(_RESPONSE_WITH_METRICS)
    bad["metrics"] = {"sleep": "excellent", "energy": "turbo", "note": None}
    with patch("ai_client.call_ai", return_value=json.dumps(bad)):
        result = extract_all(_transcripts("Slept well today"), _DATE)
    assert result["metrics"]["sleep"] is None
    assert result["metrics"]["energy"] is None


def test_metrics_missing_from_response_defaults_to_null():
    """AI response missing 'metrics' key → safe default all-nulls."""
    no_metrics = {k: v for k, v in _FULL_RESPONSE.items() if k != "metrics"}
    with patch("ai_client.call_ai", return_value=json.dumps(no_metrics)):
        result = extract_all(_transcripts("Slept well. I weigh 82.5 kg."), _DATE)
    assert result["metrics"] == {"sleep": None, "energy": None, "note": None}


def test_metrics_empty_transcripts_returns_null():
    with patch("ai_client.call_ai") as mock_ai:
        result = extract_all([], _DATE)
    mock_ai.assert_not_called()
    assert result["metrics"] == {"sleep": None, "energy": None, "note": None}


# ---------------------------------------------------------------------------
# Phase M: query key — history lookups
# ---------------------------------------------------------------------------

_QUERY_RESPONSE = {
    "workout": {"detected": False, "workout_name": None, "exercises": []},
    "tasks": [],
    "events": [],
    "bodyweight": {"detected": False},
    "metrics": {"sleep": None, "energy": None, "note": None},
    "query": {"detected": True, "question": "What did I squat last time?"},
}


def test_query_detected_passes_through():
    """A query-detected response is returned with query.detected=True and the question text."""
    with patch("ai_client.call_ai", return_value=json.dumps(_QUERY_RESPONSE)):
        result = extract_all(_transcripts("What did I squat last time?"), _DATE)
    assert result["query"]["detected"] is True
    assert result["query"]["question"] == "What did I squat last time?"


def test_query_not_detected_defaults_to_false():
    """Regular memos return query.detected=False."""
    with patch("ai_client.call_ai", return_value=json.dumps(_FULL_RESPONSE)):
        result = extract_all(
            _transcripts("Bench press 80 kg. I weighed myself, 82.5 kg. Slept well."),
            _DATE,
        )
    assert result["query"]["detected"] is False
    assert result["query"]["question"] is None


def test_query_missing_from_response_defaults_to_false():
    """AI response missing 'query' key → safe default detected: false."""
    no_query = {k: v for k, v in _FULL_RESPONSE.items() if k != "query"}
    with patch("ai_client.call_ai", return_value=json.dumps(no_query)):
        result = extract_all(_transcripts("Slept well. I weigh 82.5 kg."), _DATE)
    assert result["query"] == {"detected": False, "question": None}


def test_query_invalid_detected_field_coerced_to_false():
    """If 'detected' is not a bool, query defaults to false."""
    bad = dict(_FULL_RESPONSE)
    bad["query"] = {"detected": "yes", "question": "something"}
    with patch("ai_client.call_ai", return_value=json.dumps(bad)):
        result = extract_all(_transcripts("Slept well. I weigh 82.5 kg."), _DATE)
    assert result["query"]["detected"] is False
