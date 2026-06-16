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
    match_slot,
    next_split,
    build_session_plan,
    score_adherence,
    classify_session,
)
from weekly_report import format_metrics_for_llm, _build_adherence_line


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


# ---------------------------------------------------------------------------
# plateau_flag
# ---------------------------------------------------------------------------

def test_plateau_flag_flat_e1rm():
    """3 bench entries across 3 different ISO weeks with identical top set → plateau flag."""
    entries = [
        _make_entry("Bench press", "2026-04-07", "Chest", 3, 1, "90x1, 85x3, 80x5", 90.0),
        _make_entry("Bench press", "2026-04-14", "Chest", 3, 1, "90x1, 85x3, 80x5", 90.0),
        _make_entry("Bench press", "2026-04-21", "Chest", 3, 1, "90x1, 85x3, 80x5", 90.0),
    ]
    metrics = compute_metrics(entries, 4)
    out = format_metrics_for_llm(metrics)
    assert "--- Plateau Alerts ---" in out
    assert "bench" in out.split("--- Plateau Alerts ---")[1]


def test_plateau_flag_declining_e1rm():
    """3 bench entries with declining top sets → plateau flag."""
    entries = [
        _make_entry("Bench press", "2026-04-07", "Chest", 3, 1, "92.5x1, 87.5x3, 82.5x5", 92.5),
        _make_entry("Bench press", "2026-04-14", "Chest", 3, 1, "90x1, 85x3, 80x5", 90.0),
        _make_entry("Bench press", "2026-04-21", "Chest", 3, 1, "87.5x1, 82.5x3, 77.5x5", 87.5),
    ]
    metrics = compute_metrics(entries, 4)
    out = format_metrics_for_llm(metrics)
    assert "--- Plateau Alerts ---" in out
    assert "bench" in out.split("--- Plateau Alerts ---")[1]


def test_no_plateau_flag_when_rising():
    """3 bench entries with improving top sets → NO plateau flag."""
    entries = [
        _make_entry("Bench press", "2026-04-07", "Chest", 3, 1, "90x1, 85x3, 80x5", 90.0),
        _make_entry("Bench press", "2026-04-14", "Chest", 3, 1, "92.5x1, 87.5x3, 82.5x5", 92.5),
        _make_entry("Bench press", "2026-04-21", "Chest", 3, 1, "95x1, 90x3, 85x5", 95.0),
    ]
    metrics = compute_metrics(entries, 4)
    out = format_metrics_for_llm(metrics)
    assert "--- Plateau Alerts ---" not in out


def test_no_plateau_flag_insufficient_data():
    """Only 2 bench entries (< 3 weeks of e1RM data) → NO plateau flag."""
    entries = [
        _make_entry("Bench press", "2026-04-14", "Chest", 3, 1, "90x1, 85x3, 80x5", 90.0),
        _make_entry("Bench press", "2026-04-21", "Chest", 3, 1, "90x1, 85x3, 80x5", 90.0),
    ]
    metrics = compute_metrics(entries, 4)
    out = format_metrics_for_llm(metrics)
    assert "--- Plateau Alerts ---" not in out


# ---------------------------------------------------------------------------
# gap_alerts
# ---------------------------------------------------------------------------

def test_gap_alert_when_muscle_has_zero_sets():
    """A muscle group with 0 sets logged triggers a Training Gaps alert."""
    entries = [
        _make_entry("Bench press",       "2026-04-21", "Chest",      5, 5, "80x5", 80.0),
        _make_entry("Romanian deadlift", "2026-04-21", "Hamstrings", 0, 0, "",     0.0),
    ]
    metrics = compute_metrics(entries, 4)
    out = format_metrics_for_llm(metrics)
    assert "--- Training Gaps ---" in out
    assert "hamstrings" in out.lower()


def test_no_gap_alert_when_muscle_has_sets():
    """All muscle groups with sets > 0 → no Training Gaps section."""
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 5, "80x5",  80.0),
        _make_entry("Squat",       "2026-04-21", "Legs",  4, 5, "100x5", 100.0),
    ]
    metrics = compute_metrics(entries, 4)
    out = format_metrics_for_llm(metrics)
    assert "--- Training Gaps ---" not in out


# ---------------------------------------------------------------------------
# weight_svg_overlay
# ---------------------------------------------------------------------------

from weekly_report import _build_weight_svg


