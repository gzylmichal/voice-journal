"""Tests for store_daily_metrics and the sleep/energy pre-filter (Phase J Step 2)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


_DATE = date(2026, 6, 14)


# ---------------------------------------------------------------------------
# store_daily_metrics — writer skips when DB id empty
# ---------------------------------------------------------------------------

def test_store_daily_metrics_skips_when_no_db_id():
    with patch("pipeline.notion_client.NOTION_METRICS_DB_ID", ""), \
         patch("pipeline.notion_client.NOTION_TOKEN", "secret"), \
         patch("requests.post") as mock_post:
        from pipeline.notion_client import store_daily_metrics
        result = store_daily_metrics({"sleep": "good", "energy": "high", "note": None}, _DATE)
    assert result is False
    mock_post.assert_not_called()


def test_store_daily_metrics_skips_when_no_token():
    with patch("pipeline.notion_client.NOTION_METRICS_DB_ID", "db123"), \
         patch("pipeline.notion_client.NOTION_TOKEN", ""), \
         patch("requests.post") as mock_post:
        from pipeline.notion_client import store_daily_metrics
        result = store_daily_metrics({"sleep": "good", "energy": "high", "note": None}, _DATE)
    assert result is False
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# store_daily_metrics — omits null fields
# ---------------------------------------------------------------------------

def test_store_daily_metrics_omits_null_sleep():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("pipeline.notion_client.NOTION_METRICS_DB_ID", "db123"), \
         patch("pipeline.notion_client.NOTION_TOKEN", "secret"), \
         patch("requests.post", return_value=mock_resp) as mock_post:
        from pipeline.notion_client import store_daily_metrics
        store_daily_metrics({"sleep": None, "energy": "low", "note": None}, _DATE)
    payload = mock_post.call_args[1]["json"]
    assert "Sleep" not in payload["properties"]
    assert "Energy" in payload["properties"]
    assert payload["properties"]["Energy"]["select"]["name"] == "low"


def test_store_daily_metrics_omits_null_energy():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("pipeline.notion_client.NOTION_METRICS_DB_ID", "db123"), \
         patch("pipeline.notion_client.NOTION_TOKEN", "secret"), \
         patch("requests.post", return_value=mock_resp) as mock_post:
        from pipeline.notion_client import store_daily_metrics
        store_daily_metrics({"sleep": "bad", "energy": None, "note": None}, _DATE)
    payload = mock_post.call_args[1]["json"]
    assert "Energy" not in payload["properties"]
    assert "Sleep" in payload["properties"]
    assert payload["properties"]["Sleep"]["select"]["name"] == "bad"


def test_store_daily_metrics_sets_name_to_iso_date():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("pipeline.notion_client.NOTION_METRICS_DB_ID", "db123"), \
         patch("pipeline.notion_client.NOTION_TOKEN", "secret"), \
         patch("requests.post", return_value=mock_resp) as mock_post:
        from pipeline.notion_client import store_daily_metrics
        store_daily_metrics({"sleep": "ok", "energy": "normal", "note": None}, _DATE)
    payload = mock_post.call_args[1]["json"]
    name_content = payload["properties"]["Name"]["title"][0]["text"]["content"]
    assert name_content == _DATE.isoformat()


def test_store_daily_metrics_includes_note_when_present():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("pipeline.notion_client.NOTION_METRICS_DB_ID", "db123"), \
         patch("pipeline.notion_client.NOTION_TOKEN", "secret"), \
         patch("requests.post", return_value=mock_resp) as mock_post:
        from pipeline.notion_client import store_daily_metrics
        store_daily_metrics({"sleep": "bad", "energy": "low", "note": "rough night"}, _DATE)
    payload = mock_post.call_args[1]["json"]
    assert "Note" in payload["properties"]
    assert payload["properties"]["Note"]["rich_text"][0]["text"]["content"] == "rough night"


def test_store_daily_metrics_returns_true_on_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("pipeline.notion_client.NOTION_METRICS_DB_ID", "db123"), \
         patch("pipeline.notion_client.NOTION_TOKEN", "secret"), \
         patch("requests.post", return_value=mock_resp):
        from pipeline.notion_client import store_daily_metrics
        result = store_daily_metrics({"sleep": "good", "energy": "high", "note": None}, _DATE)
    assert result is True


def test_store_daily_metrics_returns_false_on_api_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "Bad request"
    with patch("pipeline.notion_client.NOTION_METRICS_DB_ID", "db123"), \
         patch("pipeline.notion_client.NOTION_TOKEN", "secret"), \
         patch("requests.post", return_value=mock_resp):
        from pipeline.notion_client import store_daily_metrics
        result = store_daily_metrics({"sleep": "good", "energy": "high", "note": None}, _DATE)
    assert result is False


# ---------------------------------------------------------------------------
# Pre-filter: PL + EN coverage
# ---------------------------------------------------------------------------

def test_prefilter_passes_english_sleep_cue():
    from pipeline.extractors import SLEEP_ENERGY_PHRASES
    assert any("slept" in p for p in SLEEP_ENERGY_PHRASES)


def test_prefilter_passes_polish_sleep_cue():
    from pipeline.extractors import SLEEP_ENERGY_PHRASES
    assert any("spałem" in p for p in SLEEP_ENERGY_PHRASES)


def test_prefilter_covers_padniety():
    from pipeline.extractors import SLEEP_ENERGY_PHRASES
    assert any("padnięty" in p for p in SLEEP_ENERGY_PHRASES)


def test_prefilter_covers_pelen_energii():
    from pipeline.extractors import SLEEP_ENERGY_PHRASES
    assert any("pełen energii" in p for p in SLEEP_ENERGY_PHRASES)
