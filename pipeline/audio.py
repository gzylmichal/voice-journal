"""pipeline/audio.py — Audio collection and Whisper transcription."""

import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from groq import Groq

from pipeline.config import (
    INBOX_DIR,
    SUPPORTED_FORMATS,
    TRANSCRIPT_LANGUAGE,
    WHISPER_MODEL,
    WHISPER_PROMPT,
    WHISPER_NO_SPEECH_PROB_THRESHOLD,
    WHISPER_AVG_LOGPROB_THRESHOLD,
    WHISPER_COMPRESSION_RATIO_THRESHOLD,
)

log = logging.getLogger(__name__)

# Known Whisper hallucinations that appear as entire segments on silence/noise.
WHISPER_FILLER_HALLUCINATIONS = {
    "Thank you.",
    "Thanks for watching.",
    "Thanks for watching",
    "Thank you for watching.",
    "Dziękuję.",
    "Dziękuję za uwagę.",
    "Napisy stworzone przez społeczność Amara.org",
    "Napisy stworzone przez społeczność Amara.org.",
    "Amara.org",
    ".",
    "...",
}


def _filter_segments(segments: list) -> tuple:
    """
    Drop low-quality segments from a verbose_json transcription result.

    Returns (filtered_text, dropped_count).
    """
    kept = []
    dropped = 0
    for seg in segments:
        text = (seg.get("text") or "").strip()
        no_speech = seg.get("no_speech_prob", 0.0)
        avg_logprob = seg.get("avg_logprob", 0.0)
        compression = seg.get("compression_ratio", 0.0)

        if no_speech > WHISPER_NO_SPEECH_PROB_THRESHOLD:
            log.debug(f"Dropped segment (no_speech_prob={no_speech:.2f}): {text!r}")
            dropped += 1
            continue
        if avg_logprob < WHISPER_AVG_LOGPROB_THRESHOLD:
            log.debug(f"Dropped segment (avg_logprob={avg_logprob:.2f}): {text!r}")
            dropped += 1
            continue
        if compression > WHISPER_COMPRESSION_RATIO_THRESHOLD:
            log.debug(f"Dropped segment (compression_ratio={compression:.2f}): {text!r}")
            dropped += 1
            continue
        if text in WHISPER_FILLER_HALLUCINATIONS:
            log.debug(f"Dropped filler hallucination: {text!r}")
            dropped += 1
            continue
        kept.append(text)

    return " ".join(kept).strip(), dropped


def get_inbox_files() -> List[Path]:
    """Get all audio files from inbox, sorted by modification time."""
    if not INBOX_DIR.exists():
        log.warning(f"Inbox directory does not exist: {INBOX_DIR}")
        return []
    files = [
        f for f in INBOX_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_FORMATS
    ]
    files.sort(key=lambda f: f.stat().st_mtime)
    return files


def _denoise_audio(audio_path: Path) -> Optional[Path]:
    """
    Run ffmpeg noise-reduction on an audio file and return path to cleaned WAV.
    Returns None if ffmpeg is not available or preprocessing fails (caller falls
    back to raw file).

    Filters applied:
      afftdn=nf=-25   — adaptive FFT denoiser, kills steady-state gym noise
                        (music, AC hum, treadmills, equipment hum)
      highpass=f=80   — removes low-frequency rumble (weights dropping, bass)
      dynaudnorm      — normalises volume so quiet memos don't get clipped
    """
    if not shutil.which("ffmpeg"):
        return None
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)
    tmp = Path(tmp_name)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(audio_path),
                "-af", "afftdn=nf=-25,highpass=f=80,dynaudnorm",
                "-ar", "16000",
                "-ac", "1",
                str(tmp),
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and tmp.exists():
            log.info(f"Denoised: {audio_path.name} → {tmp.name}")
            return tmp
        else:
            log.warning(f"ffmpeg denoising failed for {audio_path.name}, using raw audio")
            tmp.unlink(missing_ok=True)
            return None
    except Exception as e:
        log.warning(f"ffmpeg error ({audio_path.name}): {e}, using raw audio")
        tmp.unlink(missing_ok=True)
        return None


def transcribe_file(client: Groq, audio_path: Path) -> dict:
    """Transcribe a single audio file. Returns dict with metadata, filtered text, and raw_text."""
    file_size_mb = audio_path.stat().st_size / (1024 * 1024)
    mod_time = datetime.fromtimestamp(audio_path.stat().st_mtime)

    log.info(f"Transcribing: {audio_path.name} ({file_size_mb:.1f} MB)")

    if file_size_mb > 25:
        log.warning(f"File exceeds 25MB Groq free tier limit: {audio_path.name}")
        return {
            "file": audio_path.name,
            "time": mod_time.strftime("%H:%M"),
            "text": f"[Skipped: file too large ({file_size_mb:.1f} MB)]",
            "raw_text": "",
            "error": True,
        }

    denoised_path = _denoise_audio(audio_path)
    read_path = denoised_path if denoised_path else audio_path

    try:
        with open(read_path, "rb") as f:
            whisper_kwargs = {
                "file": (audio_path.name, f.read()),
                "model": WHISPER_MODEL,
                "response_format": "verbose_json",
                "temperature": 0,
                "prompt": WHISPER_PROMPT,
            }
            if TRANSCRIPT_LANGUAGE not in ("auto", ""):
                whisper_kwargs["language"] = TRANSCRIPT_LANGUAGE

            transcription = client.audio.transcriptions.create(**whisper_kwargs)

        if denoised_path and denoised_path.exists():
            denoised_path.unlink()

        # Extract text from verbose_json response; fall back to plain text attribute.
        segments = getattr(transcription, "segments", None)
        if segments is not None:
            raw_text = " ".join((seg.get("text") or "").strip() for seg in segments).strip()
            filtered_text, dropped = _filter_segments(segments)
            if dropped:
                log.info(f"Segment filter: {dropped} segment(s) dropped for {audio_path.name}")
        else:
            raw_text = (
                transcription.strip() if isinstance(transcription, str)
                else (getattr(transcription, "text", "") or "").strip()
            )
            filtered_text = raw_text
            dropped = 0

        log.info(f"Transcribed {audio_path.name}: {len(filtered_text)} chars ({dropped} segments dropped)")

        return {
            "file": audio_path.name,
            "time": mod_time.strftime("%H:%M"),
            "text": filtered_text,
            "raw_text": raw_text,
            "error": False,
        }

    except Exception as e:
        log.error(f"Transcription failed for {audio_path.name}: {e}")
        return {
            "file": audio_path.name,
            "time": mod_time.strftime("%H:%M"),
            "text": f"[Transcription failed: {e}]",
            "raw_text": "",
            "error": True,
        }
