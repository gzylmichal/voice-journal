import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# B1: WHISPER_PROMPT constant — must contain no digit characters
# ---------------------------------------------------------------------------

def test_whisper_prompt_has_no_digits():
    from pipeline.config import WHISPER_PROMPT
    digits_found = [ch for ch in WHISPER_PROMPT if ch.isdigit()]
    assert digits_found == [], f"WHISPER_PROMPT contains digits: {''.join(digits_found)!r}"


def test_whisper_prompt_has_vocabulary_terms():
    from pipeline.config import WHISPER_PROMPT
    assert "deadlift" in WHISPER_PROMPT.lower()
    assert "kg" in WHISPER_PROMPT
    assert "reps" in WHISPER_PROMPT.lower()


# ---------------------------------------------------------------------------
# B2: _filter_segments — hallucination heuristics
# ---------------------------------------------------------------------------

def _make_seg(text, no_speech_prob=0.0, avg_logprob=-0.3, compression_ratio=1.2):
    return {
        "text": text,
        "no_speech_prob": no_speech_prob,
        "avg_logprob": avg_logprob,
        "compression_ratio": compression_ratio,
    }


def test_filter_segments_drops_high_no_speech():
    from pipeline.audio import _filter_segments
    segs = [
        _make_seg("Good morning", no_speech_prob=0.1),
        _make_seg("Thank you.", no_speech_prob=0.9),  # high no_speech
    ]
    text, dropped = _filter_segments(segs)
    assert dropped == 1
    assert "Good morning" in text
    assert "Thank you" not in text


def test_filter_segments_keeps_normal_segments():
    from pipeline.audio import _filter_segments
    segs = [
        _make_seg("Bench press three sets"),
        _make_seg("Eighty kilograms eight reps"),
    ]
    text, dropped = _filter_segments(segs)
    assert dropped == 0
    assert "Bench press" in text
    assert "Eighty" in text


def test_filter_segments_drops_filler_hallucination():
    from pipeline.audio import _filter_segments
    segs = [
        _make_seg("Pull-ups eight reps"),
        _make_seg("Napisy stworzone przez społeczność Amara.org"),
    ]
    text, dropped = _filter_segments(segs)
    assert dropped == 1
    assert "Pull-ups" in text
    assert "Amara" not in text


def test_filter_segments_drops_low_logprob():
    from pipeline.audio import _filter_segments
    segs = [
        _make_seg("Cable rows", avg_logprob=-0.5),
        _make_seg("Garbled noise text", avg_logprob=-1.5),
    ]
    text, dropped = _filter_segments(segs)
    assert dropped == 1
    assert "Cable rows" in text


def test_filter_segments_drops_high_compression_ratio():
    from pipeline.audio import _filter_segments
    segs = [
        _make_seg("Squat session today", compression_ratio=1.1),
        _make_seg("aaaaaabbbbbbcccccc repetitive hallucination text", compression_ratio=3.0),
    ]
    text, dropped = _filter_segments(segs)
    assert dropped == 1
    assert "Squat" in text


# ---------------------------------------------------------------------------
# B2 fallback: verbose_json failure falls back gracefully
# ---------------------------------------------------------------------------

def test_transcribe_file_falls_back_on_no_segments(tmp_path):
    """If the response has no segments attribute, use .text directly."""
    from pipeline.audio import transcribe_file

    fake_audio = tmp_path / "test.m4a"
    fake_audio.write_bytes(b"\x00" * 100)

    mock_transcription = MagicMock()
    mock_transcription.segments = None
    mock_transcription.text = "Hello from fallback"

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_transcription

    with patch("pipeline.audio._denoise_audio", return_value=None):
        result = transcribe_file(mock_client, fake_audio)

    assert result["error"] is False
    assert result["text"] == "Hello from fallback"
    assert result["raw_text"] == "Hello from fallback"


def test_transcribe_file_returns_raw_and_filtered_text(tmp_path):
    """Good segments → filtered text excludes filler, raw_text includes it."""
    from pipeline.audio import transcribe_file

    fake_audio = tmp_path / "memo.m4a"
    fake_audio.write_bytes(b"\x00" * 100)

    segments = [
        {"text": "Pull-ups eight reps", "no_speech_prob": 0.05, "avg_logprob": -0.3, "compression_ratio": 1.1},
        {"text": "Thank you.", "no_speech_prob": 0.95, "avg_logprob": -0.3, "compression_ratio": 1.1},
    ]

    mock_transcription = MagicMock()
    mock_transcription.segments = segments

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_transcription

    with patch("pipeline.audio._denoise_audio", return_value=None):
        result = transcribe_file(mock_client, fake_audio)

    assert result["error"] is False
    assert "Pull-ups" in result["text"]
    assert "Thank you" not in result["text"]
    assert "Pull-ups" in result["raw_text"]
    assert "Thank you" in result["raw_text"]


def test_transcribe_file_uses_temperature_zero(tmp_path):
    """temperature=0 must be passed in the Whisper API call."""
    from pipeline.audio import transcribe_file

    fake_audio = tmp_path / "memo.m4a"
    fake_audio.write_bytes(b"\x00" * 100)

    mock_transcription = MagicMock()
    mock_transcription.segments = []

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_transcription

    with patch("pipeline.audio._denoise_audio", return_value=None):
        transcribe_file(mock_client, fake_audio)

    call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
    assert call_kwargs.get("temperature") == 0


def test_transcribe_file_uses_whisper_prompt(tmp_path):
    """WHISPER_PROMPT must be passed in the Whisper API call."""
    from pipeline.audio import transcribe_file
    from pipeline.config import WHISPER_PROMPT

    fake_audio = tmp_path / "memo.m4a"
    fake_audio.write_bytes(b"\x00" * 100)

    mock_transcription = MagicMock()
    mock_transcription.segments = []

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_transcription

    with patch("pipeline.audio._denoise_audio", return_value=None):
        transcribe_file(mock_client, fake_audio)

    call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
    assert call_kwargs.get("prompt") == WHISPER_PROMPT