def test_weight_svg_two_series_when_e1rm_present():
    """When e1rm_series has 2+ in-range points, SVG contains 2 polylines."""
    bw = [("2026-04-21", 82.0), ("2026-05-19", 81.5)]
    # 2026-W18 Monday = 2026-04-27, 2026-W20 Monday = 2026-05-11 — both in range
    e1rm = {"bench": [("2026-W18", 105.0), ("2026-W20", 106.0)]}
    svg = _build_weight_svg(bw, e1rm)
    assert svg.count("<polyline") >= 2


def test_weight_svg_one_series_when_e1rm_absent():
    """No e1rm_series → exactly 1 polyline (bw only)."""
    bw = [("2026-04-21", 82.0), ("2026-04-28", 81.8), ("2026-05-05", 81.5)]
    svg = _build_weight_svg(bw)
    assert svg.count("<polyline") == 1


def test_weight_svg_fallback_no_crash_empty_e1rm():
    """Empty e1rm_series dict → falls back to single-series, no crash."""
    result = _build_weight_svg([("2026-04-21", 82.0), ("2026-05-05", 81.5)], {})
    assert isinstance(result, str) and len(result) > 0


# ---------------------------------------------------------------------------
# match_slot — slot list fixtures mirroring workout_plan.json
# ---------------------------------------------------------------------------

_CHEST_SLOTS = [
    {"slot": "Bench press",           "type": "main",      "match": ["bench", "bench press", "smith machine bench press", "machine bench press"]},
    {"slot": "Pull-ups",              "type": "main",      "match": ["pull-up", "pull up", "pullup", "chin-up", "chin up"]},
    {"slot": "Bulgarian split squat", "type": "main",      "match": ["bulgarian", "split squat"]},
    {"slot": "Triceps",               "type": "accessory", "match": ["tricep", "pushdown", "push-down", "skull", "overhead extension"]},
    {"slot": "Biceps",                "type": "accessory", "match": ["bicep", "curl", "bicep curl", "preacher curl", "hammer curl"]},
]

_DEADLIFT_SLOTS = [
    {"slot": "Deadlift",       "type": "main",      "match": ["deadlift", "rdl", "romanian"]},
    {"slot": "Overhead Press", "type": "main",      "match": ["overhead press", "overhead barbell press", "ohp", "shoulder press", "military"]},
    {"slot": "Leg extension",  "type": "main",      "match": ["leg extension", "quad extension"]},
    {"slot": "Triceps",        "type": "accessory", "match": ["tricep", "pushdown", "push-down", "skull", "overhead extension"]},
    {"slot": "Biceps",         "type": "accessory", "match": ["bicep", "curl", "bicep curl", "preacher curl", "hammer curl"]},
]

_SQUAT_SLOTS = [
    {"slot": "Squat",   "type": "main",      "match": ["squat", "hack-squat", "hack squat"]},
    {"slot": "Dips",    "type": "main",      "match": ["dip", "dips", "machine dip", "machine dips"]},
    {"slot": "Rows",    "type": "main",      "match": ["row", "rows", "machine row", "machine rows", "cable row"]},
    {"slot": "Biceps",  "type": "accessory", "match": ["bicep", "curl", "bicep curl", "preacher curl", "hammer curl"]},
    {"slot": "Triceps", "type": "accessory", "match": ["tricep", "pushdown", "push-down", "skull", "overhead extension"]},
]

# Off-cycle Arms slots — includes Forearms for collision tests
_ARMS_SLOTS = [
    {"slot": "Biceps",   "type": "accessory", "match": ["bicep", "curl", "bicep curl", "preacher curl", "hammer curl"]},
    {"slot": "Triceps",  "type": "accessory", "match": ["tricep", "pushdown", "push-down", "skull", "overhead extension"]},
    {"slot": "Forearms", "type": "accessory", "match": ["forearm", "forearm curl", "wrist", "wrist curl", "wrist twister", "grip", "reverse curl"]},
]


def _slot_name(result):
    return result["slot"] if result else None


def test_match_slot_smith_machine_bench_press():
    assert _slot_name(match_slot("Smith Machine Bench Press", _CHEST_SLOTS)) == "Bench press"


def test_match_slot_overhead_barbell_press():
    assert _slot_name(match_slot("Overhead Barbell Press", _DEADLIFT_SLOTS)) == "Overhead Press"


def test_match_slot_triceps_pushdown():
    assert _slot_name(match_slot("Triceps Pushdown", _CHEST_SLOTS)) == "Triceps"


