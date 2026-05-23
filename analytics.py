#!/usr/bin/env python3
"""
analytics.py — Deterministic metrics for the weekly coaching report.
Pure functions only: no I/O, no API calls, no side effects.

Public interface:
    compute_metrics(entries, weeks) -> dict
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

log = logging.getLogger("analytics")


def _iso_week(date_str: str) -> str:
    try:
        d = datetime.fromisoformat(date_str).date()
        return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    except ValueError:
        return "unknown"


def parse_sets_string(weight: str) -> list[tuple[float, int]]:
    """
    Parse compact sets-detail string into (weight_kg, reps) pairs.
    "80x5, 85x3, 90x1"  -> [(80.0,5),(85.0,3),(90.0,1)]
    "bodyweightx8"       -> [(0.0,8)]
    "+24x5"              -> [(24.0,5)]
    "8 reps"             -> [(0.0,8)]
    ""  or  "—"          -> []
    """
    if not weight or weight.strip() in ("—", "-", ""):
        return []

    results: list[tuple[float, int]] = []
    for token in weight.split(","):
        token = token.strip()
        if not token:
            continue

        # "N reps" format — reps with no weight
        if token.endswith(" reps"):
            try:
                results.append((0.0, int(token[:-5].strip())))
            except ValueError:
                log.warning("parse_sets_string: cannot parse '%s'", token)
            continue

        token_lower = token.lower()

        if "x" in token_lower:
            x_idx = token_lower.index("x")
            weight_part = token_lower[:x_idx].strip()
            reps_part   = token_lower[x_idx + 1:].strip()

            try:
                reps = int(reps_part)
            except ValueError:
                log.warning("parse_sets_string: cannot parse reps in '%s'", token)
                continue

            if weight_part in ("bodyweight", "bw", "body weight", "body"):
                results.append((0.0, reps))
            else:
                try:
                    # Handle compound weights like "70 + 10" (bar + added weight)
                    if "+" in weight_part:
                        parts_sum = sum(
                            float(p.strip().rstrip("skgKG"))
                            for p in weight_part.split("+")
                            if p.strip().rstrip("skgKG")
                        )
                        results.append((parts_sum, reps))
                    else:
                        # Strip trailing tempo/unit suffixes: "60s" → 60.0
                        clean = weight_part.rstrip("skgKG").strip()
                        results.append((float(clean), reps))
                except (ValueError, ZeroDivisionError):
                    log.warning("parse_sets_string: cannot parse weight in '%s'", token)
        else:
            # No "x" — bare weight or bare "bodyweight"
            if token_lower in ("bodyweight", "bw", "body weight"):
                results.append((0.0, 0))
            else:
                try:
                    results.append((float(token.lstrip("+")), 0))
                except ValueError:
                    log.warning("parse_sets_string: cannot parse token '%s'", token)

    return results


def epley_1rm(weight_kg: float, reps: int) -> float:
    """Epley formula: weight × (1 + reps/30). Returns 0.0 for invalid inputs."""
    if weight_kg <= 0 or reps <= 0:
        return 0.0
    return weight_kg * (1 + reps / 30)


def linear_slope(values: list[float]) -> float:
    """Least-squares slope indexed 0,1,2,... Returns 0.0 for fewer than 2 values."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den != 0 else 0.0


_BENCHMARKS: dict[str, dict] = {
    "bench":    {"includes": ("bench",),    "excludes": ()},
    "deadlift": {"includes": ("deadlift",), "excludes": ("romanian", "rdl", "single", "stiff", "sumo")},
    "squat":    {"includes": ("squat",),    "excludes": ("bulgarian", "split", "goblet", "hack", "box")},
}


def identify_benchmark(exercise_name: str) -> Optional[str]:
    """Return 'bench', 'deadlift', 'squat', or None for accessories."""
    name = exercise_name.lower()
    for key, cfg in _BENCHMARKS.items():
        if any(inc in name for inc in cfg["includes"]):
            if not any(exc in name for exc in cfg["excludes"]):
                return key
    return None


