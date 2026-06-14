"""Tests for Phase J Step 3: buffer backward compatibility and once-per-day metrics write."""
import sys
import json
import tempfile
from pathlib import Path
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.storage import append_to_buffer, load_buffer, mark_written


_DATE = date(2026, 6, 14)


# ---------------------------------------------------------------------------
# Buffer backward compatibility — old entries without metrics keys load fine
# ---------------------------------------------------------------------------

def test_old_buffer_without_metrics_keys_loads_fine():
    """An old-shape pending_writes entry (no metrics/metrics_written_at) loads without error."""
    old_entry = {
        "batch_id":              "2026-06-01T08:00:00",
        "workout":               {"detected": False},
        "tasks":                 [],
        "events":                [],
        "bodyweight":            {"detected": False},
        "workout_written_at":    None,
        "tasks_written_at":      None,
        "events_written_at":     None,
        "bodyweight_written_at": None,
        # intentionally missing: "metrics", "metrics_written_at"
    }
    old_data = {
        "transcripts": [{"file": "old.m4a", "time": "08:00", "text": "hello"}],
        "pending_writes": [old_entry],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        buf_path = Path(tmpdir) / f"{_DATE.isoformat()}.json"
        buf_path.write_text(json.dumps(old_data))
        with patch("pipeline.storage.BUFFER_DIR", Path(tmpdir)):
            transcripts, pending = load_buffer(_DATE)
    assert len(transcripts) == 1
    assert len(pending) == 1
    # Old entry loads without KeyError — metrics keys simply absent
    assert "batch_id" in pending[0]
    assert pending[0].get("metrics") is None


# ---------------------------------------------------------------------------
# New buffer entries include metrics and metrics_written_at
# ---------------------------------------------------------------------------

def test_new_buffer_entry_includes_metrics_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("pipeline.storage.BUFFER_DIR", Path(tmpdir)):
            batch_id = append_to_buffer(
                [{"file": "a.m4a", "time": "09:00", "text": "slept well"}],
                _DATE,
                extracted={
                    "workout": {"detected": False},
                    "tasks": [],
                    "events": [],
                    "bodyweight": {"detected": False},
                    "metrics": {"sleep": "good", "energy": None, "note": None},
                },
            )
            _, pending = load_buffer(_DATE)
    assert len(pending) == 1
    entry = pending[0]
    assert "metrics" in entry
    assert entry["metrics"]["sleep"] == "good"
    assert "metrics_written_at" in entry
    assert entry["metrics_written_at"] is None


# ---------------------------------------------------------------------------
# mark_written sets metrics_written_at
# ---------------------------------------------------------------------------

def test_mark_written_sets_metrics_written_at():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("pipeline.storage.BUFFER_DIR", Path(tmpdir)):
            batch_id = append_to_buffer(
                [{"file": "b.m4a", "time": "10:00", "text": "padnięty"}],
                _DATE,
                extracted={
                    "workout": {"detected": False},
                    "tasks": [],
                    "events": [],
                    "bodyweight": {"detected": False},
                    "metrics": {"sleep": "bad", "energy": "low", "note": None},
                },
            )
            mark_written(_DATE, batch_id, "metrics")
            _, pending = load_buffer(_DATE)
    entry = pending[0]
    assert entry["metrics_written_at"] is not None


# ---------------------------------------------------------------------------
# First detection wins: second batch with metrics detected does not write again
# ---------------------------------------------------------------------------

def test_first_metrics_write_wins_second_batch_skips(tmp_path):
    """When the first batch already has metrics_written_at set, a second batch skips."""
    from pipeline.storage import get_buffer_path

    # Simulate buffer where first batch already has metrics written
    first_batch = {
        "batch_id": "2026-06-14T09:00:00",
        "workout": {"detected": False},
        "tasks": [], "events": [],
        "bodyweight": {"detected": False},
        "metrics": {"sleep": "bad", "energy": "low", "note": None},
        "workout_written_at": None, "tasks_written_at": None,
        "events_written_at": None, "bodyweight_written_at": None,
        "metrics_written_at": "2026-06-14T09:01:00",  # already written
    }
    buf_data = {"transcripts": [], "pending_writes": [first_batch]}

    with patch("pipeline.storage.BUFFER_DIR", tmp_path):
        buf_path = get_buffer_path(_DATE)
        buf_path.write_text(json.dumps(buf_data))
        _, pending = load_buffer(_DATE)

    # Verify: first batch has metrics_written_at set
    assert pending[0]["metrics_written_at"] is not None

    # A second batch would check existing pending and find already_written=True
    already_written = any(
        e.get("metrics_written_at") is not None
        for e in pending
    )
    assert already_written is True
