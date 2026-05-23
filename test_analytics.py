#!/usr/bin/env python3
"""
test_analytics.py — Unit tests for analytics.py
Run: pytest test_analytics.py -v
"""

import pytest
from analytics import (
    parse_sets_string,
    epley_1rm,
    linear_slope,
    identify_benchmark,
    compute_metrics,
)
from weekly_report import format_metrics_for_llm


def _make_entry(exercise, date, muscle_group, sets, reps, weight, top_set_kg):
    """Build a parsed workout entry dict matching parse_entry() output."""
    return {
        "exercise": exercise,
        "date": date,
        "session": "",
        "muscle_group": muscle_group,
        "sets": sets,
        "reps": reps,
        "weight": weight,
        "top_set_kg": top_set_kg,
    }


# ---------------------------------------------------------------------------
# parse_sets_string
# ---------------------------------------------------------------------------

def test_parse_sets_standard():
    assert parse_sets_string("80x5, 85x3, 90x1, 80x3, 70x5") == [
        (80.0, 5), (85.0, 3), (90.0, 1), (80.0, 3), (70.0, 5)
    ]

def test_parse_sets_single():
    assert parse_sets_string("100x1") == [(100.0, 1)]

def test_parse_sets_bodyweight_with_reps():
    assert parse_sets_string("bodyweightx8") == [(0.0, 8)]

def test_parse_sets_bodyweight_alone():
    assert parse_sets_string("bodyweight") == [(0.0, 0)]

def test_parse_sets_bw_alias():
    assert parse_sets_string("BWx5") == [(0.0, 5)]

def test_parse_sets_weighted_bodyweight():
    # "+24" means 24 kg added to bodyweight
    assert parse_sets_string("+24x5") == [(24.0, 5)]

def test_parse_sets_reps_only():
    assert parse_sets_string("8 reps") == [(0.0, 8)]

def test_parse_sets_empty_and_dash():
    assert parse_sets_string("") == []
    assert parse_sets_string("—") == []
    assert parse_sets_string("-") == []

def test_parse_sets_skips_malformed_token():
    # "abc" can't be parsed — skip it, keep valid tokens
    result = parse_sets_string("80x5, abc, 90x1")
    assert result == [(80.0, 5), (90.0, 1)]

def test_parse_sets_decimal_weight():
    assert parse_sets_string("92.5x1") == [(92.5, 1)]


# ---------------------------------------------------------------------------
# epley_1rm
# ---------------------------------------------------------------------------

def test_epley_1rm_single_rep():
    # 100 × (1 + 1/30) = 103.33...
    assert abs(epley_1rm(100.0, 1) - 103.33) < 0.1

def test_epley_1rm_five_reps():
    # 80 × (1 + 5/30) = 93.33...
    assert abs(epley_1rm(80.0, 5) - 93.33) < 0.1

def test_epley_1rm_zero_weight():
    assert epley_1rm(0.0, 5) == 0.0

def test_epley_1rm_zero_reps():
    assert epley_1rm(100.0, 0) == 0.0

def test_epley_1rm_negative_weight():
    assert epley_1rm(-10.0, 5) == 0.0


# ---------------------------------------------------------------------------
# linear_slope
# ---------------------------------------------------------------------------

def test_slope_increasing():
    # y = x → slope = 1
    assert abs(linear_slope([0.0, 1.0, 2.0, 3.0]) - 1.0) < 0.001

def test_slope_decreasing():
    assert abs(linear_slope([3.0, 2.0, 1.0, 0.0]) - (-1.0)) < 0.001

def test_slope_flat():
    assert linear_slope([5.0, 5.0, 5.0]) == 0.0

def test_slope_too_few_values():
    assert linear_slope([]) == 0.0
    assert linear_slope([42.0]) == 0.0

def test_slope_two_points():
    # From 10 to 15 over 1 step → slope = 5
    assert abs(linear_slope([10.0, 15.0]) - 5.0) < 0.001


# ---------------------------------------------------------------------------
# identify_benchmark
# ---------------------------------------------------------------------------

def test_benchmark_bench_variants():
    assert identify_benchmark("Smith machine bench press") == "bench"
    assert identify_benchmark("Bench press") == "bench"
    assert identify_benchmark("Incline bench") == "bench"