def test_match_slot_pull_ups():
    assert _slot_name(match_slot("Pull-ups", _CHEST_SLOTS)) == "Pull-ups"


def test_match_slot_leg_extension():
    assert _slot_name(match_slot("Leg Extension", _DEADLIFT_SLOTS)) == "Leg extension"


def test_match_slot_machine_row():
    assert _slot_name(match_slot("machine row", _SQUAT_SLOTS)) == "Rows"


def test_match_slot_hack_squat():
    assert _slot_name(match_slot("hack squat", _SQUAT_SLOTS)) == "Squat"


def test_match_slot_narrow_grip_pulldown_not_rows():
    # "row" must NOT match "narrow" — word-start boundary check
    assert match_slot("narrow grip pulldown", _SQUAT_SLOTS) is None


def test_match_slot_wrist_curl_forearms_not_biceps():
    # "wrist curl" (9 chars) beats "curl" (4 chars) → Forearms wins
    assert _slot_name(match_slot("wrist curl", _ARMS_SLOTS)) == "Forearms"


def test_match_slot_cable_curl_biceps():
    # "curl" matches Biceps; Forearms keywords don't appear in "cable curl"
    assert _slot_name(match_slot("cable curl", _ARMS_SLOTS)) == "Biceps"


def test_match_slot_preacher_curl_biceps():
    # "preacher curl" (12 chars) in Biceps slot beats "curl" (4 chars)
    assert _slot_name(match_slot("preacher curl", _ARMS_SLOTS)) == "Biceps"


def test_match_slot_no_match():
    assert match_slot("jumping jacks", _CHEST_SLOTS) is None


# ---------------------------------------------------------------------------
# next_split
# ---------------------------------------------------------------------------

_CYCLE = ["Chest", "Deadlift", "Squat"]


def _entries_with_sessions(*session_labels):
    """Build minimal entry list: each label becomes one entry, in order."""
    return [{"session": label, "date": f"2026-01-{i+1:02d}", "exercise": "x"} for i, label in enumerate(session_labels)]


def test_next_split_after_chest():
    entries = _entries_with_sessions("Chest")
    assert next_split(entries, _CYCLE) == "Deadlift"


def test_next_split_after_deadlift():
    entries = _entries_with_sessions("Deadlift")
    assert next_split(entries, _CYCLE) == "Squat"


def test_next_split_after_squat_wraps():
    entries = _entries_with_sessions("Squat")
    assert next_split(entries, _CYCLE) == "Chest"


def test_next_split_full_rotation_chest_deadlift():
    entries = _entries_with_sessions("Chest", "Deadlift")
    assert next_split(entries, _CYCLE) == "Squat"


def test_next_split_empty_entries_returns_first():
    assert next_split([], _CYCLE) == "Chest"


def test_next_split_no_in_cycle_history_returns_first():
    entries = _entries_with_sessions("Arms", "Other")
    assert next_split(entries, _CYCLE) == "Chest"


def test_next_split_off_cycle_trailing_does_not_advance():
    # Last in-cycle was Deadlift; Arms session after it must not advance
    entries = _entries_with_sessions("Chest", "Deadlift", "Arms")
    assert next_split(entries, _CYCLE) == "Squat"


def test_next_split_case_insensitive():
    entries = _entries_with_sessions("chest")
    assert next_split(entries, _CYCLE) == "Deadlift"


# ---------------------------------------------------------------------------
# build_session_plan
# ---------------------------------------------------------------------------

_CHEST_TEMPLATE = [
    {"slot": "Bench press",           "type": "main",      "match": ["bench", "bench press"]},
    {"slot": "Pull-ups",              "type": "main",      "match": ["pull-up", "pullup"]},
    {"slot": "Triceps",               "type": "accessory", "muscle": "Triceps",
     "match": ["tricep", "pushdown"]},
    {"slot": "Biceps",                "type": "accessory", "muscle": "Biceps",
     "match": ["bicep", "curl"]},
]

_TODAY = date.today()


def _wo(exercise, days_ago, weight, reps=5, session="Chest"):
    return {
        "exercise": exercise,
        "date": (_TODAY - timedelta(days=days_ago)).isoformat(),
        "weight": weight,
        "reps": reps,
        "sets": 3,
        "session": session,
        "top_set_kg": None,
        "muscle_group": "",
    }


