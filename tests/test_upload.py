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

    with patch("voice_journal.BUFFER_DIR", tmp_path), \
         patch("voice_journal.INBOX_DIR", tmp_path / "inbox"), \
         patch("voice_journal.ARCHIVE_AUDIO_DIR", tmp_path / "archive" / "audio"), \
         patch("voice_journal.get_inbox_files", return_value=files), \
         patch("voice_journal.transcribe_file", side_effect=fake_transcribe), \
         patch("voice_journal.Groq"), \
         patch("voice_journal.GROQ_API_KEY", "test"), \
         patch("voice_journal.append_to_buffer") as mock_buf, \
         patch("voice_journal.archive_files") as mock_arc, \
         patch("voice_journal.extract_workout", return_value={"detected": False}) as mock_wk, \
         patch("voice_journal.extract_tasks", return_value=[]), \
         patch("voice_journal.extract_calendar_events", return_value=[]), \
         patch("voice_journal.extract_bodyweight", return_value={"detected": False}), \
         patch("voice_journal.fetch_latest_bodyweight", return_value=None):
        voice_journal.run_upload_mode()

    # extract was called with only the non-empty transcript
    wk_call_transcripts = mock_wk.call_args[0][1]
    assert len(wk_call_transcripts) == 1
    assert wk_call_transcripts[0]["file"] == "b.m4a"

    # buffer received only the non-empty transcript
    buf_call_transcripts = mock_buf.call_args[0][0]
    assert len(buf_call_transcripts) == 1
    assert buf_call_transcripts[0]["file"] == "b.m4a"

    # archive was still called (all audio archived)
    mock_arc.assert_called_once()
