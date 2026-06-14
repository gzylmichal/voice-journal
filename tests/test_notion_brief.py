"""tests/test_notion_brief.py — Unit tests for fetch_prior_workout_session."""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pipeline.notion_client import fetch_prior_workout_session


def _page(exercise: str, date_str: str) -> dict:
    """Build a minimal Notion page dict for a workout entry."""
    return {
        "properties": {
            "Exercise": {"title": [{"plain_text": exercise}]},
            "Date": {"date": {"start": date_str}},
            "Session": {"select": None},
            "Muscle Group": {"select": None},
            "Sets": {"number": 3},
            "Reps": {"number": 8},
            "Weight": {"rich_text": [{"plain_text": "80x8, 80x8, 80x8"}]},
            "Top Set (kg)": {"number": 80.0},
        }
    }


def _mock_notion_response(pages: list, has_more: bool = False):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": pages, "has_more": has_more}
    return mock_resp


TODAY = date(2026, 6, 14)
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
WEEK_AGO = (TODAY - timedelta(days=7)).isoformat()
TWO_WEEKS_AGO = (TODAY - timedelta(days=14)).isoformat()


FAKE_TOKEN = "secret_test"
FAKE_DB = "db-test-id"


def _with_config(fn):
    """Decorator: patch NOTION_TOKEN + NOTION_WORKOUT_DB_ID to non-empty values."""
    def wrapper(*args, **kwargs):
        with (
            patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
            patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        ):
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


def test_overlap_picks_matching_session():
    """When prior sessions include today's exercises, returns history keyed by exercise."""
    pages = [
        _page("Bench Press", YESTERDAY),
        _page("OHP", YESTERDAY),
        _page("Squat", WEEK_AGO),
    ]
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post") as mock_post,
    ):
        mock_post.return_value = _mock_notion_response(pages)
        result = fetch_prior_workout_session(["Bench Press", "OHP"], TODAY)

    assert "Bench Press" in result
    assert "OHP" in result
    assert "Squat" in result  # all history returned, not just overlap date


def test_no_overlap_falls_back_to_most_recent():
    """When no exercises overlap, returns history from the most recent day."""
    pages = [
        _page("Squat", YESTERDAY),
        _page("Leg Press", YESTERDAY),
    ]
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post") as mock_post,
    ):
        mock_post.return_value = _mock_notion_response(pages)
        result = fetch_prior_workout_session(["Bench Press"], TODAY)

    assert "Squat" in result
    assert "Leg Press" in result


def test_fetch_failure_returns_empty_no_crash():
    """API error → empty dict, no exception raised."""
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post", side_effect=Exception("network error")),
    ):
        result = fetch_prior_workout_session(["Bench Press"], TODAY)
    assert result == {}


def test_missing_config_returns_empty(monkeypatch):
    """Missing NOTION_WORKOUT_DB_ID → empty dict immediately, no network call."""
    monkeypatch.setattr("pipeline.notion_client.NOTION_WORKOUT_DB_ID", "")
    with patch("pipeline.notion_client.requests.post") as mock_post:
        result = fetch_prior_workout_session(["Bench Press"], TODAY)
    mock_post.assert_not_called()
    assert result == {}


def test_empty_notion_result_returns_empty():
    """Notion returns zero pages → empty dict."""
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post") as mock_post,
    ):
        mock_post.return_value = _mock_notion_response([])
        result = fetch_prior_workout_session(["Bench Press"], TODAY)
    assert result == {}
