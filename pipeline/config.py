"""pipeline/config.py — All configuration for the Voice Journal pipeline.

Single point of .env loading. Every other pipeline module imports constants
from here rather than reading os.getenv directly.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Groq — required (Whisper transcription)
# ---------------------------------------------------------------------------
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
WHISPER_MODEL = "whisper-large-v3-turbo"
TRANSCRIPT_LANGUAGE = os.getenv("TRANSCRIPT_LANGUAGE", "auto")
LLAMA_MODEL   = os.getenv("LLAMA_MODEL", "llama-3.3-70b-versatile")

# ---------------------------------------------------------------------------
# AI providers
# ---------------------------------------------------------------------------
AI_PROVIDER       = os.getenv("AI_PROVIDER", "auto")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
GEMINI_MODEL      = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ---------------------------------------------------------------------------
# Notion — optional
# ---------------------------------------------------------------------------
NOTION_TOKEN           = os.getenv("NOTION_TOKEN", "")
NOTION_DATABASE_ID     = os.getenv("NOTION_DATABASE_ID", "")
NOTION_WORKOUT_DB_ID   = os.getenv("NOTION_WORKOUT_DB_ID", "")
NOTION_TASK_DB_ID      = os.getenv("NOTION_TASK_DB_ID", "")
NOTION_TRAINER_PAGE_ID = os.getenv("NOTION_TRAINER_PAGE_ID", "")
NOTION_BODYWEIGHT_DB_ID = os.getenv("NOTION_BODYWEIGHT_DB_ID", "")
NOTION_ENABLED         = bool(NOTION_TOKEN and NOTION_DATABASE_ID)
NOTION_API_URL         = "https://api.notion.com/v1/pages"
NOTION_VERSION         = "2022-06-28"

# ---------------------------------------------------------------------------
# Google Calendar — optional
# ---------------------------------------------------------------------------
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GCAL_TOKEN_FILE    = Path(os.getenv("GCAL_TOKEN_FILE", "/opt/voice-journal/gcal_token.json"))

try:
    from google.oauth2.credentials import Credentials as _Credentials  # noqa: F401
    _GCAL_AVAILABLE = True
except ImportError:
    _GCAL_AVAILABLE = False

GCAL_ENABLED = bool(_GCAL_AVAILABLE and GCAL_TOKEN_FILE.exists())

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR                = Path(os.getenv("BASE_DIR", "/opt/voice-journal"))
INBOX_DIR               = BASE_DIR / "inbox"
ARCHIVE_AUDIO_DIR       = BASE_DIR / "archive" / "audio"
ARCHIVE_MD_DIR          = BASE_DIR / "archive" / "markdown"
ARCHIVE_TRANSCRIPTS_DIR = BASE_DIR / "archive" / "transcripts"
BUFFER_DIR              = BASE_DIR / "buffer"

# ---------------------------------------------------------------------------
# Audio formats
# ---------------------------------------------------------------------------
SUPPORTED_FORMATS = {".m4a", ".mp3", ".wav", ".mp4", ".ogg", ".flac", ".webm", ".caf"}

# ---------------------------------------------------------------------------
# Whisper transcription settings
# ---------------------------------------------------------------------------
# Vocabulary hint for Whisper — exercise names and units only, no numeric examples.
# Numeric examples bias Whisper to reproduce those exact strings (hallucination cause).
# Keep under ~200 tokens (Whisper truncates at 224). Overridable via WHISPER_PROMPT env var.
WHISPER_PROMPT = os.getenv("WHISPER_PROMPT", (
    "Smith machine bench press, Bulgarian split squat, pull-ups, chin-ups, deadlift, "
    "Romanian deadlift, leg press, cable row, lat pulldown, overhead press, dumbbell, "
    "barbell, kg, reps, sets, bodyweight, kilograms, curls, extension, triceps, biceps, "
    "Hack-squat, squat, hamstrings, quad, "
    "wyciskanie, przysiady bułgarskie, podciąganie, martwy ciąg, "
    "wiosłowanie, wyciskanie żołnierskie, hantle, sztanga, kilogramy, serie, powtórzenia"
))

# Whisper hallucination filter thresholds
WHISPER_NO_SPEECH_PROB_THRESHOLD = float(os.getenv("WHISPER_NO_SPEECH_PROB_THRESHOLD", "0.6"))
WHISPER_AVG_LOGPROB_THRESHOLD = float(os.getenv("WHISPER_AVG_LOGPROB_THRESHOLD", "-1.0"))
WHISPER_COMPRESSION_RATIO_THRESHOLD = float(os.getenv("WHISPER_COMPRESSION_RATIO_THRESHOLD", "2.4"))