def test_benchmark_deadlift():
    assert identify_benchmark("Deadlift") == "deadlift"
    assert identify_benchmark("Conventional deadlift") == "deadlift"

def test_benchmark_deadlift_excluded():
    assert identify_benchmark("Romanian deadlift") is None
    assert identify_benchmark("RDL") is None
    assert identify_benchmark("Stiff-leg deadlift") is None
    assert identify_benchmark("Single-leg deadlift") is None

def test_benchmark_squat():
    assert identify_benchmark("Squat") == "squat"
    assert identify_benchmark("Back squat") == "squat"

def test_benchmark_squat_excluded():
    assert identify_benchmark("Bulgarian split squat") is None
    assert identify_benchmark("Goblet squat") is None
    assert identify_benchmark("Hack squat") is None

def test_benchmark_accessory_returns_none():
    assert identify_benchmark("Cable rows") is None
    assert identify_benchmark("Pull-ups") is None
    assert identify_benchmark("Bicep curl") is None
    assert identify_benchmark("Overhead press") is None
    assert identify_benchmark("Dips") is None


# ---------------------------------------------------------------------------
# Strength Progression (via compute_metrics)
# ---------------------------------------------------------------------------

def test_strength_improving():
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 1, "80x5, 85x3, 90x1, 80x3, 70x5", 90.0),
        _make_entry("Bench press", "2026-04-28", "Chest", 5, 1, "82.5x5, 87.5x3, 92.5x1, 82.5x3, 72.5x5", 92.5),
        _make_entry("Bench press", "2026-05-05", "Chest", 5, 1, "85x5, 90x3, 95x1, 85x3, 75x5", 95.0),
    ]
    metrics = compute_metrics(entries, 4)
    bench = metrics["strength_progression"]["bench"]
    assert not bench["insufficient_data"]
    assert bench["trend"] == "improving"
    assert bench["plateau_risk"] == "low"
    assert bench["current_e1rm"] > 95.0

def test_strength_plateau():
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 1, "80x5, 85x3, 90x1, 80x3", 90.0),
        _make_entry("Bench press", "2026-04-28", "Chest", 5, 1, "80x5, 85x3, 90x1, 80x3", 90.0),
        _make_entry("Bench press", "2026-05-05", "Chest", 5, 1, "80x5, 85x3, 90x1, 80x3", 90.0),
    ]
    metrics = compute_metrics(entries, 4)
    bench = metrics["strength_progression"]["bench"]
    assert not bench["insufficient_data"]
    assert bench["plateau_risk"] == "high"
    assert bench["trend"] == "stable"

def test_strength_insufficient_data_one_session():
    entries = [
        _make_entry("Bench press", "2026-05-05", "Chest", 5, 1, "80x5, 85x3, 90x1", 90.0),
    ]
    metrics = compute_metrics(entries, 4)
    assert metrics["strength_progression"]["bench"]["insufficient_data"] is True

def test_strength_no_data_for_lift():
    entries = [
        _make_entry("Cable rows", "2026-04-21", "Back", 3, 10, "50x10", 50.0),
    ]
    metrics = compute_metrics(entries, 4)
    assert metrics["strength_progression"]["bench"]["insufficient_data"] is True
    assert metrics["strength_progression"]["deadlift"]["insufficient_data"] is True
    assert metrics["strength_progression"]["squat"]["insufficient_data"] is True

def test_strength_back_off_detected():
    # Pyramid with back-off: 5 sets, top at index 2, sets at 3 and 4 are back-offs
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 1, "80x5, 85x3, 90x1, 80x3, 70x5", 90.0),
        _make_entry("Bench press", "2026-04-28", "Chest", 5, 1, "80x5, 85x3, 92.5x1, 80x3, 70x5", 92.5),
    ]
    metrics = compute_metrics(entries, 4)
    sessions = metrics["strength_progression"]["bench"]["recent_sessions"]
    assert sessions[-1]["back_off_present"] is True

