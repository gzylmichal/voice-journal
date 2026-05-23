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

from pipeline.config import INBOX_DIR, SUPPORTED_FORMATS, TRANSCRIPT_LANGUAGE, WHISPER_MODEL

log = logging.getLogger(__name__)


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
    """Transcribe a single audio file. Returns dict with metadata + text."""
    file_size_mb = audio_path.stat().st_size / (1024 * 1024)
    mod_time = datetime.fromtimestamp(audio_path.stat().st_mtime)

    log.info(f"Transcribing: {audio_path.name} ({file_size_mb:.1f} MB)")

    if file_size_mb > 25:
        log.warning(f"File exceeds 25MB Groq free tier limit: {audio_path.name}")
        return {
            "file": audio_path.name,
            "time": mod_time.strftime("%H:%M"),
            "text": f"[Skipped: file too large ({file_size_mb:.1f} MB)]",
            "error": True
        }

    denoised_path = _denoise_audio(audio_path)
    read_path = denoised_path if denoised_path else audio_path

    try:
        with open(read_path, "rb") as f:
            whisper_kwargs = {
                "file": (audio_path.name, f.read()),
                "model": WHISPER_MODEL,
                "response_format": "text",
            }
            if TRANSCRIPT_LANGUAGE not in ("auto", ""):
                whisper_kwargs["language"] = TRANSCRIPT_LANGUAGE

            # Vocabulary hint for both English and Polish — memos may be in either
            # language or mix both. Whisper auto-detects per file; the prompt steers
            # it toward gym terminology in whichever language is spoken.
            whisper_kwargs["prompt"] = (
                "Smith machine bench press, Bulgarian split squat, pull-ups, chin-ups, "
                "deadlift, Romanian deadlift, squat, leg press, cable rows, lat pulldown, "
                "overhead press, dumbbell, barbell, kg, reps, sets, bodyweight, "
                "wyciskanie na Smithu, przysiady bułgarskie, podciąganie, martwy ciąg, "
                "rumuński martwy ciąg, wiosłowanie, wyciskanie żołnierskie, "
                "hantle, sztanga, kilogramy, serie, powtórzenia, "
                "60 kg, 70 kg, 80 kg, 85 kg, 90 kg, 95 kg, 100 kg, "
                "3 powtórzenia, 5 powtórzeń, 8 powtórzeń, 10 powtórzeń, 12 powtórzeń, "
                "3 serie, 4 serie, 5 serii, 8 serii"
            )

            transcription = client.audio.transcriptions.create(**whisper_kwargs)

        if denoised_path and denoised_path.exists():
            denoised_path.unlink()

        text = transcription.strip() if isinstance(transcription, str) else transcription.text.strip()
        log.info(f"Transcribed {audio_path.name}: {len(text)} chars")

        return {
            "file": audio_path.name,
            "time": mod_time.strftime("%H:%M"),
            "text": text,
            "error": False
        }

    except Exception as e:
        log.error(f"Transcription failed for {audio_path.name}: {e}")
        return {
            "file": audio_path.name,
            "time": mod_time.strftime("%H:%M"),
            "text": f"[Transcription failed: {e}]",
            "error": True
        }
