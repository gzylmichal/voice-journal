"""Tests for Phase M Step 3: _handle_query — answer + ntfy push."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date
from unittest.mock import patch, MagicMock

import voice_journal


_DATE = date(2026, 6, 14)

_CANNED_HISTORY = {
    "Squat": [
        {"date": "2026-06-07", "sets": 4, "reps": 5, "weight": "100 kg"},
        {"date": "2026-06-10", "sets": 4, "reps": 5, "weight": "105 kg"},
    ]
}

_QUERY = {"detected": True, "question": "What did I squat last time?"}


def test_answer_composed_from_provided_rows():
    """AI is called with the fetched rows; the returned answer is pushed."""
    with patch("voice_journal.fetch_prior_workout_session", return_value=_CANNED_HISTORY), \
         patch("voice_journal.ai_client.call_ai", return_value="Last squat: 105 kg × 5 (2026-06-10)") as mock_ai, \
         patch("voice_journal.send_notification") as mock_push:
        voice_journal._handle_query(_QUERY, _DATE)

    mock_ai.assert_called_once()
    call_args = mock_ai.call_args
    # Rows are in the user message
    assert "Squat" in call_args[0][0]
    assert "105" in call_args[0][0]
    mock_push.assert_called_once_with("Last squat: 105 kg × 5 (2026-06-10)", title="Training history")


def test_no_data_returns_honest_message():
    """When fetch returns empty dict, an honest no-data answer is pushed (no LLM call)."""
    with patch("voice_journal.fetch_prior_workout_session", return_value={}), \
         patch("voice_journal.ai_client.call_ai") as mock_ai, \
         patch("voice_journal.send_notification") as mock_push:
        voice_journal._handle_query(_QUERY, _DATE)

    mock_ai.assert_not_called()
    mock_push.assert_called_once()
    pushed_text = mock_push.call_args[0][0]
    assert "no records" in pushed_text.lower()


def test_llm_failure_no_push():
    """When AI call raises, no notification is sent and no exception escapes."""
    with patch("voice_journal.fetch_prior_workout_session", return_value=_CANNED_HISTORY), \
         patch("voice_journal.ai_client.call_ai", side_effect=RuntimeError("API down")), \
         patch("voice_journal.send_notification") as mock_push:
        voice_journal._handle_query(_QUERY, _DATE)  # must not raise

    mock_push.assert_not_called()


def test_ntfy_failure_does_not_crash():
    """send_notification never raises; _handle_query must also not crash on push failure."""
    with patch("voice_journal.fetch_prior_workout_session", return_value=_CANNED_HISTORY), \
         patch("voice_journal.ai_client.call_ai", return_value="Last squat 105 kg"), \
         patch("voice_journal.send_notification", side_effect=Exception("ntfy down")):
        # send_notification is supposed to never raise, but even if it did _handle_query must survive
        # The iron rule in notify.py means this side_effect exercises defensive intent
        try:
            voice_journal._handle_query(_QUERY, _DATE)
        except Exception:
            raise AssertionError("_handle_query must not let push exceptions escape")


def test_fetch_failure_gives_honest_no_data():
    """When fetch_prior_workout_session raises, honest no-data answer is still pushed."""
    with patch("voice_journal.fetch_prior_workout_session", side_effect=Exception("Notion down")), \
         patch("voice_journal.ai_client.call_ai") as mock_ai, \
         patch("voice_journal.send_notification") as mock_push:
        voice_journal._handle_query(_QUERY, _DATE)

    mock_ai.assert_not_called()
    mock_push.assert_called_once()
    assert "no records" in mock_push.call_args[0][0].lower()
