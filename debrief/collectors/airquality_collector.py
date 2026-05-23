"""
Air Quality collector — Open-Meteo Air Quality API.

Uses the same coordinates as weather. No API key required.
Docs: https://open-meteo.com/en/docs/air-quality-api
"""

import logging
import requests

logger = logging.getLogger("debrief.airquality")

# European AQI thresholds
AQI_LEVELS = [
    (0,  20,  "Good",     "🟢"),
    (21, 40,  "Fair",     "🟡"),
    (41, 60,  "Moderate", "🟠"),
    (61, 80,  "Poor",     "🔴"),
    (81, 100, "Very Poor","🟣"),
    (101, 9999, "Extremely Poor", "⚫"),
]


def _aqi_label(value: float) -> tuple[str, str]:
    for lo, hi, label, emoji in AQI_LEVELS:
        if lo <= value <= hi:
            return label, emoji
    return "Unknown", "⚪"


def collect_airquality(cfg: dict) -> dict:
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": cfg["latitude"],
        "longitude": cfg["longitude"],
        "current": "european_aqi,pm2_5,pm10",
        "timezone": cfg["timezone"],
    }

    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    current = data.get("current", {})
    aqi = current.get("european_aqi")
    pm25 = current.get("pm2_5")
    pm10 = current.get("pm10")

    if aqi is None:
        return {"available": False}

    label, emoji = _aqi_label(aqi)

    return {
        "available": True,
        "aqi": round(aqi),
        "label": label,
        "emoji": emoji,
        "pm25": round(pm25, 1) if pm25 is not None else None,
        "pm10": round(pm10, 1) if pm10 is not None else None,
    }


def to_text(data: dict) -> str:
    if not data or not data.get("available"):
        return "[Air quality unavailable]"
    parts = [f"AQI: {data['aqi']} — {data['label']}"]
    if data.get("pm25") is not None:
        parts.append(f"PM2.5: {data['pm25']} µg/m³")
    if data.get("pm10") is not None:
        parts.append(f"PM10: {data['pm10']} µg/m³")
    return ", ".join(parts)