def test_strength_no_back_off_detected():
    # Only ascending sets, no back-off
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 3, 1, "80x5, 85x3, 90x1", 90.0),
        _make_entry("Bench press", "2026-04-28", "Chest", 3, 1, "82.5x5, 87.5x3, 92.5x1", 92.5),
    ]
    metrics = compute_metrics(entries, 4)
    sessions = metrics["strength_progression"]["bench"]["recent_sessions"]
    assert sessions[-1]["back_off_present"] is False

def test_strength_empty_entries():
    metrics = compute_metrics([], 4)
    assert metrics["strength_progression"]["bench"]["insufficient_data"] is True


# ---------------------------------------------------------------------------
# Adherence (via compute_metrics)
# ---------------------------------------------------------------------------

def test_adherence_perfect_4_weeks():
    entries = []
    dates = [
        # week 1
        ("2026-04-21", "2026-04-23", "2026-04-25"),
        # week 2
        ("2026-04-28", "2026-04-30", "2026-05-02"),
        # week 3
        ("2026-05-05", "2026-05-07", "2026-05-09"),
        # week 4
        ("2026-05-12", "2026-05-14", "2026-05-16"),
    ]
    for bench_d, dl_d, sq_d in dates:
        entries.append(_make_entry("Bench press", bench_d, "Chest", 5, 1, "90x1", 90.0))
        entries.append(_make_entry("Deadlift",    dl_d,    "Back",  5, 1, "160x1", 160.0))
        entries.append(_make_entry("Squat",       sq_d,    "Legs",  5, 1, "120x1", 120.0))
    metrics = compute_metrics(entries, 4)
    adh = metrics["adherence"]
    assert adh["total_sessions"] == 12
    assert adh["adherence_score"] == 100
    assert adh["current_streak_weeks"] == 4

def test_adherence_missed_squat_in_week1():
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 1, "90x1", 90.0),
        _make_entry("Deadlift",    "2026-04-23", "Back",  5, 1, "160x1", 160.0),
        # squat missing in week 1
        _make_entry("Bench press", "2026-04-28", "Chest", 5, 1, "90x1", 90.0),
        _make_entry("Deadlift",    "2026-04-30", "Back",  5, 1, "160x1", 160.0),
        _make_entry("Squat",       "2026-05-02", "Legs",  5, 1, "120x1", 120.0),
    ]
    metrics = compute_metrics(entries, 2)
    adh = metrics["adherence"]
    assert adh["total_sessions"] == 5
    assert adh["adherence_score"] < 100
    week1 = adh["weekly_breakdown"][0]
    assert week1["squat"] is False
    assert week1["bench"] is True
    assert week1["deadlift"] is True

def test_adherence_streak_broken():
    # Week 1: only 2 sessions. Week 2: 3 sessions. Streak = 1.
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 1, "90x1", 90.0),
        _make_entry("Deadlift",    "2026-04-23", "Back",  5, 1, "160x1", 160.0),
        # week 1 has only 2
        _make_entry("Bench press", "2026-04-28", "Chest", 5, 1, "90x1", 90.0),
        _make_entry("Deadlift",    "2026-04-30", "Back",  5, 1, "160x1", 160.0),
        _make_entry("Squat",       "2026-05-02", "Legs",  5, 1, "120x1", 120.0),
    ]
    metrics = compute_metrics(entries, 2)
    assert metrics["adherence"]["current_streak_weeks"] == 1

def test_adherence_benchmark_frequency_zero_squat():
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 1, "90x1", 90.0),
        _make_entry("Deadlift",    "2026-04-23", "Back",  5, 1, "160x1", 160.0),
        _make_entry("Bench press", "2026-04-28", "Chest", 5, 1, "90x1", 90.0),
        _make_entry("Deadlift",    "2026-04-30", "Back",  5, 1, "160x1", 160.0),
    ]
    metrics = compute_metrics(entries, 2)
    bf = metrics["adherence"]["benchmark_frequency"]
    assert bf["squat"] == 0.0
    assert bf["bench"] == 1.0
    assert bf["deadlift"] == 1.0

def test_adherence_arms_day_not_penalised():
    # Arms day counted as a session but does not affect benchmark frequency
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest",   5, 1, "90x1", 90.0),
        _make_entry("Deadlift",    "2026-04-23", "Back",    5, 1, "160x1", 160.0),
        _make_entry("Squat",       "2026-04-25", "Legs",    5, 1, "120x1", 120.0),
        _make_entry("Dips",        "2026-04-26", "Triceps", 8, 8, "BW", 0.0),
    ]
    metrics = compute_metrics(entries, 1)
    adh = metrics["adherence"]
    assert adh["total_sessions"] == 4   # 4 distinct dates
    assert adh["adherence_score"] == 100  # 4 ≥ 3 expected → capped at 100