def test_build_session_plan_main_progresses():
    entries = [
        _wo("Bench Press", 14, "70x5, 70x5, 70x5"),
        _wo("Bench Press",  7, "70x5, 70x5, 70x5"),
        _wo("Bench Press",  0, "70x5, 70x5, 70x5"),
    ]
    plan = build_session_plan(entries, "Chest", _CHEST_TEMPLATE)
    bench = next(s for s in plan if s["slot"] == "Bench press")
    assert bench["exercise"] == "Bench Press"
    assert bench["rec"]["action"] == "progress"
    assert bench["rec"]["weight_kg"] == 72.5


def test_build_session_plan_variation_swap_uses_latest():
    # Two bench variations; Smith Machine is more recent → plan uses Smith Machine
    entries = [
        _wo("Bench Press",       14, "70x5, 70x5, 70x5"),
        _wo("Bench Press",        7, "70x5, 70x5, 70x5"),
        _wo("Smith Machine Bench Press", 3, "65x8, 65x8"),
        _wo("Smith Machine Bench Press", 1, "65x8, 65x8"),
    ]
    plan = build_session_plan(entries, "Chest", _CHEST_TEMPLATE)
    bench = next(s for s in plan if s["slot"] == "Bench press")
    assert bench["exercise"] == "Smith Machine Bench Press"
    assert bench["rec"]["action"] in ("progress", "repeat", "no_recommendation")


def test_build_session_plan_too_few_sessions_main_last_only():
    # Only 1 bench session → suggestion: None, last numbers shown
    entries = [_wo("Bench Press", 5, "70x5, 70x5")]
    plan = build_session_plan(entries, "Chest", _CHEST_TEMPLATE)
    bench = next(s for s in plan if s["slot"] == "Bench press")
    assert bench["exercise"] == "Bench Press"
    assert bench["suggestion"] is None
    assert bench["last_sets_str"] == "70x5, 70x5"
    assert "rec" not in bench


def test_build_session_plan_no_history_main_reminder():
    # No matching exercises → reminder
    plan = build_session_plan([], "Chest", _CHEST_TEMPLATE)
    bench = next(s for s in plan if s["slot"] == "Bench press")
    assert bench.get("reminder") is True


def test_build_session_plan_accessory_with_history_progresses():
    entries = [
        _wo("Triceps Pushdown", 14, "30x12, 30x12"),
        _wo("Triceps Pushdown",  7, "30x12, 30x12"),
    ]
    plan = build_session_plan(entries, "Chest", _CHEST_TEMPLATE)
    tri = next(s for s in plan if s["slot"] == "Triceps")
    assert tri["exercise"] == "Triceps Pushdown"
    assert tri["rec"]["action"] in ("progress", "repeat")


def test_build_session_plan_accessory_no_history_reminder():
    plan = build_session_plan([], "Chest", _CHEST_TEMPLATE)
    tri = next(s for s in plan if s["slot"] == "Triceps")
    assert tri.get("reminder") is True


def test_build_session_plan_accessory_one_session_reminder():
    entries = [_wo("Bicep Curl", 5, "20x10, 20x10")]
    plan = build_session_plan(entries, "Chest", _CHEST_TEMPLATE)
    bic = next(s for s in plan if s["slot"] == "Biceps")
    assert bic.get("reminder") is True


def test_build_session_plan_order_matches_template():
    plan = build_session_plan([], "Chest", _CHEST_TEMPLATE)
    assert [s["slot"] for s in plan] == [t["slot"] for t in _CHEST_TEMPLATE]


# ---------------------------------------------------------------------------
# score_adherence
# ---------------------------------------------------------------------------

_ADHERE_TEMPLATES = [
    {"slot": "Bench press", "type": "main",      "match": ["bench"]},
    {"slot": "Overhead",    "type": "main",      "match": ["overhead press", "ohp"]},
    {"slot": "Triceps",     "type": "accessory", "match": ["tricep", "pushdown"]},
]

_TODAY_A = date.today()


def _sa_entry(exercise, days_ago, weight, reps=5, session="Chest"):
    """Build a minimal workout entry for score_adherence tests."""
    return {
        "exercise": exercise,
        "date": (_TODAY_A - timedelta(days=days_ago)).isoformat(),
        "weight": weight,
        "reps": reps,
        "sets": 3,
        "session": session,
        "top_set_kg": None,
        "muscle_group": "",
    }


def test_score_adherence_empty_window_returns_zero():
    result = score_adherence([], 28, _ADHERE_TEMPLATES)
    assert result["total"] == 0
    assert result["detail"] == []


