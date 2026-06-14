#!/usr/bin/env python3
"""
test_analytics.py — Unit tests for analytics.py
Run: pytest test_analytics.py -v
"""

import pytest
from datetime import date, timedelta
from analytics import (
    parse_sets_string,
    epley_1rm,
    linear_slope,
    identify_benchmark,
    compute_metrics,
    recommend_progression,
    detect_prs,
)
from weekly_report import format_metrics_for_llm


# ---------------------------------------------------------------------------
# recommend_progression helpers
# ---------------------------------------------------------------------------

def _hist(exercise, days_ago_and_weights):
    """Build history list: [(days_ago, weight_str, reps)] → list of rows."""
    today = date.today()
    rows = []
    for entry in days_ago_and_weights:
        days_ago = entry[0]
        weight_str = entry[1]
        reps = entry[2] if len(entry) > 2 else None
        row = {
            "exercise": exercise,
            "date": (today - timedelta(days=days_ago)).isoformat(),
            "weight": weight_str,
        }
        if reps is not None:
            row["reps"] = reps
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# recommend_progression tests
# ---------------------------------------------------------------------------

def test_recommend_all_reps_hit_progress():
    # 3 sessions: usual top = 8, last session all hit 8 → +2.5 kg
    hist = _hist("Bench Press", [
        (14, "77.5x8, 77.5x8, 77.5x8"),
        (7,  "77.5x8, 77.5x8, 77.5x8"),
        (0,  "77.5x8, 77.5x8, 77.5x8"),
    ])
    rec = recommend_progression(hist)
    assert rec["action"] == "progress"
    assert rec["weight_kg"] == 80.0

def test_recommend_lower_body_increment():
    # Squat: all reps hit → +5 kg increment
    hist = _hist("Squat", [
        (14, "100x5, 100x5, 100x5"),
        (7,  "100x5, 100x5, 100x5"),
        (0,  "100x5, 100x5, 100x5"),
    ])
    rec = recommend_progression(hist)
    assert rec["action"] == "progress"
    assert rec["weight_kg"] == 105.0

def test_recommend_reps_missed_same_weight():
    # Not all sets hit usual top (8) → repeat, target +1 rep on weakest set (7)
    hist = _hist("Bench Press", [
        (14, "80x8, 80x8, 80x8"),
        (7,  "80x8, 80x8, 80x8"),
        (0,  "80x8, 80x8, 80x7"),
    ])
    rec = recommend_progression(hist)
    assert rec["action"] == "repeat"
    assert rec["weight_kg"] == 80.0
    assert rec["target_reps"] == 8   # weakest 7 → target 8

def test_recommend_gap_over_14_days():
    hist = _hist("Bench Press", [
        (30, "80x8, 80x8, 80x8"),
        (20, "80x8, 80x8, 80x8"),
        (16, "80x8, 80x8, 80x8"),
    ])
    rec = recommend_progression(hist)
    assert rec["action"] == "repeat"
    assert "gap" in (rec["note"] or "")

def test_recommend_bodyweight_plus_one_rep():
    hist = _hist("Pull-ups", [
        (14, "BW", 8),
        (7,  "BW", 8),
        (0,  "BW", 8),
    ])
    rec = recommend_progression(hist)
    assert rec["action"] == "progress"
    assert rec["weight_kg"] is None
    assert rec["target_reps"] == 9

def test_recommend_loaded_bodyweight():
    hist = _hist("Pull-ups", [
        (14, "BW + 10kg", 8),
        (7,  "BW + 10kg", 8),
        (0,  "BW + 10kg", 8),
    ])
    rec = recommend_progression(hist)
    assert rec["action"] == "progress"
    assert rec["weight_kg"] == 12.5  # 10 + 2.5

def test_recommend_single_session_no_recommendation():
    hist = _hist("Bench Press", [(0, "80x8, 80x8, 80x8")])
    rec = recommend_progression(hist)
    assert rec["action"] == "no_recommendation"

def test_recommend_rpe_9_repeat():
    hist = _hist("Bench Press", [
        (14, "80x8, 80x8, 80x8"),
        (7,  "80x8, 80x8, 80x8"),
        (0,  "80x8, 80x8, 80x8"),
    ])
    hist[-1]["rpe"] = 9
    rec = recommend_progression(hist)
    assert rec["action"] == "repeat"
    assert "RPE" in (rec["note"] or "")

