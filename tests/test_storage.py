"""Tests for the extended buffer storage layer."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.storage import append_to_buffer, load_buffer, mark_written, get_buffer_path


TEST_DATE = date(2026, 5, 19)

TRANSCRIPT = {"file": "memo_001.m4a", "time": "14:32:00", "text": "Did bench press."}


@pytest.fixture(autouse=True)
def tmp_buffer(tmp_path, monkeypatch):
    """Redirect BUFFER_DIR to a temp directory for each test."""
    import pipeline.storage as storage_mod
    monkeypatch.setattr(storage_mod, "BUFFER_DIR", tmp_path)
    return tmp_path


def test_load_buffer_returns_empty_when_no_file():
    transcripts, pending = load_buffer(TEST_DATE)
    assert transcripts == []
    assert pending == []


def test_load_buffer_backward_compat_flat_array(tmp_path):
    """Old-format buffer (flat list) is read as (list, [])."""
    import pipeline.storage as storage_mod
    path = tmp_path / "2026-05-19.json"
    path.write_text(json.dumps([TRANSCRIPT]))
    transcripts, pending = load_buffer(TEST_DATE)
    assert transcripts == [TRANSCRIPT]
    assert pending == []


def test_append_to_buffer_without_extracted_returns_none():
    batch_id = append_to_buffer([TRANSCRIPT], TEST_DATE)
    assert batch_id is None


def test_append_to_buffer_without_extracted_no_pending_writes():
    append_to_buffer([TRANSCRIPT], TEST_DATE)
    transcripts, pending = load_buffer(TEST_DATE)
    assert transcripts == [TRANSCRIPT]
    assert pending == []


def test_append_to_buffer_with_extracted_returns_batch_id():
    extracted = {"workout": {"detected": False}, "tasks": [], "events": []}
    batch_id = append_to_buffer([TRANSCRIPT], TEST_DATE, extracted=extracted)
    assert batch_id is not None
    assert isinstance(batch_id, str)
    assert "T" in batch_id  # ISO datetime format


def test_append_to_buffer_with_extracted_stores_pending_write():
    extracted = {
        "workout": {"detected": True, "exercises": [{"name": "Bench"}]},
        "tasks": [{"title": "Buy milk"}],
        "events": [],
    }
    batch_id = append_to_buffer([TRANSCRIPT], TEST_DATE, extracted=extracted)
    transcripts, pending = load_buffer(TEST_DATE)
    assert len(pending) == 1
    entry = pending[0]
    assert entry["batch_id"] == batch_id
    assert entry["workout"]["detected"] is True
    assert entry["tasks"] == [{"title": "Buy milk"}]
    assert entry["workout_written_at"] is None
    assert entry["tasks_written_at"] is None
    assert entry["events_written_at"] is None


def test_append_to_buffer_deduplicates_by_filename():
    append_to_buffer([TRANSCRIPT], TEST_DATE)
    append_to_buffer([TRANSCRIPT], TEST_DATE)
    transcripts, _ = load_buffer(TEST_DATE)
    assert len(transcripts) == 1


def test_mark_written_sets_resource_timestamp():
    extracted = {"workout": {"detected": True}, "tasks": [], "events": []}
    batch_id = append_to_buffer([TRANSCRIPT], TEST_DATE, extracted=extracted)
    mark_written(TEST_DATE, batch_id, "workout")
    _, pending = load_buffer(TEST_DATE)
    assert pending[0]["workout_written_at"] is not None
    assert pending[0]["tasks_written_at"] is None


def test_mark_written_is_noop_for_unknown_batch_id():
    extracted = {"workout": {"detected": True}, "tasks": [], "events": []}
    append_to_buffer([TRANSCRIPT], TEST_DATE, extracted=extracted)
    # Should not raise
    mark_written(TEST_DATE, "nonexistent-id", "workout")
    _, pending = load_buffer(TEST_DATE)
    assert pending[0]["workout_written_at"] is None


def test_mark_written_noop_when_no_buffer_file():
    # Should not raise even with no buffer file
    mark_written(TEST_DATE, "any-id", "tasks")
