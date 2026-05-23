"""
Calendar collector — Google Calendar API.

Returns structured dict with today's events + tomorrow's first event.
"""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


def collect_calendar(cfg: dict) -> dict:
    """Fetch today's events + tomorrow's first event."""

    creds_file = cfg.get("google_credentials_file", "")
    calendar_id = cfg.get("google_calendar_id", "primary")

    if not creds_file or not Path(creds_file).exists():
        return {"configured": False, "today": [], "tomorrow_first": None}

    creds = Credentials.from_service_account_file(
        creds_file,
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    tz_name = cfg.get("timezone", "Europe/Warsaw")
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    tomorrow_end = today_start + timedelta(days=2)

    today_events = [
        _normalize_event(e, tz)
        for e in _list_events(service, calendar_id, today_start, today_end, tz_name)
    ]
    tomorrow_events = _list_events(
        service, calendar_id, today_end, tomorrow_end, tz_name, max_results=1
    )
    tomorrow_first = _normalize_event(tomorrow_events[0], tz) if tomorrow_events else None

    # Mark past events so the template can mute them
    now_minutes = now_local.hour * 60 + now_local.minute
    for e in today_events:
        if e["start_minutes"] is not None:
            e["is_past"] = e["start_minutes"] < now_minutes
        else:
            e["is_past"] = False

    return {
        "configured": True,
        "today": today_events,
        "tomorrow_first": tomorrow_first,
    }


def _list_events(service, calendar_id, time_min, time_max, tz_name, max_results=50):
    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
            timeZone=tz_name,
        )
        .execute()
    )
    return result.get("items", [])


def _normalize_event(event: dict, tz: ZoneInfo) -> dict:
    """Convert a Google Calendar event into our flat dict format."""
    start = event["start"].get("dateTime") or event["start"].get("date", "")
    summary = event.get("summary", "(no title)")
    location = event.get("location", "")

    start_minutes = None
    if "T" in start:
        try:
            dt = datetime.fromisoformat(start)
            if dt.tzinfo is not None:
                dt = dt.astimezone(tz)
            time_str = dt.strftime("%H:%M")
            start_minutes = dt.hour * 60 + dt.minute
        except ValueError:
            time_str = start[11:16]
    else:
        time_str = "All day"

    return {
        "time": time_str,
        "start_minutes": start_minutes,
        "summary": summary,
        "location": location,
        "is_past": False,
    }


def to_text(data: dict) -> str:
    if not data or not data.get("configured"):
        return "[Calendar not configured]"
    lines = ["TODAY'S AGENDA:"]
    if data["today"]:
        for e in data["today"]:
            loc = f" @ {e['location']}" if e["location"] else ""
            lines.append(f"  {e['time']} — {e['summary']}{loc}")
    else:
        lines.append("  No events scheduled.")
    lines.append("")
    lines.append("TOMORROW'S FIRST EVENT:")
    if data["tomorrow_first"]:
        e = data["tomorrow_first"]
        lines.append(f"  {e['time']} — {e['summary']}")
    else:
        lines.append("  Nothing scheduled.")
    return "\n".join(lines)