# ---------------------------------------------------------------------------
# Volume Distribution (via compute_metrics)
# ---------------------------------------------------------------------------

def test_volume_push_heavy():
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest",    5, 5, "80x5", 80.0),
        _make_entry("Tricep dips", "2026-04-21", "Triceps",  3, 8, "BW",   0.0),
        _make_entry("Pull-ups",    "2026-04-21", "Back",     3, 8, "BW",   0.0),
    ]
    metrics = compute_metrics(entries, 1)
    vol = metrics["volume_distribution"]
    assert vol["push_sets"] == 8     # 5 (chest) + 3 (triceps)
    assert vol["pull_sets"] == 3
    assert vol["push_pull_ratio"] > 1.2

def test_volume_no_pull_ratio_none():
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 5, "80x5", 80.0),
    ]
    metrics = compute_metrics(entries, 1)
    assert metrics["volume_distribution"]["push_pull_ratio"] is None

def test_volume_undertrained_flagged():
    entries = [
        _make_entry("Overhead press", "2026-04-21", "Shoulders", 1, 5, "60x5", 60.0),
        _make_entry("Bench press",    "2026-04-21", "Chest",     8, 5, "80x5", 80.0),
    ]
    # 4-week window → shoulders = 0.25 sets/week → below 2.0 threshold
    metrics = compute_metrics(entries, 4)
    assert "Shoulders" in metrics["volume_distribution"]["undertrained_groups"]

def test_volume_legs_not_undertrained():
    entries = [
        _make_entry("Squat",      "2026-04-21", "Legs",  1, 3, "120x3", 120.0),
        _make_entry("Bench press","2026-04-21", "Chest", 8, 5,  "80x5",  80.0),
    ]
    metrics = compute_metrics(entries, 4)
    assert "Legs" not in metrics["volume_distribution"]["undertrained_groups"]

def test_volume_sets_by_muscle_group():
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 5, "80x5", 80.0),
        _make_entry("Bench press", "2026-04-21", "Chest", 3, 3, "85x3", 85.0),
        _make_entry("Cable rows",  "2026-04-21", "Back",  4, 8, "60x8", 60.0),
    ]
    metrics = compute_metrics(entries, 1)
    mg = metrics["volume_distribution"]["sets_by_muscle_group"]
    assert mg["Chest"] == 8
    assert mg["Back"] == 4


# ---------------------------------------------------------------------------
# format_metrics_for_llm
# ---------------------------------------------------------------------------

def test_format_contains_all_sections():
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 1, "80x5, 85x3, 90x1, 80x3, 70x5", 90.0),
        _make_entry("Bench press", "2026-04-28", "Chest", 5, 1, "82.5x5, 87.5x3, 92.5x1, 82.5x3", 92.5),
        _make_entry("Deadlift",    "2026-04-23", "Back",  5, 1, "130x5, 140x3, 155x1, 130x3", 155.0),
        _make_entry("Deadlift",    "2026-04-30", "Back",  5, 1, "132.5x5, 142.5x3, 157.5x1", 157.5),
    ]
    metrics = compute_metrics(entries, 2)
    out = format_metrics_for_llm(metrics)
    assert "--- Strength Progression ---" in out
    assert "--- Adherence ---" in out
    assert "--- Volume Distribution ---" in out
    assert "bench:" in out
    assert "deadlift:" in out
    assert "squat:" in out

def test_format_insufficient_data_shown():
    entries = [
        _make_entry("Bench press", "2026-05-05", "Chest", 5, 1, "90x1", 90.0),
    ]
    metrics = compute_metrics(entries, 4)
    out = format_metrics_for_llm(metrics)
    assert "insufficient data" in out

def test_format_empty_entries():
    metrics = compute_metrics([], 4)
    out = format_metrics_for_llm(metrics)
    assert "--- Strength Progression ---" in out
    assert "insufficient data" in out
