import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import date
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_transcript(filename="memo.m4a"):
    return {"file": filename, "time": "10:00", "text": "", "raw_text": "Thanks for watching.", "error": None}


def _good_transcript(filename="memo.m4a"):
    return {"file": filename, "time": "10:00", "text": "Bench press 80 kg.", "raw_text": "Bench press 80 kg.", "error": None}


# ---------------------------------------------------------------------------
# Empty-transcript skip tests
# ---------------------------------------------------------------------------

def test_empty_transcript_not_buffered(tmp_path):
    """A memo whose filtered text is empty must not be buffered or extracted."""
    import voice_journal

    fake_file = tmp_path / "memo.m4a"
    fake_file.write_bytes(b"audio")

    with patch("voice_journal.BUFFER_DIR", tmp_path), \
         patch("voice_journal.INBOX_DIR", tmp_path / "inbox"), \
         patch("voice_journal.ARCHIVE_AUDIO_DIR", tmp_path / "archive" / "audio"), \
         patch("voice_journal.get_inbox_files", return_value=[fake_file]), \
         patch("voice_journal.transcribe_file", return_value=_empty_transcript()), \
         patch("voice_journal.Groq"), \
         patch("voice_journal.GROQ_API_KEY", "test"), \
         patch("voice_journal.append_to_buffer") as mock_buf, \
         patch("voice_journal.archive_files") as mock_arc, \
         patch("voice_journal.extract_workout"), \
         patch("voice_journal.extract_tasks"), \
         patch("voice_journal.extract_calendar_events"), \
         patch("voice_journal.extract_bodyweight"):
        voice_journal.run_upload_mode()

    mock_buf.assert_not_called()
    mock_arc.assert_called_once()


def test_empty_transcript_audio_still_archived(tmp_path):
    """Audio for a memo with empty transcript must be archived (file moved out of inbox)."""
    import voice_journal
    from pipeline.storage import archive_files as real_archive_files

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_archive = tmp_path / "archive" / "audio"
    audio_archive.mkdir(parents=True)

    fake_file = inbox / "memo.m4a"
    fake_file.write_bytes(b"audio")

    with patch("voice_journal.BUFFER_DIR", tmp_path), \
         patch("voice_journal.INBOX_DIR", inbox), \
         patch("voice_journal.ARCHIVE_AUDIO_DIR", audio_archive), \
         patch("pipeline.storage.ARCHIVE_AUDIO_DIR", audio_archive), \
         patch("pipeline.storage.ARCHIVE_TRANSCRIPTS_DIR", tmp_path / "archive" / "transcripts"), \
         patch("voice_journal.get_inbox_files", return_value=[fake_file]), \
         patch("voice_journal.transcribe_file", return_value=_empty_transcript()), \
         patch("voice_journal.Groq"), \
         patch("voice_journal.GROQ_API_KEY", "test"), \
         patch("voice_journal.extract_workout"), \
         patch("voice_journal.extract_tasks"), \
         patch("voice_journal.extract_calendar_events"), \
         patch("voice_journal.extract_bodyweight"):
        voice_journal.run_upload_mode()

    today = date.today()
    assert not fake_file.exists(), "audio should have been moved out of inbox"
    assert (audio_archive / today.isoformat() / "memo.m4a").exists(), "audio should be in archive"


def test_mixed_only_nonempty_buffered(tmp_path):
    """When some memos have empty transcripts, only non-empty ones go to extract/buffer."""
    import voice_journal

    files = [tmp_path / "a.m4a", tmp_path / "b.m4a"]
    for f in files:
        f.write_bytes(b"audio")

    def fake_transcribe(client, f):
        return _empty_transcript(f.name) if f.name == "a.m4a" else _good_transcript(f.name)

    mock_extracted = {"workout": {"detected": False}, "tasks": [], "events": [], "bodyweight": {"detected": False}}

    with patch("voice_journal.BUFFER_DIR", tmp_path), \
         patch("voice_journal.INBOX_DIR", tmp_path / "inbox"), \
         patch("voice_journal.ARCHIVE_AUDIO_DIR", tmp_path / "archive" / "audio"), \
         patch("voice_journal.get_inbox_files", return_value=files), \
         patch("voice_journal.transcribe_file", side_effect=fake_transcribe), \
         patch("voice_journal.Groq"), \
         patch("voice_journal.GROQ_API_KEY", "test"), \
         patch("voice_journal.append_to_buffer") as mock_buf, \
         patch("voice_journal.archive_files") as mock_arc, \
         patch("voice_journal.extract_all", return_value=mock_extracted) as mock_ea, \
         patch("voice_journal.fetch_latest_bodyweight", return_value=None):
        voice_journal.run_upload_mode()

    # extract_all was called with only the non-empty transcript
    ea_call_transcripts = mock_ea.call_args[0][0]
    assert len(ea_call_transcripts) == 1
    assert ea_call_transcripts[0]["file"] == "b.m4a"

    # buffer received only the non-empty transcript
    buf_call_transcripts = mock_buf.call_args[0][0]
    assert len(buf_call_transcripts) == 1
    assert buf_call_transcripts[0]["file"] == "b.m4a"

    # archive was still called (all audio archived)
    mock_arc.assert_called_once()


