"""tests/test_brief.py — Unit tests for pipeline/brief.py."""

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from pipeline.brief import send_preworkout_brief, _is_first_workout_batch


TODAY = date(2026, 6, 14)


def _workout(detected=True, name="Push", exercises=None):
    if exercises is None:
        exercises = [
            {
                "name": "Bench Press",
                "sets": 3,
                "sets_detail": [
                    {"weight": "80 kg", "reps": 8},
                    {"weight": "80 kg", "reps": 8},
                    {"weight": "80 kg", "reps": 7},
                ],
            }
        ]
    return {"detected": detected, "workout_name": name, "exercises": exercises}


def _pending_write(workout_detected=True):
    return {"workout": {"detected": workout_detected}, "tasks": [], "events": []}


# ---------------------------------------------------------------------------
# _is_first_workout_batch
# ---------------------------------------------------------------------------

def test_first_batch_empty_pending():
    assert _is_first_workout_batch([]) is True

def test_first_batch_no_previous_workout():
    assert _is_first_workout_batch([_pending_write(workout_detected=False)]) is True

def test_not_first_batch_when_previous_workout():
    assert _is_first_workout_batch([_pending_write(workout_detected=True)]) is False


# ---------------------------------------------------------------------------
# send_preworkout_brief trigger conditions
# ---------------------------------------------------------------------------

def test_first_workout_batch_sends():
    """First workout batch of the day → notification sent."""
    with (
        patch("pipeline.brief.fetch_prior_workout_session", return_value={}),
        patch("pipeline.brief.send_notification") as mock_send,
    ):
        send_preworkout_brief(_workout(), TODAY, pending_writes=[])
    mock_send.assert_called_once()


def test_second_batch_same_day_no_send():
    """Second workout batch today → brief suppressed."""
    with (
        patch("pipeline.brief.fetch_prior_workout_session", return_value={}),
        patch("pipeline.brief.send_notification") as mock_send,
    ):
        send_preworkout_brief(
            _workout(), TODAY,
            pending_writes=[_pending_write(workout_detected=True)],
        )
    mock_send.assert_not_called()


def test_non_workout_batch_no_send():
    """Batch without detected workout → no brief."""
    with (
        patch("pipeline.brief.fetch_prior_workout_session", return_value={}),
        patch("pipeline.brief.send_notification") as mock_send,
    ):
        send_preworkout_brief({"detected": False, "exercises": []}, TODAY, pending_writes=[])
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Message formatting from canned Notion history
# ---------------------------------------------------------------------------

def test_message_contains_session_name():
    history = {
        "Bench Press": [
            {
                "exercise": "Bench Press", "date": "2026-06-07",
                "weight": "80x8, 80x8, 80x8",
            },
            {
                "exercise": "Bench Press", "date": "2026-06-14",
                "weight": "80x8, 80x8, 80x8",
            },
        ]
    }
    with (
        patch("pipeline.brief.fetch_prior_workout_session", return_value=history),
        patch("pipeline.brief.send_notification") as mock_send,
    ):
        send_preworkout_brief(_workout(name="Chest day"), TODAY, pending_writes=[])
    msg = mock_send.call_args[0][0]
    assert "Chest day" in msg


def test_message_contains_exercise_last_sets():
    history = {
        "Bench Press": [
            {"exercise": "Bench Press", "date": "2026-06-07", "weight": "77.5x8, 77.5x8"},
            {"exercise": "Bench Press", "date": "2026-06-14", "weight": "77.5x8, 77.5x8"},
        ]
    }
    with (
        patch("pipeline.brief.fetch_prior_workout_session", return_value=history),
        patch("pipeline.brief.send_notification") as mock_send,
    ):
        send_preworkout_brief(_workout(), TODAY, pending_writes=[])
    msg = mock_send.call_args[0][0]
    assert "77.5" in msg


def test_exercise_overlap_matching():
    """history_by_exercise keyed exactly as exercise name → rec built from that history."""
    history = {
        "Bench Press": [
            {"exercise": "Bench Press", "date": "2026-05-31", "weight": "80x8, 80x8, 80x8"},
            {"exercise": "Bench Press", "date": "2026-06-07", "weight": "80x8, 80x8, 80x8"},
            {"exercise": "Bench Press", "date": "2026-06-14", "weight": "80x8, 80x8, 80x8"},
        ]
    }
    with (
        patch("pipeline.brief.fetch_prior_workout_session", return_value=history),
        patch("pipeline.brief.send_notification") as mock_send,
    ):
        send_preworkout_brief(_workout(), TODAY, pending_writes=[])
    msg = mock_send.call_args[0][0]
    # All reps hit → should recommend weight progression (+2.5 → 82.5)
    assert "82.5" in msg


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

def test_notion_fetch_failure_no_send_no_crash():
    """Notion fetch exception → no brief sent, no crash."""
    with (
        patch(
            "pipeline.brief.fetch_prior_workout_session",
            side_effect=Exception("network"),
        ),
        patch("pipeline.brief.send_notification") as mock_send,
    ):
        # Should not raise
        send_preworkout_brief(_workout(), TODAY, pending_writes=[])
    mock_send.assert_not_called()


def test_exception_in_brief_never_propagates():
    """Any internal error must be caught — caller must not see an exception."""
    with patch("pipeline.brief.fetch_prior_workout_session", side_effect=RuntimeError("boom")):
        # Must not raise
        send_preworkout_brief(_workout(), TODAY, pending_writes=[])
