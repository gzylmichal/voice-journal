"""tests/test_backfill_sessions.py — Unit tests for backfill_sessions.py.

HTTP calls are mocked throughout; no real Notion requests are made.
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backfill_sessions import compute_changes, run_apply, run_dry_run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(page_id: str, date_str: str, exercise: str, session: str) -> dict:
    """Build a minimal Notion page dict matching the Workout DB schema."""
    return {
        "id": page_id,
        "properties": {
            "Exercise":      {"title":     [{"plain_text": exercise}] if exercise else []},
            "Date":          {"date":      {"start": date_str}},
            "Session":       {"select":    {"name": session} if session else None},
            "Muscle Group":  {"select":    None},
            "Sets":          {"number":    None},
            "Reps":          {"number":    None},
            "Weight":        {"rich_text": []},
            "Top Set (kg)":  {"number":    None},
            "RPE":           {"number":    None},
            "Pain note":     {"rich_text": []},
        },
    }


# ---------------------------------------------------------------------------
# Test 1: Day grouping + per-day classification
# ---------------------------------------------------------------------------

def test_day_grouping_chest_applied_to_all_rows():
    """Bench + accessories on one day → Chest applied to every row for that date."""
    pages = [
        _make_page("id-1", "2026-06-10", "Bench Press",           "Other"),
        _make_page("id-2", "2026-06-10", "Bulgarian split squat", "Other"),
        _make_page("id-3", "2026-06-10", "Triceps Pushdown",      "Other"),
        _make_page("id-4", "2026-06-10", "Preacher Curl",         "Other"),
    ]

    changes = compute_changes(pages)

    assert len(changes) == 4, f"Expected 4 changes, got {len(changes)}"
    for page_id, d, exercise_names, current, computed in changes:
        assert computed == "Chest", f"Expected Chest, got {computed!r}"
        assert current == "Other"
        assert d == "2026-06-10"
    assert {c[0] for c in changes} == {"id-1", "id-2", "id-3", "id-4"}


# ---------------------------------------------------------------------------
# Test 2: Idempotency — correct rows produce no changes
# ---------------------------------------------------------------------------

def test_idempotency_already_correct_session_skipped():
    """Rows already labelled with the correct session generate no PATCH candidates."""
    pages = [
        _make_page("id-1", "2026-06-11", "Bench Press",      "Chest"),
        _make_page("id-2", "2026-06-11", "Triceps Pushdown", "Chest"),
        _make_page("id-3", "2026-06-12", "Deadlift",         "Deadlift"),
    ]

    changes = compute_changes(pages)

    assert changes == [], f"Expected no changes, got {changes}"


# ---------------------------------------------------------------------------
# Test 3: Mixed day — only wrong rows appear in changes
# ---------------------------------------------------------------------------

def test_mixed_days_only_differing_rows_returned():
    """Deadlift day already correct + Bench day wrong → only Bench rows returned."""
    pages = [
        _make_page("id-ok-1", "2026-06-13", "Deadlift",    "Deadlift"),  # correct
        _make_page("id-ok-2", "2026-06-13", "Romanian DL", "Deadlift"),  # correct
        _make_page("id-bad",  "2026-06-14", "Bench Press", "Other"),     # wrong
    ]

    changes = compute_changes(pages)

    assert len(changes) == 1
    page_id, d, exercise_names, current, computed = changes[0]
    assert page_id == "id-bad"
    assert computed == "Chest"
    assert current == "Other"


# ---------------------------------------------------------------------------
# Test 4: Dry-run issues zero PATCH calls
# ---------------------------------------------------------------------------

def test_dry_run_issues_no_patch_calls():
    """run_dry_run must not call patch_session regardless of how many changes exist."""
    pages = [
        _make_page("id-1", "2026-06-15", "Bench Press", "Other"),
        _make_page("id-2", "2026-06-15", "Dips",        "Other"),
    ]
    changes = compute_changes(pages)
    assert changes  # sanity: there are changes to report

    with patch("backfill_sessions.patch_session") as mock_patch:
        run_dry_run(changes)

    mock_patch.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5: --apply patches only differing rows, one call per row
# ---------------------------------------------------------------------------

def test_apply_patches_only_differing_rows():
    """run_apply calls patch_session exactly once per changed row with the right args."""
    changes = [
        ("id-a", "2026-06-16", ["Bench Press", "Dips"], "Other", "Chest"),
        ("id-b", "2026-06-16", ["Bench Press", "Dips"], "Arms",  "Chest"),
    ]

    with (
        patch("backfill_sessions.patch_session", return_value=True) as mock_patch,
        patch("time.sleep"),
    ):
        run_apply(changes)

    assert mock_patch.call_count == 2
    mock_patch.assert_any_call("id-a", "Chest")
    mock_patch.assert_any_call("id-b", "Chest")
