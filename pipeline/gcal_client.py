"""pipeline/gcal_client.py — Google Calendar event creation."""

import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from pipeline.config import GCAL_ENABLED, GCAL_TOKEN_FILE, GOOGLE_CALENDAR_ID

log = logging.getLogger(__name__)

DEFAULT_DURATION_MINUTES = 30
DEFAULT_EVENT_HOUR = 9

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    _GCAL_LIBS_AVAILABLE = True
except ImportError:
    _GCAL_LIBS_AVAILABLE = False


def _get_gcal_service():
    """Load credentials and return a Google Calendar service object."""
    creds = Credentials.from_authorized_user_file(
        str(GCAL_TOKEN_FILE),
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        GCAL_TOKEN_FILE.write_text(creds.to_json())
        log.info("Google Calendar token refreshed")
    return build("calendar", "v3", credentials=creds)


def _build_gcal_event(event: dict) -> Optional[dict]:
    """Convert extracted event dict to a Google Calendar API event body."""
    title = event.get("title", "Untitled event").strip()
    notes = event.get("notes")

    try:
        event_date = date.fromisoformat(event["date"])
    except (KeyError, ValueError):
        log.warning(f"Skipping event '{title}': invalid date '{event.get('date')}'")
        return None

    duration = event.get("duration_minutes") or DEFAULT_DURATION_MINUTES

    time_str = event.get("time")
    if time_str:
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            log.warning(f"Event '{title}': bad time '{time_str}', defaulting to {DEFAULT_EVENT_HOUR}:00")
            hour, minute = DEFAULT_EVENT_HOUR, 0
    else:
        hour, minute = DEFAULT_EVENT_HOUR, 0

    start_dt = datetime(event_date.year, event_date.month, event_date.day, hour, minute)
    end_dt   = start_dt + timedelta(minutes=duration)

    return {
        "summary": title,
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Europe/Warsaw"},
        "end":   {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),   "timeZone": "Europe/Warsaw"},
        "description": f"Added from voice journal\n\n{notes}" if notes else "Added from voice journal",
    }


def create_gcal_events(events: List[dict]) -> int:
    """Create events in Google Calendar. Returns count of successfully created events."""
    if not events:
        return 0

    try:
        service = _get_gcal_service()
    except Exception as e:
        log.error(f"Google Calendar auth failed: {e}")
        return 0

    created = 0
    for event in events:
        gcal_body = _build_gcal_event(event)
        if gcal_body is None:
            continue
        try:
            result = service.events().insert(
                calendarId=GOOGLE_CALENDAR_ID,
                body=gcal_body,
            ).execute()
            log.info(
                f"Calendar event created: '{gcal_body['summary']}' "
                f"on {event.get('date')} at {event.get('time', 'no time specified')} "
                f"→ {result.get('htmlLink', '')}"
            )
            created += 1
        except Exception as e:
            log.error(f"Failed to create event '{gcal_body.get('summary')}': {e}")

    return created