def _compute_strength_progression(entries: list[dict]) -> dict:
    by_lift: dict[str, list] = defaultdict(list)
    for e in entries:
        key = identify_benchmark(e.get("exercise", ""))
        if key:
            by_lift[key].append(e)

    results = {}
    _insufficient = {
        "insufficient_data": True, "current_e1rm": None,
        "trend": None, "velocity_kg_per_week": None,
        "plateau_risk": None, "recent_sessions": [], "weekly_e1rm": [],
    }

    for lift_key in ("bench", "deadlift", "squat"):
        lift_entries = sorted(by_lift[lift_key], key=lambda e: e["date"])

        # Group by ISO week, pick entry with highest top_set_kg
        by_week: dict[str, list] = defaultdict(list)
        for e in lift_entries:
            by_week[_iso_week(e["date"])].append(e)

        weekly_data = []
        for week in sorted(by_week.keys()):
            best = max(by_week[week], key=lambda e: e.get("top_set_kg") or 0)
            top_set_kg = best.get("top_set_kg") or 0
            if not top_set_kg:
                continue

            pyramid = parse_sets_string(best.get("weight", ""))
            valid = [(w, r) for w, r in pyramid if w > 0]

            if valid:
                top_w, top_r = max(valid, key=lambda p: p[0])
            else:
                top_w = top_set_kg
                top_r = best.get("reps") or 1

            e1rm = epley_1rm(top_w, top_r)
            if e1rm <= 0:
                continue

            # Back-off: sets exist after the max-weight set
            back_off_present = False
            if pyramid:
                max_idx = max(range(len(pyramid)), key=lambda i: pyramid[i][0])
                back_off_present = max_idx < len(pyramid) - 1

            volume_load = sum(w * r for w, r in pyramid if w > 0 and r > 0)

            weekly_data.append({
                "week": week,
                "e1rm": e1rm,
                "entry": best,
                "pyramid": pyramid,
                "top_set": {"weight_kg": top_w, "reps": top_r},
                "volume_load_kg": round(volume_load, 1),
                "back_off_present": back_off_present,
            })

        if len(weekly_data) < 2:
            results[lift_key] = dict(_insufficient)
            continue

        trend_window = weekly_data[-3:]
        e1rm_series = [d["e1rm"] for d in trend_window]
        slope = linear_slope(e1rm_series)

        trend = "improving" if slope >= 1.0 else ("declining" if slope <= -1.0 else "stable")
        improvement = trend_window[-1]["e1rm"] - trend_window[0]["e1rm"]
        plateau_risk = "high" if improvement < 2.5 else ("medium" if improvement < 5.0 else "low")

        results[lift_key] = {
            "insufficient_data": False,
            "current_e1rm": round(weekly_data[-1]["e1rm"], 1),
            "trend": trend,
            "velocity_kg_per_week": round(slope, 2),
            "plateau_risk": plateau_risk,
            "recent_sessions": [
                {
                    "date": d["entry"]["date"],
                    "top_set": d["top_set"],
                    "pyramid": d["pyramid"],
                    "volume_load_kg": d["volume_load_kg"],
                    "back_off_present": d["back_off_present"],
                }
                for d in weekly_data[-3:]
            ],
            "weekly_e1rm": [(d["week"], round(d["e1rm"], 1)) for d in weekly_data],
        }

    return results