# ---------------------------------------------------------------------------
# Phase M Step 2: query memo isolation
# ---------------------------------------------------------------------------

def _query_extracted():
    return {
        "workout": {"detected": False, "workout_name": None, "exercises": []},
        "tasks": [],
        "events": [],
        "bodyweight": {"detected": False},
        "metrics": {"sleep": None, "energy": None, "note": None},
        "query": {"detected": True, "question": "What did I squat last time?"},
    }


def _normal_extracted():
    return {
        "workout": {"detected": False},
        "tasks": [],
        "events": [],
        "bodyweight": {"detected": False},
        "metrics": {"sleep": None, "energy": None, "note": None},
        "query": {"detected": False, "question": None},
    }


def test_query_memo_does_not_call_append_to_buffer(tmp_path):
    """When query.detected is True, the memo must NOT be appended to the buffer."""
    import voice_journal

    fake_file = tmp_path / "memo.m4a"
    fake_file.write_bytes(b"audio")

    with patch("voice_journal.BUFFER_DIR", tmp_path), \
         patch("voice_journal.INBOX_DIR", tmp_path / "inbox"), \
         patch("voice_journal.ARCHIVE_AUDIO_DIR", tmp_path / "archive" / "audio"), \
         patch("voice_journal.get_inbox_files", return_value=[fake_file]), \
         patch("voice_journal.transcribe_file", return_value=_good_transcript()), \
         patch("voice_journal.Groq"), \
         patch("voice_journal.GROQ_API_KEY", "test"), \
         patch("voice_journal.extract_all", return_value=_query_extracted()), \
         patch("voice_journal.append_to_buffer") as mock_buf, \
         patch("voice_journal.archive_files") as mock_arc, \
         patch("voice_journal._handle_query") as mock_hq:
        voice_journal.run_upload_mode()

    mock_buf.assert_not_called()
    mock_arc.assert_called_once()  # audio still archived
    mock_hq.assert_called_once()


def test_query_memo_does_not_write_notion(tmp_path):
    """When query.detected is True, no workout/task/event/bodyweight writes to Notion."""
    import voice_journal

    fake_file = tmp_path / "memo.m4a"
    fake_file.write_bytes(b"audio")

    with patch("voice_journal.BUFFER_DIR", tmp_path), \
         patch("voice_journal.INBOX_DIR", tmp_path / "inbox"), \
         patch("voice_journal.ARCHIVE_AUDIO_DIR", tmp_path / "archive" / "audio"), \
         patch("voice_journal.get_inbox_files", return_value=[fake_file]), \
         patch("voice_journal.transcribe_file", return_value=_good_transcript()), \
         patch("voice_journal.Groq"), \
         patch("voice_journal.GROQ_API_KEY", "test"), \
         patch("voice_journal.extract_all", return_value=_query_extracted()), \
         patch("voice_journal.append_to_buffer") as mock_buf, \
         patch("voice_journal.archive_files"), \
         patch("voice_journal.create_notion_workout_entries") as mock_wk, \
         patch("voice_journal.create_notion_tasks") as mock_tasks, \
         patch("voice_journal.create_gcal_events") as mock_gcal, \
         patch("voice_journal.store_bodyweight") as mock_bw, \
         patch("voice_journal._handle_query"):
        voice_journal.run_upload_mode()

    mock_buf.assert_not_called()
    mock_wk.assert_not_called()
    mock_tasks.assert_not_called()
    mock_gcal.assert_not_called()
    mock_bw.assert_not_called()


def test_normal_memo_still_calls_append_to_buffer(tmp_path):
    """A non-query batch is completely unchanged — buffer is still written."""
    import voice_journal

    fake_file = tmp_path / "memo.m4a"
    fake_file.write_bytes(b"audio")

    with patch("voice_journal.BUFFER_DIR", tmp_path), \
         patch("voice_journal.INBOX_DIR", tmp_path / "inbox"), \
         patch("voice_journal.ARCHIVE_AUDIO_DIR", tmp_path / "archive" / "audio"), \
         patch("voice_journal.get_inbox_files", return_value=[fake_file]), \
         patch("voice_journal.transcribe_file", return_value=_good_transcript()), \
         patch("voice_journal.Groq"), \
         patch("voice_journal.GROQ_API_KEY", "test"), \
         patch("voice_journal.extract_all", return_value=_normal_extracted()), \
         patch("voice_journal.append_to_buffer") as mock_buf, \
         patch("voice_journal.archive_files"), \
         patch("voice_journal.send_preworkout_brief"), \
         patch("voice_journal.send_batch_summary"), \
         patch("voice_journal.load_buffer", return_value=([], [])), \
         patch("voice_journal.fetch_latest_bodyweight", return_value=None), \
         patch("voice_journal.NOTION_ENABLED", False), \
         patch("voice_journal.GCAL_ENABLED", False), \
         patch("voice_journal.NOTION_BODYWEIGHT_DB_ID", ""):
        voice_journal.run_upload_mode()

    mock_buf.assert_called_once()
