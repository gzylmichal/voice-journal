"""
Workout collector — fetches last 7 days from the Notion Workout Log DB.

Returns structured data for the Sunday Weekly Review email.
Shares NOTION_API_KEY and NOTION_WORKOUT_DB_ID from cfg.
"""

import logging
import sys
import os as _os
import requests
from datetime import date, datetime, timedelta
from collections import defaultdict

_ANALYTICS_DIR = _os.path.join(_os.path.dirname(__file__), '..', '..')


def _get_detect_prs():
    try:
        from analytics import detect_prs
        return detect_prs
    except ImportError:
        try:
            sys.path.insert(0, _os.path.abspath(_ANALYTICS_DIR))
            from analytics import detect_prs
            return detect_prs
        except ImportError:
            return None

logger = logging.getLogger("debrief.workout")

NOTION_VERSION = "2022-06-28"

KEY_LIFTS = {
    "Bench Press": ["bench"],
    "Deadlift":    ["deadlift"],
    "Squat":       ["squat"],
    "OHP":         ["overhead press", "ohp"],
}


def collect_workout(cfg: dict, weeks: int = 1) -> dict:
    """Fetch workout entries from Notion Workout Log DB. Pass weeks=8 for the weekly review chart."""

    api_key = cfg.get("notion_api_key", "")
    db_id   = cfg.get("notion_workout_db_id", "")

    if not api_key or not db_id:
        return {"configured": False, "entries": [], "sessions": 0}

    since = (date.today() - timedelta(weeks=weeks)).isoformat()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    payload = {
        "filter": {"property": "Date", "date": {"on_or_after": since}},
        "sorts": [{"property": "Date", "direction": "ascending"}],
        "page_size": 200,
    }

    entries = []
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    try:
        while True:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            for page in data.get("results", []):
                entries.append(_parse_entry(page))
            if data.get("has_more"):
                payload["start_cursor"] = data["next_cursor"]
            else:
                break
    except Exception as exc:
        logger.error("Workout fetch failed: %s", exc)
        return {"configured": True, "entries": [], "sessions": 0, "error": str(exc)}

    logger.info("Workout: fetched %d entries", len(entries))

    # Aggregate
    sessions_by_date: dict[str, str] = {}
    key_lift_tops: dict[str, dict[str, float]] = {lift: {} for lift in KEY_LIFTS}

    for e in entries:
        d = e["date"]
        if d:
            sessions_by_date[d] = e.get("session", "")
            # Track top sets for key lifts
            if e.get("top_set_kg"):
                name_lower = e["exercise"].lower()
                for lift, keywords in KEY_LIFTS.items():
                    if any(kw in name_lower for kw in keywords):
                        if d not in key_lift_tops[lift] or e["top_set_kg"] > key_lift_tops[lift][d]:
                            key_lift_tops[lift][d] = e["top_set_kg"]
                        break

    return {
        "configured": True,
        "entries": entries,
        "sessions": len(sessions_by_date),
        "session_dates": sorted(sessions_by_date.keys()),
        "session_types": sessions_by_date,
        "key_lift_tops": key_lift_tops,  # {lift_name: {date: top_kg}}
        "formatted_text": _format_for_ai(entries),
    }


def _parse_entry(page: dict) -> dict:
    props = page.get("properties", {})

    def title(p):
        items = p.get("title", [])
        return items[0]["plain_text"] if items else ""

    def sel(p):
        s = p.get("select")
        return s["name"] if s else ""

    def num(p):
        return p.get("number")

    def rt(p):
        items = p.get("rich_text", [])
        return items[0]["plain_text"] if items else ""

    def dt(p):
        d = p.get("date", {})
        return d.get("start", "") if d else ""

    return {
        "exercise":     title(props.get("Exercise", {})),
        "date":         dt(props.get("Date", {})),
        "session":      sel(props.get("Session", {})),
        "muscle_group": sel(props.get("Muscle Group", {})),
        "sets":         num(props.get("Sets", {})),
        "reps":         num(props.get("Reps", {})),
        "weight":       rt(props.get("Weight", {})),
        "top_set_kg":   num(props.get("Top Set (kg)", {})),
    }


