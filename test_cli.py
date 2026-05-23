import json
from datetime import date
from pathlib import Path


def test_inbox_count_empty_dir(tmp_path):
    from cli import _inbox_count
    assert _inbox_count(tmp_path, {".m4a", ".mp3"}) == 0


def test_inbox_count_with_audio_files(tmp_path):
    from cli import _inbox_count
    (tmp_path / "a.m4a").touch()
    (tmp_path / "b.mp3").touch()
    (tmp_path / "notes.txt").touch()  # not an audio format, must not count
    assert _inbox_count(tmp_path, {".m4a", ".mp3"}) == 2


def test_inbox_count_missing_dir():
    from cli import _inbox_count
    assert _inbox_count(Path("/nonexistent/xyz"), {".m4a"}) == 0


def test_load_buffer_no_file(tmp_path):
    from cli import _load_buffer
    assert _load_buffer(tmp_path, date(2026, 1, 1)) == []


def test_load_buffer_returns_entries(tmp_path):
    from cli import _load_buffer
    entries = [{"file": "a.m4a", "time": "09:00", "text": "hello", "error": False}]
    (tmp_path / "2026-01-01.json").write_text(json.dumps(entries))
    result = _load_buffer(tmp_path, date(2026, 1, 1))
    assert len(result) == 1
    assert result[0]["text"] == "hello"


def test_load_buffer_corrupt_json(tmp_path):
    from cli import _load_buffer
    (tmp_path / "2026-01-01.json").write_text("not valid json {{{")
    assert _load_buffer(tmp_path, date(2026, 1, 1)) == []