def test_score_adherence_no_templates_returns_zero():
    entries = [_sa_entry("Bench Press", 3, "70x5")]
    result = score_adherence(entries, 28, [])
    assert result["total"] == 0


def test_score_adherence_hit():
    # Two prior sessions at 70×5, suggestion will be 72.5×5 (progress).
    # Actual session: 72.5×5 → hit.
    entries = [
        _sa_entry("Bench Press", 14, "70x5, 70x5, 70x5"),
        _sa_entry("Bench Press",  7, "70x5, 70x5, 70x5"),
        _sa_entry("Bench Press",  1, "72.5x5, 72.5x5, 72.5x5"),
    ]
    result = score_adherence(entries, 28, _ADHERE_TEMPLATES)
    assert result["total"] >= 1
    in_window = [d for d in result["detail"] if d["exercise"] == "Bench Press"]
    assert any(d["outcome"] == "hit" for d in in_window)


def test_score_adherence_beat_more_weight():
    # Two prior sessions at 70×5, suggestion ≈ 72.5×5.
    # Actual: 80×5 → beat (more weight than suggested).
    entries = [
        _sa_entry("Bench Press", 14, "70x5, 70x5, 70x5"),
        _sa_entry("Bench Press",  7, "70x5, 70x5, 70x5"),
        _sa_entry("Bench Press",  1, "80x5, 80x5"),
    ]
    result = score_adherence(entries, 28, _ADHERE_TEMPLATES)
    in_window = [d for d in result["detail"] if d["exercise"] == "Bench Press"]
    assert any(d["outcome"] == "beat" for d in in_window)


def test_score_adherence_beat_more_reps_same_weight():
    # Two prior sessions at 70×5, suggestion ≈ 72.5×5.
    # Actual: 72.5×8 → beat (same weight, more reps).
    entries = [
        _sa_entry("Bench Press", 14, "70x5, 70x5, 70x5"),
        _sa_entry("Bench Press",  7, "70x5, 70x5, 70x5"),
        _sa_entry("Bench Press",  1, "72.5x8, 72.5x8"),
    ]
    result = score_adherence(entries, 28, _ADHERE_TEMPLATES)
    in_window = [d for d in result["detail"] if d["exercise"] == "Bench Press"]
    assert any(d["outcome"] == "beat" for d in in_window)


def test_score_adherence_missed():
    # Two prior sessions at 70×5, suggestion ≈ 72.5×5.
    # Actual: 60×5 → missed (less weight).
    entries = [
        _sa_entry("Bench Press", 14, "70x5, 70x5, 70x5"),
        _sa_entry("Bench Press",  7, "70x5, 70x5, 70x5"),
        _sa_entry("Bench Press",  1, "60x5, 60x5"),
    ]
    result = score_adherence(entries, 28, _ADHERE_TEMPLATES)
    in_window = [d for d in result["detail"] if d["exercise"] == "Bench Press"]
    assert any(d["outcome"] == "missed" for d in in_window)


def test_score_adherence_one_prior_session_skipped():
    # Only 1 prior session → no suggestion existed → skipped.
    entries = [
        _sa_entry("Bench Press", 7, "70x5, 70x5"),
        _sa_entry("Bench Press", 1, "72.5x5, 72.5x5"),
    ]
    result = score_adherence(entries, 28, _ADHERE_TEMPLATES)
    # The in-window session at day-1 has only 1 prior → skipped
    assert result["total"] == 0


def test_score_adherence_accessory_skipped():
    # Triceps Pushdown matches the accessory slot → skipped for scoring.
    entries = [
        _sa_entry("Triceps Pushdown", 14, "30x12"),
        _sa_entry("Triceps Pushdown",  7, "30x12"),
        _sa_entry("Triceps Pushdown",  1, "32.5x12"),
    ]
    result = score_adherence(entries, 28, _ADHERE_TEMPLATES)
    assert result["total"] == 0


def test_score_adherence_outside_window_not_counted():
    # Session 40 days ago is outside a 28-day window → not scored.
    entries = [
        _sa_entry("Bench Press", 60, "70x5"),
        _sa_entry("Bench Press", 50, "70x5"),
        _sa_entry("Bench Press", 40, "72.5x5"),
    ]
    result = score_adherence(entries, 28, _ADHERE_TEMPLATES)
    assert result["total"] == 0


