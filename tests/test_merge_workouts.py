import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.extractors import merge_buffered_workouts


def _entry(workout: dict) -> dict:
    return {
        "batch_id": "test",
        "workout": workout,
        "tasks": [],
        "events": [],
        "bodyweight": {"detected": False},
        "workout_written_at": None,
        "tasks_written_at": None,
        "events_written_at": None,
        "bodyweight_written_at": None,
    }


# ---------------------------------------------------------------------------
# Empty / no-workout cases
# ---------------------------------------------------------------------------

def test_empty_list_returns_not_detected():
    assert merge_buffered_workouts([]) == {"detected": False}


def test_none_returns_not_detected():
    assert merge_buffered_workouts(None) == {"detected": False}


def test_all_not_detected_returns_not_detected():
    entries = [
        _entry({"detected": False}),
        _entry({"detected": False}),
    ]
    assert merge_buffered_workouts(entries) == {"detected": False}


def test_missing_workout_key_returns_not_detected():
    entries = [{"batch_id": "x", "tasks": [], "events": []}]
    assert merge_buffered_workouts(entries) == {"detected": False}


# ---------------------------------------------------------------------------
# Same exercise in two batches → sets combined in order
# ---------------------------------------------------------------------------

def test_same_exercise_two_batches_merges_sets():
    batch1 = _entry({
        "detected": True,
        "workout_name": "Push day",
        "exercises": [{
            "name": "Bench press",
            "sets": 2,
            "sets_detail": [
                {"weight": "80 kg", "reps": 8},
                {"weight": "80 kg", "reps": 8},
            ],
            "weight": "80 kg",
        }],
    })
    batch2 = _entry({
        "detected": True,
        "workout_name": "Push day",
        "exercises": [{
            "name": "Bench press",
            "sets": 1,
            "sets_detail": [
                {"weight": "85 kg", "reps": 5},
            ],
            "weight": "85 kg",
        }],
    })
    result = merge_buffered_workouts([batch1, batch2])
    assert result["detected"] is True
    assert result["workout_name"] == "Push day"
    assert len(result["exercises"]) == 1
    ex = result["exercises"][0]
    assert ex["name"] == "Bench press"
    assert ex["sets"] == 3
    assert len(ex["sets_detail"]) == 3
    assert ex["sets_detail"][0] == {"weight": "80 kg", "reps": 8}
    assert ex["sets_detail"][2] == {"weight": "85 kg", "reps": 5}


# ---------------------------------------------------------------------------
# Two different exercises → both present, order preserved
# ---------------------------------------------------------------------------

def test_different_exercises_both_present():
    batch1 = _entry({
        "detected": True,
        "workout_name": "Push day",
        "exercises": [{
            "name": "Bench press",
            "sets": 3,
            "sets_detail": [{"weight": "80 kg", "reps": 8}] * 3,
            "weight": "80 kg",
        }],
    })
    batch2 = _entry({
        "detected": True,
        "workout_name": "Push day",
        "exercises": [{
            "name": "Overhead press",
            "sets": 3,
            "sets_detail": [{"weight": "60 kg", "reps": 6}] * 3,
            "weight": "60 kg",
        }],
    })
    result = merge_buffered_workouts([batch1, batch2])
    assert result["detected"] is True
    names = [ex["name"] for ex in result["exercises"]]
    assert names == ["Bench press", "Overhead press"]
    assert result["exercises"][0]["sets"] == 3
    assert result["exercises"][1]["sets"] == 3


# ---------------------------------------------------------------------------
# Mix: one detected, one not → uses the detected one
# ---------------------------------------------------------------------------

def test_one_detected_one_not():
    entries = [
        _entry({"detected": False}),
        _entry({
            "detected": True,
            "workout_name": "Leg day",
            "exercises": [{
                "name": "Squat",
                "sets": 4,
                "sets_detail": [{"weight": "100 kg", "reps": 5}] * 4,
                "weight": "100 kg",
            }],
        }),
    ]
    result = merge_buffered_workouts(entries)
    assert result["detected"] is True
    assert result["workout_name"] == "Leg day"
    assert len(result["exercises"]) == 1


# ---------------------------------------------------------------------------
# Case-insensitive exercise name dedup
# ---------------------------------------------------------------------------

def test_case_insensitive_exercise_merge():
    batch1 = _entry({
        "detected": True,
        "workout_name": "Push",
        "exercises": [{"name": "Bench Press", "sets": 2,
                       "sets_detail": [{"weight": "80 kg", "reps": 8}] * 2}],
    })
    batch2 = _entry({
        "detected": True,
        "workout_name": "Push",
        "exercises": [{"name": "bench press", "sets": 1,
                       "sets_detail": [{"weight": "85 kg", "reps": 5}]}],
    })
    result = merge_buffered_workouts([batch1, batch2])
    assert len(result["exercises"]) == 1
    assert result["exercises"][0]["sets"] == 3


# ---------------------------------------------------------------------------
# No sets_detail (legacy flat schema) → falls back to sets count
# ---------------------------------------------------------------------------

def test_legacy_no_sets_detail():
    entry = _entry({
        "detected": True,
        "workout_name": "Push day",
        "exercises": [{"name": "Bench press", "sets": 3, "weight": "80 kg"}],
    })
    result = merge_buffered_workouts([entry])
    assert result["detected"] is True
    ex = result["exercises"][0]
    assert ex["sets"] == 3
    assert ex["sets_detail"] == []
