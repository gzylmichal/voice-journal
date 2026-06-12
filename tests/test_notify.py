import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import MagicMock, patch

import requests
import pytest

from pipeline.notify import send_notification


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
