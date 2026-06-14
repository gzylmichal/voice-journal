"""Tests for Phase J Step 4: sleep/workout correlation and sleep/energy summary."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, timedelta

import pytest


def _date(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _metrics(d: str, sleep: str, energy: str = None) -> dict:
    return {"date": d, "sleep": sleep, "energy": energy, "note": None}


def _workout(d: str, top_kg: float) -> dict:
    return {"date": d, "exercise": "Bench Press", "top_set_kg": top_kg, "sets": 3}


# Import helpers under test
from weekly_report import compute_sleep_workout_correlation, build_sleep_energy_summary


# ---------------------------------------------------------------------------
# Correlation — not enough data → no line
# ---------------------------------------------------------------------------

def test_correlation_empty_metrics_returns_empty():
    result = compute_sleep_workout_correlation([], [_workout(_date(1), 80.0)])
    assert result == ""


def test_correlation_empty_workouts_returns_empty():
    result = compute_sleep_workout_correlation([_metrics(_date(1), "bad")], [])
    assert result == ""


def test_correlation_fewer_than_3_bad_sleep_workout_days_returns_empty():
    """Only 2 bad-sleep days with workouts — below threshold, no line."""
    metrics = [_metrics(_date(3), "bad"), _metrics(_date(2), "bad")]
    workouts = [_workout(_date(3), 80.0), _workout(_date(2), 75.0)]
    result = compute_sleep_workout_correlation(metrics, workouts)
    assert result == ""


def test_correlation_no_bad_sleep_days_returns_empty():
    metrics = [_metrics(_date(d), "good") for d in range(1, 8)]
    workouts = [_workout(_date(d), 80.0) for d in range(1, 8)]
    result = compute_sleep_workout_correlation(metrics, workouts)
    assert result == ""


# ---------------------------------------------------------------------------
# Correlation — ≥3 bad-sleep workout days → line produced
# ---------------------------------------------------------------------------

def test_correlation_three_bad_sleep_days_produces_line():
    metrics = [_metrics(_date(d), "bad") for d in [3, 5, 7]]
    workouts = [_workout(_date(d), 60.0) for d in [3, 5, 7]]
    # Add some good-day workouts at higher weight to create a negative delta
    workouts += [_workout(_date(d), 90.0) for d in [1, 2, 4]]
    result = compute_sleep_workout_correlation(metrics, workouts)
    assert result != ""
    assert "bad-sleep" in result
    assert "%" in result


def test_correlation_bad_sleep_equal_to_average_shows_zero_pct():
    """If bad-sleep days perform same as average, show +0% or 0%."""
    # 3 bad-sleep days and 3 good-sleep days, all at 80 kg top set
    metrics = (
        [_metrics(_date(d), "bad") for d in [2, 4, 6]] +
        [_metrics(_date(d), "good") for d in [1, 3, 5]]
    )
    workouts = [_workout(_date(d), 80.0) for d in [1, 2, 3, 4, 5, 6]]
    result = compute_sleep_workout_correlation(metrics, workouts)
    assert result != ""
    assert "0%" in result


def test_correlation_negative_pct_is_shown():
    """Bad-sleep days have lower average top set → negative %."""
    metrics = [_metrics(_date(d), "bad") for d in [3, 5, 7]]
    workouts = (
        [_workout(_date(d), 50.0) for d in [3, 5, 7]] +   # bad-sleep: 50 kg
        [_workout(_date(d), 100.0) for d in [1, 2, 4]]     # other days: 100 kg
    )
    result = compute_sleep_workout_correlation(metrics, workouts)
    assert "-" in result


# ---------------------------------------------------------------------------
# Sleep/energy summary
# ---------------------------------------------------------------------------

def test_sleep_energy_summary_empty_metrics():
    assert build_sleep_energy_summary([], 4) == ""


def test_sleep_energy_summary_counts_correctly():
    metrics = [
        _metrics(_date(1), "bad", "low"),
        _metrics(_date(2), "bad", "normal"),
        _metrics(_date(3), "good", "high"),
    ]
    result = build_sleep_energy_summary(metrics, 4)
    assert "Sleep" in result
    assert "bad 2d" in result
    assert "good 1d" in result
    assert "Energy" in result
    assert "low 1d" in result


def test_sleep_energy_summary_degrades_gracefully_no_energy():
    metrics = [_metrics(_date(1), "ok"), _metrics(_date(2), "bad")]
    result = build_sleep_energy_summary(metrics, 4)
    assert "Sleep" in result
    # When no energy data, "Energy:" count line should not appear
    assert "Energy:" not in result
