import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import MagicMock, patch

import requests
import pytest

from pipeline.notify import send_notification, send_batch_summary


def test_sends_to_correct_url():
    """send_notification POSTs to NTFY_SERVER/NTFY_TOPIC."""
    with patch("pipeline.config.NTFY_TOPIC", "test-topic"), \
         patch("pipeline.config.NTFY_SERVER", "https://ntfy.example.com"), \
         patch("pipeline.notify.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        result = send_notification("hello", title="Test", priority="default")
    assert result is True
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert url == "https://ntfy.example.com/test-topic"


def test_disabled_when_topic_empty():
    """send_notification returns False immediately when NTFY_TOPIC is empty."""
    with patch("pipeline.config.NTFY_TOPIC", ""), \
         patch("pipeline.notify.requests.post") as mock_post:
        result = send_notification("hello")
    assert result is False
    mock_post.assert_not_called()


def test_requests_exception_returns_false_no_raise():
    """A requests exception must not propagate — returns False."""
    with patch("pipeline.config.NTFY_TOPIC", "test-topic"), \
         patch("pipeline.config.NTFY_SERVER", "https://ntfy.example.com"), \
         patch("pipeline.notify.requests.post",
               side_effect=requests.exceptions.ConnectionError("no network")):
        result = send_notification("hello")  # must not raise
    assert result is False


def test_timeout_is_set():
    """The HTTP call must include a 10-second timeout."""
    with patch("pipeline.config.NTFY_TOPIC", "test-topic"), \
         patch("pipeline.config.NTFY_SERVER", "https://ntfy.example.com"), \
         patch("pipeline.notify.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        send_notification("hello")
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs.get("timeout") == 10


def test_non_2xx_response_returns_false():
    """A 5xx response returns False (server error)."""
    with patch("pipeline.config.NTFY_TOPIC", "test-topic"), \
         patch("pipeline.config.NTFY_SERVER", "https://ntfy.example.com"), \
         patch("pipeline.notify.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=500)
        result = send_notification("hello")
    assert result is False


# ---------------------------------------------------------------------------
# send_batch_summary tests
# ---------------------------------------------------------------------------

WORKOUT_FIXTURE = {
    "detected": True,
    "workout_name": "Push",
    "exercises": [
        {
            "name": "Bench Press",
            "sets_detail": [
                {"weight": "80 kg", "reps": 8},
                {"weight": "80 kg", "reps": 8},
                {"weight": "82.5 kg", "reps": 6},
            ],
        }
    ],
}


def test_batch_summary_workout_only_formats_correctly():
    """Workout-only batch produces a message containing exercise name and sets."""
    with patch("pipeline.notify.send_notification") as mock_send:
        send_batch_summary(
            WORKOUT_FIXTURE, [], [], {}, [{"text": "bench press memo"}]
        )
    mock_send.assert_called_once()
    message = mock_send.call_args[0][0]
    assert "Bench Press" in message
    assert "80x8" in message
    assert "Workout DB" in message


def test_batch_summary_bw_rejected_shows_correct_message():
    """Rejected bodyweight produces 'BW rejected: X kg vs last Y kg'."""
    with patch("pipeline.notify.send_notification") as mock_send:
        send_batch_summary(
            {}, [], [], {}, [],
            bw_rejected={"value": 95, "last": 82},
        )
    mock_send.assert_called_once()
    message = mock_send.call_args[0][0]
    assert "BW rejected: 95 kg vs last 82 kg" in message


def test_batch_summary_empty_batch_does_not_send():
    """Empty batch (no workout, tasks, events, bodyweight) sends nothing."""
    with patch("pipeline.notify.send_notification") as mock_send:
        send_batch_summary({}, [], [], {}, [])
    mock_send.assert_not_called()


def test_batch_summary_send_notification_exception_does_not_propagate():
    """An exception raised inside send_notification must not escape send_batch_summary."""
    with patch("pipeline.notify.send_notification", side_effect=RuntimeError("boom")):
        # Must not raise
        send_batch_summary(
            WORKOUT_FIXTURE, [], [], {}, [{"text": "test"}]
        )