def test_recommend_pain_note_no_progression():
    hist = _hist("Bench Press", [
        (14, "80x8, 80x8, 80x8"),
        (7,  "80x8, 80x8, 80x8"),
        (0,  "80x8, 80x8, 80x8"),
    ])
    hist[-1]["pain_note"] = "shoulder twinge"
    rec = recommend_progression(hist)
    assert rec["action"] == "repeat"
    assert "shoulder twinge" in (rec["note"] or "")


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


# ---------------------------------------------------------------------------
# RPE signals (via compute_metrics)
# ---------------------------------------------------------------------------

def _entry_rpe(exercise, date_str, weight, rpe=None, pain_note=None):
    e = _make_entry(exercise, date_str, "Chest", 3, 8, weight, float(weight.split("x")[0]) if "x" in weight else 0)
    if rpe is not None:
        e["rpe"] = rpe
    if pain_note is not None:
        e["pain_note"] = pain_note
    return e


def test_avg_rpe_computed_per_exercise_week():
    entries = [
        _entry_rpe("Bench press", "2026-04-21", "80x8", rpe=7.0),
        _entry_rpe("Bench press", "2026-04-21", "80x8", rpe=9.0),
        _entry_rpe("Bench press", "2026-04-28", "80x8", rpe=8.0),
    ]
    metrics = compute_metrics(entries, 2)
    avg = metrics["rpe_signals"]["avg_rpe_by_exercise"].get("Bench press", {})
    # Week of Apr 21: avg of 7 and 9 = 8.0
    april_week = [v for k, v in avg.items() if "W17" in k or "2026-W" in k]
    assert any(abs(v - 8.0) < 0.1 for v in avg.values()), f"avg: {avg}"


def test_fatigue_flag_flat_e1rm_rising_rpe():
    """Flat e1RM + rising RPE → fatigue flag for that lift."""
    entries = [
        _entry_rpe("Bench press", "2026-04-07", "90x1", rpe=7.0),
        _entry_rpe("Bench press", "2026-04-14", "90x1", rpe=8.0),
        _entry_rpe("Bench press", "2026-04-21", "90x1", rpe=9.0),
    ]
    metrics = compute_metrics(entries, 4)
    flags = metrics["rpe_signals"]["fatigue_flags"]
    assert any(f["lift"] == "bench" for f in flags), f"flags: {flags}"


def test_no_fatigue_flag_when_e1rm_improving():
    """Rising e1RM → no fatigue flag even if RPE also rises."""
    entries = [
        _entry_rpe("Bench press", "2026-04-07", "85x1", rpe=7.0),
        _entry_rpe("Bench press", "2026-04-14", "90x1", rpe=8.0),
        _entry_rpe("Bench press", "2026-04-21", "95x1", rpe=9.0),
    ]
    metrics = compute_metrics(entries, 4)
    flags = metrics["rpe_signals"]["fatigue_flags"]
    bench_flags = [f for f in flags if f["lift"] == "bench"]
    assert not bench_flags, f"unexpected fatigue flag: {bench_flags}"


def test_pain_pattern_triggers_at_two_occurrences():
    entries = [
        _entry_rpe("Bench press", "2026-04-14", "80x8", pain_note="left shoulder twinge"),
        _entry_rpe("Bench press", "2026-04-21", "80x8", pain_note="shoulder ache again"),
    ]
    metrics = compute_metrics(entries, 2)
    patterns = metrics["rpe_signals"]["pain_patterns"]
    assert any(p["body_part"] == "shoulder" for p in patterns), f"patterns: {patterns}"


def test_pain_pattern_does_not_trigger_at_one():
    entries = [
        _entry_rpe("Bench press", "2026-04-14", "80x8", pain_note="knee twinge"),
    ]
    metrics = compute_metrics(entries, 2)
    patterns = metrics["rpe_signals"]["pain_patterns"]
    assert not any(p["body_part"] == "knee" for p in patterns), f"unexpected: {patterns}"


