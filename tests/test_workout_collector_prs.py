import sys
from pathlib import Path

# Add paths so imports resolve both in test env and from project root
_ROOT = Path(__file__).parent.parent
_DEBRIEF = _ROOT / "debrief"
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_DEBRIEF))
sys.path.insert(0, str(_DEBRIEF / "collectors"))

from workout_collector import _format_pr_lines, to_text


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