def _format_pr_lines(prs: dict) -> str:
    """Format PR dict (output of detect_prs) into human-readable trophy lines."""
    if not prs:
        return ""

    lines = []
    for exercise in sorted(prs.keys()):
        for pr in prs[exercise]:
            kind = pr.get("kind", "")
            weight_kg = pr.get("weight_kg", 0)
            reps = pr.get("reps", 0)
            if kind == "weight":
                prev = pr.get("prev_best_kg", 0)
                lines.append(f"🏆 PR: {exercise} {weight_kg} kg (prev: {prev} kg)")
            elif kind == "reps":
                prev_reps = pr.get("prev_best_reps", 0)
                lines.append(f"🏆 PR: {exercise} {weight_kg} kg × {reps} reps (prev: {prev_reps} reps)")

    return "\n".join(lines)


def collect_today_workout(cfg: dict) -> dict:
    """
    Fetch today's workout entries (falls back to yesterday if today has none).
    Used in the daily morning debrief.
    """
    api_key = cfg.get("notion_api_key", "")
    db_id   = cfg.get("notion_workout_db_id", "")

    if not api_key or not db_id:
        return {"configured": False, "entries": [], "date": None}

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    for target_date in (today, yesterday):
        payload = {
            "filter": {"property": "Date", "date": {"equals": target_date}},
            "sorts": [{"property": "Exercise", "direction": "ascending"}],
            "page_size": 100,
        }
        try:
            resp = requests.post(
                f"https://api.notion.com/v1/databases/{db_id}/query",
                headers=headers, json=payload, timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            entries = [_parse_entry(p) for p in data.get("results", [])]
            if entries:
                session = entries[0].get("session", "")

                # Detect PRs vs prior history
                prs = {}
                try:
                    detect_prs_fn = _get_detect_prs()
                    if detect_prs_fn is not None:
                        hist_result = collect_workout(cfg, weeks=8)
                        all_entries = hist_result.get("entries", []) + entries
                        prs = detect_prs_fn(all_entries, window_days=2)
                except Exception as exc:
                    logger.warning("PR detection failed (non-fatal): %s", exc)
                    prs = {}

                # Build formatted text with optional PR header
                base_text = _format_for_ai(entries)
                pr_lines = _format_pr_lines(prs)
                if pr_lines:
                    formatted_text = pr_lines + "\n\n" + base_text
                else:
                    formatted_text = base_text

                pr_count = sum(len(v) for v in prs.values())

                return {
                    "configured": True,
                    "entries": entries,
                    "date": target_date,
                    "session": session,
                    "formatted_text": formatted_text,
                    "pr_count": pr_count,
                }
        except Exception as exc:
            logger.error("Today workout fetch failed: %s", exc)
            return {"configured": True, "entries": [], "date": target_date, "error": str(exc)}

    return {"configured": True, "entries": [], "date": today}


def collect_training_suggestion(cfg: dict) -> dict:
    """
    Infer the next workout in the rotation from the last ~14 days of sessions.

    Returns one of:
      {"configured": True, "suggestion": "leg day", "last_date": "Jun 7"}
      {"configured": True, "fallback": {"Chest": 2, "Back": 5, "Legs": 9}}
      {"configured": True}  — empty history, section omitted
      {"configured": False}  — not configured
    """
    api_key = cfg.get("notion_api_key", "")
    db_id   = cfg.get("notion_workout_db_id", "")

    if not api_key or not db_id:
        return {"configured": False}

    try:
        data = collect_workout(cfg, weeks=2)
    except Exception as exc:
        logger.warning("Training suggestion fetch failed (non-fatal): %s", exc)
        return {"configured": True}

    session_types: dict[str, str] = data.get("session_types", {})
    if not session_types:
        return {"configured": True}

    # Build ordered list of (date, session) for the window
    dated = sorted(session_types.items())  # [(date_str, session), ...]
    sessions = [s for _, s in dated if s]

    if not sessions:
        return {"configured": True}

    # Try to detect a repeating cycle (length 2–6)
    suggestion = _infer_next_in_cycle(sessions)
    if suggestion:
        # Find the most recent date for the suggested session
        last_date = ""
        for d, s in reversed(dated):
            if s.lower() == suggestion.lower():
                try:
                    last_date = datetime.fromisoformat(d).strftime("%b %-d")
                except Exception:
                    last_date = d
                break
        return {"configured": True, "suggestion": suggestion, "last_date": last_date}

    # Fallback: days since each split
    return {"configured": True, "fallback": _days_since_each_split(dated)}


def _infer_next_in_cycle(sessions: list) -> "str | None":
    """
    Try cycle lengths 2–6. Return the next predicted session if the tail
    of `sessions` matches a repeating cycle cleanly (≥2 full repeats must fit).
    """
    if len(sessions) < 2:
        return None
    for length in range(2, 7):
        if len(sessions) < length * 2:
            continue
        tail = sessions[-length * 2:]
        first_half  = tail[:length]
        second_half = tail[length:]
        if [s.lower() for s in first_half] == [s.lower() for s in second_half]:
            # The cycle repeats — predict the next session after the tail
            next_idx = len(sessions) % length
            return sessions[-length + next_idx] if next_idx < length else second_half[0]
    return None


def _days_since_each_split(dated: list[tuple[str, str]]) -> dict[str, int]:
    """Return {session_name: days_since_last} for each distinct split."""
    from datetime import date as _date
    today = _date.today()
    last_seen: dict[str, str] = {}
    for d, s in dated:
        if s:
            last_seen[s] = d
    result = {}
    for session, d in last_seen.items():
        try:
            delta = (today - _date.fromisoformat(d)).days
        except Exception:
            delta = 0
        result[session] = delta
    return dict(sorted(result.items(), key=lambda x: x[1]))


def _format_for_ai(entries: list[dict]) -> str:
    """Format entries as text for the AI coaching prompt."""
    if not entries:
        return "No workout data this week."

    by_date: dict[str, dict] = {}
    for e in entries:
        d = e["date"]
        if d not in by_date:
            by_date[d] = {"session": e["session"], "exercises": []}
        by_date[d]["exercises"].append(e)

    lines = [f"Sessions this week: {len(by_date)}", ""]
    for d in sorted(by_date.keys()):
        try:
            day_label = datetime.fromisoformat(d).strftime("%a %d %b")
        except ValueError:
            day_label = d
        lines.append(f"\n{day_label} — {by_date[d]['session']}")
        for ex in by_date[d]["exercises"]:
            sets   = ex["sets"] if ex["sets"] is not None else "?"
            reps   = ex["reps"] if ex["reps"] is not None else "—"
            weight = ex["weight"] or "BW"
            top    = f" ← top: {ex['top_set_kg']} kg" if ex["top_set_kg"] else ""
            lines.append(f"  - {ex['exercise']} [{ex['muscle_group']}]: {sets}×{reps} @ {weight}{top}")

    return "\n".join(lines)


def to_text(data: dict) -> str:
    if not data or not data.get("configured"):
        return "[Workout DB not configured — set NOTION_WORKOUT_DB_ID]"
    if not data.get("entries"):
        return "[No workouts logged this week]"
    return data.get("formatted_text") or _format_for_ai(data.get("entries", []))


# ---------------------------------------------------------------------------
# Session plan collector (Phase N2)
# ---------------------------------------------------------------------------

def _load_analytics():
    """Import build_session_plan and next_split from analytics at project root."""
    try:
        from analytics import build_session_plan, next_split
        return build_session_plan, next_split
    except ImportError:
        try:
            sys.path.insert(0, _os.path.abspath(_ANALYTICS_DIR))
            from analytics import build_session_plan, next_split
            return build_session_plan, next_split
        except ImportError:
            return None, None


def _load_plan_config_fn():
    try:
        from pipeline.plan_config import load_plan_config
        return load_plan_config
    except ImportError:
        try:
            sys.path.insert(0, _os.path.abspath(_ANALYTICS_DIR))
            from pipeline.plan_config import load_plan_config
            return load_plan_config
        except ImportError:
            return None


def collect_session_plan(cfg: dict) -> dict:
    """Build the prescribed session plan for today from workout history + plan config.

    Returns:
        {configured: True, plan_available: True, split: str, plan: list[dict]}
        {configured: True, plan_available: False}   — no config / no history / no split
        {configured: False}                          — Notion not configured
    """
    api_key = cfg.get("notion_api_key", "")
    db_id   = cfg.get("notion_workout_db_id", "")
    if not api_key or not db_id:
        return {"configured": False}

    build_session_plan, next_split_fn = _load_analytics()
    load_plan_config = _load_plan_config_fn()

    if build_session_plan is None or load_plan_config is None:
        logger.warning("session_plan: analytics or plan_config not importable — section omitted")
        return {"configured": True, "plan_available": False}

    plan_cfg = load_plan_config()
    if plan_cfg is None:
        logger.info("session_plan: no plan config — section omitted")
        return {"configured": True, "plan_available": False}

    try:
        history = collect_workout(cfg, weeks=8)
    except Exception as exc:
        logger.warning("session_plan: history fetch failed: %s", exc)
        return {"configured": True, "plan_available": False}

    entries = history.get("entries", [])
    cycle = plan_cfg.get("cycle", [])
    templates = plan_cfg.get("templates", {})

    split = next_split_fn(entries, cycle)
    if not split:
        logger.info("session_plan: could not determine next split")
        return {"configured": True, "plan_available": False}

    template = templates.get(split)
    if not template:
        logger.info("session_plan: no template for split %r", split)
        return {"configured": True, "plan_available": False}

    try:
        plan = build_session_plan(entries, split, template)
    except Exception as exc:
        logger.warning("session_plan: build failed: %s", exc)
        return {"configured": True, "plan_available": False}

    if not plan:
        return {"configured": True, "plan_available": False}

    return {"configured": True, "plan_available": True, "split": split, "plan": plan}


def render_session_plan_text(data: dict) -> str:
    """Compact single-line rendering of a session plan dict."""
    if not data or not data.get("plan_available"):
        return ""
    split = data.get("split", "")
    plan  = data.get("plan", [])
    return _format_plan_line(split, plan)


def _format_plan_line(split: str, plan: list) -> str:
    """'Chest day → Bench 72.5×5 (last 70×5) · Pull-ups BW×9 (last BW×8) · Triceps + Biceps'"""
    main_parts: list = []
    reminder_names: list = []

    for slot in plan:
        if slot.get("reminder"):
            reminder_names.append(slot.get("slot", "?"))
        elif "rec" in slot:
            main_parts.append(_format_slot_with_rec(slot))
        else:
            # too few sessions — last numbers only
            exercise = slot.get("exercise") or slot.get("slot", "?")
            last = slot.get("last_sets_str", "")
            main_parts.append(f"{exercise} (last {last})" if last else exercise)

    parts = main_parts[:]
    if reminder_names:
        parts.append(" + ".join(reminder_names))

    day_label = f"{split} day"
    return (day_label + " → " + " · ".join(parts)) if parts else day_label


def _format_slot_with_rec(slot: dict) -> str:
    rec      = slot["rec"]
    exercise = slot.get("exercise") or slot.get("slot", "?")
    last     = slot.get("last_sets_str", "")
    action   = rec.get("action", "")
    weight_kg    = rec.get("weight_kg")
    target_reps  = rec.get("target_reps")
    note         = rec.get("note", "") or ""

    if action == "no_recommendation":
        return f"{exercise} (last {last})" if last else exercise

    if weight_kg is not None:
        target_str = f"{weight_kg}×{target_reps}" if target_reps else f"{weight_kg} kg"
    elif target_reps is not None:
        # BW exercise — format as BW×target_reps
        target_str = f"BW×{target_reps}"
    else:
        return f"{exercise} (last {last})" if last else exercise

    suffix = f" {note}" if note else ""
    last_part = f" (last {last})" if last else ""
    return f"{exercise} {target_str}{suffix}{last_part}"


def generate_progress_chart(workout_data: dict) -> str:
    """
    Generate a key-lifts progress line chart for the last 8 weeks.
    Returns an HTML <img> tag with base64-encoded PNG, or empty string on failure.

    Requires: matplotlib (pip install matplotlib)
    """
    try:
        import matplotlib
        matplotlib.use("Agg")   # headless — no display needed
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        import base64
        import io
        from datetime import datetime as _dt, timedelta
        from collections import defaultdict
    except ImportError:
        logger.warning("matplotlib not installed — skipping chart. Run: pip install matplotlib")
        return ""

    entries = workout_data.get("entries", [])
    if not entries:
        return ""

    KEY_LIFTS_LOCAL = {
        "Bench Press": (["bench"],                "#7F77DD"),
        "Deadlift":    (["deadlift"],              "#5DCAA5"),
        "Squat":       (["squat"],                 "#EF9F27"),
        "OHP":         (["overhead press", "ohp"], "#ED93B1"),
    }

    # Build week labels for last 8 weeks
    today = _dt.today().date()
    week_starts = [(today - timedelta(weeks=7-i)) for i in range(8)]
    week_starts = [d - timedelta(days=d.weekday()) for d in week_starts]  # align to Monday
    week_labels = [f"W{d.isocalendar()[1]}" for d in week_starts]

    def week_start_for(date_str: str):
        try:
            d = _dt.fromisoformat(date_str).date()
            return d - timedelta(days=d.weekday())
        except Exception:
            return None

    # Collect top set per lift per week
    lift_data = {lift: defaultdict(float) for lift in KEY_LIFTS_LOCAL}
    for e in entries:
        if not e.get("top_set_kg"):
            continue
        ws = week_start_for(e["date"])
        if ws not in week_starts:
            continue
        name_lower = e["exercise"].lower()
        for lift, (keywords, _) in KEY_LIFTS_LOCAL.items():
            if any(kw in name_lower for kw in keywords):
                if e["top_set_kg"] > lift_data[lift][ws]:
                    lift_data[lift][ws] = e["top_set_kg"]
                break

    # Plot
    fig, ax = plt.subplots(figsize=(6, 2.4))
    fig.patch.set_facecolor("#16162a")
    ax.set_facecolor("#16162a")

    has_data = False
    for lift, (_, color) in KEY_LIFTS_LOCAL.items():
        y = [lift_data[lift].get(ws, None) for ws in week_starts]
        # Only plot if at least 1 data point
        if any(v is not None for v in y):
            has_data = True
            # Fill gaps with None so line breaks naturally
            ax.plot(week_labels, y, marker="o", markersize=4,
                    linewidth=1.8, color=color, label=lift, zorder=3)

    if not has_data:
        plt.close(fig)
        return ""

    ax.tick_params(colors="#888888", labelsize=9)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%g"))
    for spine in ax.spines.values():
        spine.set_edgecolor("#2a2a3e")
    ax.grid(axis="y", color="#2a2a3e", linewidth=0.8)
    ax.legend(loc="upper left", fontsize=9, framealpha=0,
              labelcolor="#aaaacc", ncol=4, handlelength=1.2)

    plt.tight_layout(pad=0.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    return f'<img src="data:image/png;base64,{encoded}" alt="Key lifts progress" style="width:100%;max-width:560px;display:block;margin:10px 0;" />'
