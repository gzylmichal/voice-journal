#!/usr/bin/env python3
"""
analytics.py — Deterministic metrics for the weekly coaching report.
Pure functions only: no I/O, no API calls, no side effects.

Public interface:
    compute_metrics(entries, weeks) -> dict
"""

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
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


_LOWER_BODY_KEYWORDS = ("squat", "leg press", "rdl", "romanian", "deadlift", "hip thrust")


def _is_lower_body(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in _LOWER_BODY_KEYWORDS)


def _round_to_plate(kg: float) -> float:
    return round(kg / 2.5) * 2.5


def _detect_bw(weight_str: str) -> tuple[bool, float]:
    """Return (is_bodyweight, added_kg). Parses 'BW' and 'BW + 10kg' formats."""
    s = (weight_str or "").strip().upper()
    if not s.startswith("BW"):
        return False, 0.0
    if "+" in s:
        try:
            added = float(s.split("+", 1)[1].replace("KG", "").replace("G", "").strip())
        except ValueError:
            added = 0.0
        return True, added
    return True, 0.0


def recommend_progression(history: list[dict]) -> dict:
    """Pure function: list of Notion workout rows for ONE exercise → recommendation.

    Each row must have at least: date (ISO str), weight (sets str), exercise (name).
    Optional fields checked with key-presence guard: rpe, pain_note.

    Return dict keys:
        action          "progress" | "repeat" | "no_recommendation"
        weight_kg       float | None  (target weight; for loaded BW: added kg)
        target_reps     int | None    (target reps for each set)
        note            str | None    (e.g. pain note, gap note)
        last_sets_str   str           (formatted last-session string for display)
        last_date       str
    """
    _no_rec = lambda sets_str="", last_date_="", note=None: {  # noqa: E731
        "action": "no_recommendation", "weight_kg": None,
        "target_reps": None, "note": note,
        "last_sets_str": sets_str, "last_date": last_date_,
    }

    if not history:
        return _no_rec()

    sorted_hist = sorted(history, key=lambda r: r.get("date") or "")
    last = sorted_hist[-1]
    last_date = last.get("date") or ""
    last_weight_str = (last.get("weight") or "").strip()
    exercise_name = last.get("exercise") or ""

    # Fewer than 2 sessions → no recommendation
    if len(sorted_hist) < 2:
        return _no_rec(sets_str=last_weight_str, last_date_=last_date)

    # Gap > 14 days → repeat last weights
    gap_days = 0
    try:
        gap_days = (date.today() - datetime.fromisoformat(last_date).date()).days
    except (ValueError, TypeError):
        pass
    if gap_days > 14:
        return {
            "action": "repeat", "weight_kg": None, "target_reps": None,
            "note": f"({gap_days}d gap — repeat last)",
            "last_sets_str": last_weight_str, "last_date": last_date,
        }

    # Pain note → no progression (check key presence — field doesn't exist yet in Phase H)
    if "pain_note" in last and last.get("pain_note"):
        return {
            "action": "repeat", "weight_kg": None, "target_reps": None,
            "note": f"(take it easy — {last['pain_note']})",
            "last_sets_str": last_weight_str, "last_date": last_date,
        }

    last_rpe = last.get("rpe") if "rpe" in last else None

    # Bodyweight exercise detection
    is_bw, bw_added = _detect_bw(last_weight_str)
    if is_bw:
        # Reps from the Reps column (BW sets don't encode reps in weight string)
        last_reps = int(last.get("reps") or 0)
        if last_rpe is not None and last_rpe >= 9:
            return {
                "action": "repeat", "weight_kg": bw_added or None, "target_reps": last_reps,
                "note": "RPE ≥ 9 — repeat",
                "last_sets_str": last_weight_str, "last_date": last_date,
            }
        if bw_added:
            new_added = _round_to_plate(bw_added + 2.5)
            return {
                "action": "progress", "weight_kg": new_added, "target_reps": last_reps,
                "note": None, "last_sets_str": last_weight_str, "last_date": last_date,
            }
        # Pure BW → +1 rep
        return {
            "action": "progress", "weight_kg": None, "target_reps": last_reps + 1,
            "note": None, "last_sets_str": last_weight_str, "last_date": last_date,
        }

    # Standard weighted exercise
    last_sets = parse_sets_string(last_weight_str)
    valid_last = [(w, r) for w, r in last_sets if w > 0 and r > 0]
    if not valid_last:
        return _no_rec(sets_str=last_weight_str, last_date_=last_date)

    # Working weight = most frequent weight in last session
    working_weight = Counter(w for w, r in valid_last).most_common(1)[0][0]
    reps_at_working = [r for w, r in valid_last if w == working_weight]

    # Usual top rep range = max reps seen across last 5 sessions at any weight
    usual_top = 0
    for row in sorted_hist[-5:]:
        row_sets = parse_sets_string(row.get("weight") or "")
        row_valid_reps = [r for w, r in row_sets if w > 0 and r > 0]
        if row_valid_reps:
            usual_top = max(usual_top, max(row_valid_reps))

    if usual_top == 0:
        usual_top = max(reps_at_working) if reps_at_working else 0

    all_hit_top = bool(reps_at_working) and all(r >= usual_top for r in reps_at_working)

    # RPE overrides
    if last_rpe is not None and last_rpe >= 9:
        return {
            "action": "repeat", "weight_kg": working_weight,
            "target_reps": max(reps_at_working),
            "note": "RPE ≥ 9 — repeat",
            "last_sets_str": last_weight_str, "last_date": last_date,
        }

    if all_hit_top or (last_rpe is not None and last_rpe <= 7):
        increment = 5.0 if _is_lower_body(exercise_name) else 2.5
        new_weight = _round_to_plate(working_weight + increment)
        return {
            "action": "progress", "weight_kg": new_weight,
            "target_reps": usual_top,
            "note": None, "last_sets_str": last_weight_str, "last_date": last_date,
        }

    # Reps not fully reached → same weight, target +1 on weakest set
    weakest = min(reps_at_working)
    return {
        "action": "repeat", "weight_kg": working_weight,
        "target_reps": weakest + 1,
        "note": None, "last_sets_str": last_weight_str, "last_date": last_date,
    }