def test_rpe_signals_empty_when_no_rpe_data():
    """Old entries without rpe/pain_note → rpe_signals is present but empty/quiet."""
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 3, 8, "80x8", 80.0),
    ]
    metrics = compute_metrics(entries, 2)
    sig = metrics["rpe_signals"]
    assert sig["avg_rpe_by_exercise"] == {}
    assert sig["fatigue_flags"] == []
    assert sig["pain_patterns"] == []


def test_format_metrics_includes_fatigue_flag():
    """format_metrics_for_llm shows FATIGUE FLAG line when triggered."""
    entries = [
        _entry_rpe("Bench press", "2026-04-07", "90x1", rpe=7.0),
        _entry_rpe("Bench press", "2026-04-14", "90x1", rpe=8.0),
        _entry_rpe("Bench press", "2026-04-21", "90x1", rpe=9.0),
    ]
    metrics = compute_metrics(entries, 4)
    out = format_metrics_for_llm(metrics)
    assert "FATIGUE FLAG" in out or "fatigue" in out.lower(), out[-300:]


def test_format_metrics_includes_pain_pattern():
    """format_metrics_for_llm shows PAIN PATTERN line when ≥2 occurrences."""
    entries = [
        _entry_rpe("Bench press", "2026-04-14", "80x8", pain_note="shoulder pain"),
        _entry_rpe("Bench press", "2026-04-21", "80x8", pain_note="shoulder ache"),
    ]
    metrics = compute_metrics(entries, 2)
    out = format_metrics_for_llm(metrics)
    assert "PAIN PATTERN" in out or "shoulder" in out, out[-300:]


# ---------------------------------------------------------------------------
# detect_prs
# ---------------------------------------------------------------------------

def _pr_entry(exercise, date_str, weight_str):
    """Build a minimal workout entry for detect_prs tests."""
    return {
        "exercise": exercise,
        "date": date_str,
        "session": "",
        "muscle_group": "Chest",
        "sets": 3,
        "reps": 5,
        "weight": weight_str,
        "top_set_kg": 0.0,
    }


def test_detect_prs_first_ever_no_pr():
    """Single entry for an exercise — first-ever — should NOT be flagged as a PR."""
    entries = [_pr_entry("Squat", "2026-06-10", "100x5")]
    result = detect_prs(entries, window_days=30)
    # Either the exercise is absent or its PR list is empty
    assert result.get("Squat", []) == []


def test_detect_prs_weight_pr():
    """Window entry sets a new weight high — should return a weight-PR."""
    entries = [
        _pr_entry("Deadlift", "2026-05-01", "80x5, 85x3, 90x1"),   # prior
        _pr_entry("Deadlift", "2026-06-10", "80x5, 85x3, 92.5x1"), # window: new max
    ]
    result = detect_prs(entries, window_days=30)
    assert "Deadlift" in result
    prs = result["Deadlift"]
    assert len(prs) == 1
    pr = prs[0]
    assert pr["kind"] == "weight"
    assert pr["weight_kg"] == 92.5
    assert pr["prev_best_kg"] == 90.0


def test_detect_prs_rep_pr_equal_weight():
    """More reps at the same weight — should return a rep-PR (not a weight-PR)."""
    entries = [
        _pr_entry("Bench press", "2026-05-01", "80x6"),   # prior: 6 reps at 80
        _pr_entry("Bench press", "2026-06-10", "80x8"),   # window: 8 reps at 80
    ]
    result = detect_prs(entries, window_days=30)
    assert "Bench press" in result
    prs = result["Bench press"]
    assert len(prs) == 1
    pr = prs[0]
    assert pr["kind"] == "reps"
    assert pr["weight_kg"] == 80.0
    assert pr["reps"] == 8
    assert pr["prev_best_reps"] == 6


def test_detect_prs_no_pr():
    """Window entry is lighter than prior max and fewer reps — no PR."""
    entries = [
        _pr_entry("Romanian deadlift", "2026-05-01", "90x1, 87.5x5"),  # prior max=90, 5 reps@87.5
        _pr_entry("Romanian deadlift", "2026-06-10", "87.5x3"),         # window: lighter, fewer reps
    ]
    result = detect_prs(entries, window_days=30)
    assert result.get("Romanian deadlift", []) == []
