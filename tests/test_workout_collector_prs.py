import sys
from pathlib import Path

# Add paths so imports resolve both in test env and from project root
_ROOT = Path(__file__).parent.parent
_DEBRIEF = _ROOT / "debrief"
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_DEBRIEF))
sys.path.insert(0, str(_DEBRIEF / "collectors"))

from workout_collector import _format_pr_lines, _merge_by_exercise, _format_for_ai, to_text


def test_pr_line_weight_pr_renders():
    result = _format_pr_lines({
        "Bench Press": [
            {
                "kind": "weight",
                "date": "2026-06-14",
                "weight_kg": 92.5,
                "reps": 1,
                "prev_best_kg": 90.0,
            }
        ]
    })
    assert "🏆" in result
    assert "Bench Press" in result
    assert "92.5" in result


def test_pr_line_rep_pr_renders():
    result = _format_pr_lines({
        "Deadlift": [
            {
                "kind": "reps",
                "date": "2026-06-14",
                "weight_kg": 140.0,
                "reps": 5,
                "prev_best_reps": 3,
            }
        ]
    })
    assert "🏆" in result
    assert "Deadlift" in result
    assert "140.0" in result
    assert "5" in result


def test_no_pr_line_when_empty():
    result = _format_pr_lines({})
    assert result == ""


def test_to_text_includes_pr_from_formatted_text():
    data = {
        "configured": True,
        "entries": [
            {
                "exercise": "Bench Press",
                "date": "2026-06-14",
                "session": "Chest",
                "sets": 3,
                "reps": 5,
                "weight": "90x5",
                "top_set_kg": 90.0,
                "muscle_group": "Chest",
            }
        ],
        "date": "2026-06-14",
        "session": "Chest",
        "formatted_text": "🏆 PR: Bench Press 90.0 kg (prev: 87.5 kg)\n\nSessions this week: 1",
    }
    assert "🏆" in to_text(data)


def test_to_text_no_pr_when_absent():
    data = {
        "configured": True,
        "entries": [
            {
                "exercise": "Squat",
                "date": "2026-06-14",
                "session": "Legs",
                "sets": 4,
                "reps": 5,
                "weight": "100x5",
                "top_set_kg": 100.0,
                "muscle_group": "Legs",
            }
        ],
        "date": "2026-06-14",
        "session": "Legs",
        "formatted_text": "Sessions this week: 1\n\n  - Squat [Legs]: 4×5 @ 100x5",
    }
    assert "🏆" not in to_text(data)


# ---------------------------------------------------------------------------
# _merge_by_exercise — Step 1 bugfix
# ---------------------------------------------------------------------------

def _entry(exercise, weight, top_set_kg, sets=3, reps=5,
           date="2026-06-14", session="Chest", muscle_group="Chest"):
    return {
        "exercise": exercise, "date": date, "session": session,
        "muscle_group": muscle_group, "sets": sets, "reps": reps,
        "weight": weight, "top_set_kg": top_set_kg,
    }


def test_merge_same_exercise_collapses_to_one():
    """Multiple rows with same name (case-insensitive) merge into a single entry."""
    entries = [
        _entry("Bench Press", "60x10", 60.0, sets=1),
        _entry("bench press", "70x5, 70x5, 70x5", 70.0, sets=3),
        _entry("Bench Press", "60x10", 60.0, sets=1),
    ]
    merged = _merge_by_exercise(entries)
    assert len(merged) == 1
    assert merged[0]["exercise"] == "Bench Press"
    assert merged[0]["sets"] == 5
    assert "60x10" in merged[0]["weight"]
    assert "70x5" in merged[0]["weight"]


def test_merge_top_set_is_max():
    """top_set_kg in merged entry is the max across the group."""
    entries = [
        _entry("Bench Press", "60x10", 60.0),
        _entry("bench press", "70x5", 70.0),
        _entry("BENCH PRESS", "65x8", 65.0),
    ]
    merged = _merge_by_exercise(entries)
    assert len(merged) == 1
    assert merged[0]["top_set_kg"] == 70.0


def test_merge_distinct_exercises_stay_separate():
    """Different exercises are not merged together."""
    entries = [
        _entry("Bench Press", "70x5", 70.0),
        _entry("Cable fly", "30x12", 30.0, muscle_group="Chest"),
        _entry("Triceps pushdown", "25x12", 25.0, muscle_group="Triceps"),
    ]
    merged = _merge_by_exercise(entries)
    assert len(merged) == 3


def test_format_for_ai_merges_same_exercise_into_one_line():
    """_format_for_ai renders each exercise name only once per day."""
    entries = [
        _entry("Bench Press", "60x10", 60.0, sets=1),
        _entry("Bench Press", "70x5, 70x5", 70.0, sets=2),
        _entry("Cable fly", "30x12", 30.0, sets=3, muscle_group="Chest"),
    ]
    text = _format_for_ai(entries)
    assert text.count("Bench Press") == 1
    assert text.count("Cable fly") == 1
    assert "70" in text  # top set from merged rows