def test_score_adherence_aggregate_counts():
    # Multiple in-window sessions; verify totals = hit + beat + missed.
    entries = [
        # Session A prior sessions
        _sa_entry("Bench Press", 21, "70x5, 70x5"),
        _sa_entry("Bench Press", 14, "70x5, 70x5"),
        # In-window session A: hit
        _sa_entry("Bench Press",  7, "72.5x5, 72.5x5"),
        # In-window session B: missed
        _sa_entry("Bench Press",  1, "60x5, 60x5"),
    ]
    result = score_adherence(entries, 28, _ADHERE_TEMPLATES)
    assert result["total"] == result["hit"] + result["beat"] + result["missed"]
    assert result["total"] >= 2


# ---------------------------------------------------------------------------
# _build_adherence_line (weekly_report.py helper)
# ---------------------------------------------------------------------------

def test_build_adherence_line_with_data():
    adh = {
        "total": 9, "hit": 6, "beat": 2, "missed": 1,
        "detail": [
            {"exercise": "Bench Press", "date": "2026-06-10",
             "outcome": "missed", "actual": "70x5", "planned": "72.5x5"},
        ],
    }
    line = _build_adherence_line(adh)
    assert "8/9" in line          # hit + beat = 8
    assert "2 beat" in line
    assert "1 missed" in line
    assert "Bench Press" in line  # missed example included


def test_build_adherence_line_no_missed_example():
    adh = {"total": 3, "hit": 2, "beat": 1, "missed": 0, "detail": []}
    line = _build_adherence_line(adh)
    assert "3/3" in line
    assert "0 missed" in line
    assert "(" not in line  # no example when no misses


def test_build_adherence_line_total_zero_returns_empty():
    assert _build_adherence_line({"total": 0, "hit": 0, "beat": 0, "missed": 0, "detail": []}) == ""


def test_build_adherence_line_empty_dict_returns_empty():
    assert _build_adherence_line({}) == ""


def test_format_metrics_unchanged_without_adherence():
    """format_metrics_for_llm output is unaffected — adherence line is separate."""
    entries = [
        _make_entry("Bench press", "2026-04-21", "Chest", 5, 1, "80x5, 85x3, 90x1", 90.0),
        _make_entry("Bench press", "2026-04-28", "Chest", 5, 1, "82.5x5, 87.5x3, 92.5x1", 92.5),
    ]
    metrics = compute_metrics(entries, 2)
    out = format_metrics_for_llm(metrics)
    assert "--- Strength Progression ---" in out
    assert "--- Adherence ---" in out
    # The plan-adherence section is appended by main(), not by format_metrics_for_llm
    assert "Plan Adherence" not in out


# ---------------------------------------------------------------------------
# classify_session — Step 2 bugfix
# ---------------------------------------------------------------------------

def test_classify_session_chest_day():
    """Bench + Bulgarian split squat (typical chest day) → Chest."""
    names = ["Bench Press", "Bulgarian split squat", "Cable fly", "Triceps pushdown"]
    assert classify_session(names) == "Chest"


def test_classify_session_deadlift_day():
    """Deadlift day → Deadlift."""
    names = ["Deadlift", "Romanian deadlift", "Barbell row"]
    assert classify_session(names) == "Deadlift"


def test_classify_session_squat_day():
    """Squat and hack squat → Squat."""
    names = ["Squat", "Hack squat", "Leg press"]
    assert classify_session(names) == "Squat"


def test_classify_session_arms_only():
    """Pure arms isolation → Arms."""
    names = ["Bicep curl", "Hammer curl", "Triceps pushdown"]
    assert classify_session(names) == "Arms"


def test_classify_session_empty():
    """No exercises → Other."""
    assert classify_session([]) == "Other"


def test_classify_session_deadlift_wins_over_bench():
    """Deadlift has priority over bench when both present."""
    assert classify_session(["Deadlift", "Bench press"]) == "Deadlift"


def test_classify_session_bench_wins_over_split_squat():
    """Bench wins even when Bulgarian split squat is in the list."""
    assert classify_session(["Bench Press", "Bulgarian split squat"]) == "Chest"


def test_classify_session_hack_squat_is_squat():
    """Hack squat (no 'split' in name) classifies as Squat."""
    assert classify_session(["Hack squat", "Leg press"]) == "Squat"


def test_classify_session_split_squat_alone_is_other():
    """Bulgarian split squat alone (no bench, no deadlift) → Other."""
    assert classify_session(["Bulgarian split squat"]) == "Other"