def _compute_adherence(entries: list[dict], weeks: int) -> dict:
    # Track distinct session dates and which benchmarks each date contains
    dates_benchmarks: dict[str, dict] = defaultdict(
        lambda: {"bench": False, "deadlift": False, "squat": False}
    )
    for e in entries:
        d = e.get("date", "")
        if not d:
            continue
        dates_benchmarks[d]   # ensure key exists
        key = identify_benchmark(e.get("exercise", ""))
        if key:
            dates_benchmarks[d][key] = True

    session_dates = sorted(dates_benchmarks.keys())

    # Group dates by ISO week
    by_week: dict[str, list] = defaultdict(list)
    for d in session_dates:
        by_week[_iso_week(d)].append(d)

    # Aggregate benchmark presence per week
    bench_by_week: dict[str, dict] = defaultdict(
        lambda: {"bench": False, "deadlift": False, "squat": False}
    )
    for d in session_dates:
        week = _iso_week(d)
        for key in ("bench", "deadlift", "squat"):
            if dates_benchmarks[d][key]:
                bench_by_week[week][key] = True

    total = len(session_dates)
    expected = weeks * 3
    adherence_score = min(100, round(total / expected * 100)) if expected > 0 else 0
    avg_per_week = round(total / weeks, 1) if weeks > 0 else 0.0

    # Current streak: consecutive completed weeks (≥3 sessions) from the end
    sorted_weeks = sorted(by_week.keys())
    streak = 0
    for week in reversed(sorted_weeks):
        if len(by_week[week]) >= 3:
            streak += 1
        else:
            break

    weekly_breakdown = [
        {
            "week": week,
            "sessions": len(by_week[week]),
            "bench":    bench_by_week[week]["bench"],
            "deadlift": bench_by_week[week]["deadlift"],
            "squat":    bench_by_week[week]["squat"],
        }
        for week in sorted_weeks
    ]

    benchmark_frequency = {
        key: round(
            sum(1 for d in session_dates if dates_benchmarks[d][key]) / weeks, 2
        ) if weeks > 0 else 0.0
        for key in ("bench", "deadlift", "squat")
    }

    return {
        "total_sessions":        total,
        "expected_sessions":     expected,
        "adherence_score":       adherence_score,
        "avg_sessions_per_week": avg_per_week,
        "current_streak_weeks":  streak,
        "weekly_breakdown":      weekly_breakdown,
        "benchmark_frequency":   benchmark_frequency,
    }


_PUSH_GROUPS = {"chest", "shoulders", "triceps"}
_PULL_GROUPS = {"back", "biceps"}
_LEGS_GROUPS = {"legs", "glutes", "hamstrings"}


def _compute_volume_distribution(entries: list[dict], weeks: int) -> dict:
    sets_by_muscle: dict[str, int] = defaultdict(int)
    for e in entries:
        mg = (e.get("muscle_group") or "").strip()
        if not mg:
            continue
        sets_by_muscle[mg] += e.get("sets") or 0

    avg_per_week = {
        mg: round(total / weeks, 1)
        for mg, total in sets_by_muscle.items()
    } if weeks > 0 else {}

    push_sets = sum(v for k, v in sets_by_muscle.items() if k.lower() in _PUSH_GROUPS)
    pull_sets = sum(v for k, v in sets_by_muscle.items() if k.lower() in _PULL_GROUPS)
    push_pull_ratio = round(push_sets / pull_sets, 2) if pull_sets > 0 else None

    undertrained = [
        mg for mg, avg in avg_per_week.items()
        if avg < 2.0
        and mg.lower() not in _LEGS_GROUPS
        and mg.lower() != "core"
    ]

    return {
        "sets_by_muscle_group": dict(sets_by_muscle),
        "avg_sets_per_week":    avg_per_week,
        "push_sets":            push_sets,
        "pull_sets":            pull_sets,
        "push_pull_ratio":      push_pull_ratio,
        "undertrained_groups":  undertrained,
    }


def compute_metrics(entries: list[dict], weeks: int) -> dict:
    """Single entry point. Returns combined metrics dict."""
    dates = sorted(e["date"] for e in entries if e.get("date"))
    return {
        "analysis_window": {
            "start": dates[0] if dates else "—",
            "end":   dates[-1] if dates else "—",
            "weeks": weeks,
        },
        "strength_progression": _compute_strength_progression(entries),
        "adherence":            _compute_adherence(entries, weeks),
        "volume_distribution":  _compute_volume_distribution(entries, weeks),
    }
