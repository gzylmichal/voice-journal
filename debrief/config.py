"""
debrief/config.py — Configuration for Morning Debrief and Weekly Review.

Reads from the shared .env in the project root (one directory up).
Key names follow the voice-journal convention; debrief-only names are
accepted as fallbacks for backward compatibility.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def load_config() -> dict:
    # Shared .env lives one level up (voice_journal_vps root)
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    def _get(*keys, default=""):
        for k in keys:
            v = os.getenv(k, "")
            if v:
                return v
        return default

    return {
        # Location
        "latitude":      _get("LATITUDE", default="50.0614"),
        "longitude":     _get("LONGITUDE", default="19.9366"),
        "timezone":      _get("TIMEZONE", default="Europe/Warsaw"),
        "location_name": _get("LOCATION_NAME", default="Kraków"),

        # AI — voice journal uses GOOGLE_API_KEY; debrief historically GEMINI_API_KEY
        "gemini_api_key": _get("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        "gemini_model":   _get("GEMINI_MODEL", default="gemini-2.5-flash"),

        # Email (SMTP)
        "smtp_host":     _get("SMTP_HOST"),
        "smtp_port":     int(os.getenv("SMTP_PORT", "587")),
        "smtp_user":     _get("SMTP_USER"),
        "smtp_password": _get("SMTP_PASSWORD"),
        "email_from":    _get("EMAIL_FROM"),
        "email_to":      _get("EMAIL_TO"),

        # Google Calendar (service account for debrief)
        "google_credentials_file": _get("GOOGLE_CREDENTIALS_FILE"),
        "google_calendar_id":      _get("GOOGLE_CALENDAR_ID", default="primary"),

        # Notion — voice journal uses NOTION_TOKEN; debrief historically NOTION_API_KEY
        "notion_api_key":      _get("NOTION_TOKEN", "NOTION_API_KEY"),
        "notion_journal_db_id": _get("NOTION_DATABASE_ID", "NOTION_JOURNAL_DB_ID"),
        "notion_workout_db_id": _get("NOTION_WORKOUT_DB_ID"),

        # Binance
        "binance_api_key":    _get("BINANCE_API_KEY"),
        "binance_api_secret": _get("BINANCE_API_SECRET"),

        # News
        "news_global_count": int(os.getenv("NEWS_GLOBAL_COUNT", "7")),
        "news_polish_count": int(os.getenv("NEWS_POLISH_COUNT", "7")),

        # Currency
        "currency_codes": _get("CURRENCY_CODES", default="USD,EUR,GBP,CHF").split(","),

        # Task aging
        "notion_task_db_id": _get("NOTION_TASK_DB_ID"),
        "task_aging_days":   int(os.getenv("TASK_AGING_DAYS", "7")),
    }


def require_keys(cfg: dict, keys: list) -> None:
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        print(f"ERROR: Missing required config keys: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