def detect_prs(entries: list[dict], window_days: int) -> dict:
    """Detect weight-PRs and rep-PRs within the last window_days days.

    Args:
        entries: list of workout entry dicts with keys: exercise, date (ISO str),
                 weight (sets string), top_set_kg, sets, reps, muscle_group, session.
        window_days: only entries within the last window_days days are PR candidates;
                     ALL entries serve as the historical baseline.

    Returns:
        dict keyed by exercise name. Each value is a list of PR dicts:
          weight-PR: {kind, date, weight_kg, reps, prev_best_kg}
          rep-PR:    {kind, date, weight_kg, reps, prev_best_reps}
    """
    if not entries:
        return {}

    # Determine cutoff date for the window
    today = date.today()
    cutoff = today - timedelta(days=window_days)

    # Parse all entries: collect (date_obj, sets) per exercise
    # sorted ascending by date so we can build a rolling baseline
    by_exercise: dict[str, list] = defaultdict(list)
    for e in entries:
        exercise = e.get("exercise", "")
        if not exercise:
            continue
        date_str = e.get("date", "")
        try:
            date_obj = datetime.fromisoformat(date_str).date()
        except (ValueError, TypeError):
            continue
        sets = parse_sets_string(e.get("weight", ""))
        if not sets:
            continue
        by_exercise[exercise].append((date_obj, date_str, sets))

    result: dict[str, list[dict]] = {}

    for exercise, sessions in by_exercise.items():
        # Sort by date ascending
        sessions_sorted = sorted(sessions, key=lambda t: t[0])

        prs: list[dict] = []

        for date_obj, date_str, sets in sessions_sorted:
            # Only PR-candidate if within the window
            if date_obj < cutoff:
                continue

            # Build baseline from ALL entries BEFORE this date
            prior_sessions = [s for s in sessions_sorted if s[0] < date_obj]

            # First-ever entry for this exercise → not a PR
            if not prior_sessions:
                continue

            # --- Weight PR check ---
            valid_sets = [(w, r) for w, r in sets if w > 0 and r > 0]
            if not valid_sets:
                continue

            max_weight = max(w for w, r in valid_sets)

            # Prior best weight across all prior sessions
            prior_best_kg: float = 0.0
            for _, _, prior_sets in prior_sessions:
                for w, r in prior_sets:
                    if w > prior_best_kg:
                        prior_best_kg = w

            if max_weight > prior_best_kg:
                # Find reps at max weight in this session
                reps_at_max = max(
                    (r for w, r in valid_sets if w == max_weight),
                    default=0,
                )
                prs.append({
                    "kind": "weight",
                    "date": date_str,
                    "weight_kg": max_weight,
                    "reps": reps_at_max,
                    "prev_best_kg": prior_best_kg,
                })
                # Skip rep-PR check for this session — weight PR takes precedence
                continue

            # --- Rep PR check ---
            # For each (weight, reps) pair, check if reps > max(reps at weight >= this_weight in prior)
            for w, r in valid_sets:
                # Max reps seen in prior sessions at any weight >= w
                prior_best_reps = 0
                for _, _, prior_sets in prior_sessions:
                    for pw, pr in prior_sets:
                        if pw >= w and pr > prior_best_reps:
                            prior_best_reps = pr

                if prior_best_reps > 0 and r > prior_best_reps:
                    prs.append({
                        "kind": "reps",
                        "date": date_str,
                        "weight_kg": w,
                        "reps": r,
                        "prev_best_reps": prior_best_reps,
                    })
                    break  # one rep-PR per session per exercise is enough

        if prs:
            result[exercise] = prs

    return result


_BODY_PART_KEYWORDS: dict[str, list[str]] = {
    "knee":     ["knee", "kolano", "knees", "patella"],
    "shoulder": ["shoulder", "bark", "shoulders", "rotator"],
    "wrist":    ["wrist", "nadgarstek", "wrists"],
    "elbow":    ["elbow", "łokieć"],
    "back":     ["back", "kręgosłup", "plecy", "lower back", "spine"],
    "hip":      ["hip", "biodro", "hips"],
    "ankle":    ["ankle", "kostka"],
    "neck":     ["neck", "szyja", "kark"],
}


def _extract_body_part(pain_note: str) -> Optional[str]:
    note_lower = pain_note.lower()
    for part, keywords in _BODY_PART_KEYWORDS.items():
        if any(kw in note_lower for kw in keywords):
            return part
    return None


def _compute_rpe_signals(entries: list[dict], strength_progression: dict) -> dict:
    """Compute RPE trends and pain pattern signals from workout entries.

    No-ops cleanly when no entries carry rpe or pain_note (older data).
    Returns:
        avg_rpe_by_exercise:  {exercise: {iso_week: avg_rpe}}
        fatigue_flags:        list of {lift, reason} — e1RM flat + RPE rising
        pain_patterns:        list of {body_part, occurrences} — ≥2 occurrences
    """
    rpe_by_ex_week: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    pain_counts: dict[str, int] = defaultdict(int)

    for entry in entries:
        rpe = entry.get("rpe")
        exercise = entry.get("exercise", "")
        date_str = entry.get("date", "")
        pain = entry.get("pain_note")

        if rpe is not None:
            week = _iso_week(date_str)
            rpe_by_ex_week[exercise][week].append(float(rpe))

        if pain:
            part = _extract_body_part(pain)
            if part:
                pain_counts[part] += 1

    avg_rpe: dict[str, dict[str, float]] = {
        ex: {
            week: round(sum(rlist) / len(rlist), 1)
            for week, rlist in week_data.items()
        }
        for ex, week_data in rpe_by_ex_week.items()
    }

    # Fatigue flags: benchmark lift where e1RM is flat/stable AND RPE is rising
    fatigue_flags: list[dict] = []
    for lift_key in ("bench", "deadlift", "squat"):
        sp = strength_progression.get(lift_key, {})
        if sp.get("insufficient_data"):
            continue
        if sp.get("trend") == "improving":
            continue  # rising e1RM → not a fatigue signal

        # Collect RPE values for all exercises matching this lift, sorted by date
        lift_entries_with_rpe = sorted(
            [
                (e.get("date", ""), e.get("rpe"))
                for e in entries
                if identify_benchmark(e.get("exercise", "")) == lift_key
                and e.get("rpe") is not None
            ],
            key=lambda t: t[0],
        )
        if len(lift_entries_with_rpe) < 2:
            continue
        rpe_series = [r for _, r in lift_entries_with_rpe]
        rpe_slope = linear_slope(rpe_series)
        if rpe_slope > 0:
            fatigue_flags.append({
                "lift": lift_key,
                "reason": (
                    f"e1RM {sp['trend']} (plateau_risk={sp['plateau_risk']}) "
                    f"while RPE rising (+{rpe_slope:.1f}/session)"
                ),
            })

    pain_patterns = [
        {"body_part": part, "occurrences": count}
        for part, count in sorted(pain_counts.items())
        if count >= 2
    ]

    return {
        "avg_rpe_by_exercise": avg_rpe,
        "fatigue_flags":       fatigue_flags,
        "pain_patterns":       pain_patterns,
    }


def compute_metrics(entries: list[dict], weeks: int) -> dict:
    """Single entry point. Returns combined metrics dict."""
    dates = sorted(e["date"] for e in entries if e.get("date"))
    strength = _compute_strength_progression(entries)
    return {
        "analysis_window": {
            "start": dates[0] if dates else "—",
            "end":   dates[-1] if dates else "—",
            "weeks": weeks,
        },
        "strength_progression": strength,
        "adherence":            _compute_adherence(entries, weeks),
        "volume_distribution":  _compute_volume_distribution(entries, weeks),
        "rpe_signals":          _compute_rpe_signals(entries, strength),
    }
