"""
Weather collector — Open-Meteo (primary), wttr.in (fallback 1), MET Norway (fallback 2).

Returns structured dict; use to_text() for plaintext dumps.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

MET_SYMBOLS = {
    "clearsky": "Clear sky", "fair": "Mainly clear", "partlycloudy": "Partly cloudy",
    "cloudy": "Overcast", "fog": "Foggy",
    "lightrain": "Light rain", "rain": "Moderate rain", "heavyrain": "Heavy rain",
    "lightrainshowers": "Slight rain showers", "rainshowers": "Moderate rain showers",
    "heavyrainshowers": "Violent rain showers",
    "lightsleet": "Light freezing rain", "sleet": "Sleet",
    "lightsnow": "Slight snow", "snow": "Moderate snow", "heavysnow": "Heavy snow",
    "lightsnowshowers": "Slight snow showers", "snowshowers": "Heavy snow showers",
    "thunderstorm": "Thunderstorm", "thunder": "Thunderstorm",
}


def _met_desc(symbol_code: str) -> str:
    base = symbol_code.split("_")[0] if symbol_code else ""
    return MET_SYMBOLS.get(base, symbol_code or "Unknown")


def collect_weather(cfg: dict) -> dict:
    """Fetch weather with fallback chain: Open-Meteo → wttr.in → MET Norway."""
    errors = []

    for label, fn in [
        ("open-meteo", _collect_open_meteo),
        ("wttr.in",    _collect_wttr),
        ("met-norway", _collect_met_norway),
    ]:
        try:
            result = fn(cfg)
            if label != "open-meteo":
                logger.warning("Weather: using fallback source %s", label)
            return result
        except Exception as exc:
            logger.warning("Weather %s failed: %s", label, exc)
            errors.append(f"{label}: {exc}")

    raise RuntimeError(f"All weather sources failed: {'; '.join(errors)}")


def _collect_open_meteo(cfg: dict) -> dict:
    """Primary: Open-Meteo — no API key required."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": cfg["latitude"],
        "longitude": cfg["longitude"],
        "timezone": cfg["timezone"],
        "current": ",".join([
            "temperature_2m", "relative_humidity_2m", "apparent_temperature",
            "weather_code", "wind_speed_10m", "wind_gusts_10m",
        ]),
        "daily": ",".join([
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "apparent_temperature_max", "apparent_temperature_min",
            "sunrise", "sunset", "precipitation_sum",
            "precipitation_probability_max", "wind_speed_10m_max", "uv_index_max",
        ]),
        "forecast_days": 4,
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    current = data["current"]
    daily = data["daily"]

    forecast_days = []
    for i in range(len(daily["time"])):
        date_str = daily["time"][i]
        sunrise = daily["sunrise"][i].split("T")[1] if daily["sunrise"][i] else None
        sunset = daily["sunset"][i].split("T")[1] if daily["sunset"][i] else None
        forecast_days.append({
            "date": date_str,
            "label": "Today" if i == 0 else datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %b %d"),
            "weather_code": daily["weather_code"][i],
            "description": WMO_CODES.get(daily["weather_code"][i], f"Code {daily['weather_code'][i]}"),
            "temp_min": daily["temperature_2m_min"][i],
            "temp_max": daily["temperature_2m_max"][i],
            "precip_mm": daily["precipitation_sum"][i] or 0,
            "precip_prob": daily["precipitation_probability_max"][i] or 0,
            "wind_max": daily["wind_speed_10m_max"][i],
            "uv_max": daily["uv_index_max"][i] or 0,
            "sunrise": sunrise,
            "sunset": sunset,
        })

    return {
        "location": cfg["location_name"],
        "source": "open-meteo",
        "current": {
            "temperature": current["temperature_2m"],
            "feels_like": current["apparent_temperature"],
            "weather_code": current["weather_code"],
            "description": WMO_CODES.get(current["weather_code"], f"Code {current['weather_code']}"),
            "wind": current["wind_speed_10m"],
            "wind_gusts": current["wind_gusts_10m"],
            "humidity": current["relative_humidity_2m"],
        },
        "today": forecast_days[0] if forecast_days else None,
        "upcoming": forecast_days[1:] if len(forecast_days) > 1 else [],
    }


def _collect_wttr(cfg: dict) -> dict:
    """Fallback 1: wttr.in — no API key required."""
    lat, lon = cfg["latitude"], cfg["longitude"]
    url = f"https://wttr.in/{lat},{lon}?format=j1"

    resp = requests.get(url, timeout=10, headers={"Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json()

    cur = data["current_condition"][0]
    cur_desc = cur.get("weatherDesc", [{}])[0].get("value", "")

    forecast_days = []
    for i, day in enumerate(data.get("weather", [])[:4]):
        date_str = day["date"]
        label = "Today" if i == 0 else datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %b %d")
        hourly = day.get("hourly", [])
        precip_mm = round(sum(float(h.get("precipMM", 0)) for h in hourly), 1)
        precip_prob = max((int(h.get("chanceofrain", 0)) for h in hourly), default=0)
        wind_max = max((float(h.get("windspeedKmph", 0)) for h in hourly), default=0)
        astro = day.get("astronomy", [{}])[0]
        forecast_days.append({
            "date": date_str,
            "label": label,
            "weather_code": None,
            "description": day.get("weatherDesc", [{}])[0].get("value", ""),
            "temp_min": float(day["mintempC"]),
            "temp_max": float(day["maxtempC"]),
            "precip_mm": precip_mm,
            "precip_prob": precip_prob,
            "wind_max": wind_max,
            "uv_max": float(day.get("uvIndex", 0)),
            "sunrise": astro.get("sunrise"),
            "sunset": astro.get("sunset"),
        })

    return {
        "location": cfg["location_name"],
        "source": "wttr.in",
        "current": {
            "temperature": float(cur["temp_C"]),
            "feels_like": float(cur["FeelsLikeC"]),
            "weather_code": None,
            "description": cur_desc,
            "wind": float(cur["windspeedKmph"]),
            "wind_gusts": float(cur.get("WindGustKmph", cur["windspeedKmph"])),
            "humidity": float(cur["humidity"]),
        },
        "today": forecast_days[0] if forecast_days else None,
        "upcoming": forecast_days[1:] if len(forecast_days) > 1 else [],
    }


def _collect_met_norway(cfg: dict) -> dict:
    """Fallback 2: MET Norway / Yr.no — no API key required, needs User-Agent."""
    lat = round(float(cfg["latitude"]), 4)
    lon = round(float(cfg["longitude"]), 4)
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

    resp = requests.get(
        url,
        params={"lat": lat, "lon": lon},
        headers={"User-Agent": "voice-journal/1.0"},
        timeout=10,
    )
    resp.raise_for_status()
    timeseries = resp.json()["properties"]["timeseries"]

    def _parse_dt(entry):
        return datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))

    now = datetime.now(timezone.utc)
    current_entry = min(timeseries, key=lambda e: abs((_parse_dt(e) - now).total_seconds()))
    cur_instant = current_entry["data"]["instant"]["details"]
    cur_symbol = current_entry["data"].get("next_1_hours", {}).get("summary", {}).get("symbol_code", "")

    # Group timeseries by date
    buckets = defaultdict(list)
    for entry in timeseries:
        buckets[_parse_dt(entry).date().isoformat()].append(entry)

    today_str = now.date().isoformat()
    sorted_days = sorted(k for k in buckets if k >= today_str)[:4]

    forecast_days = []
    for i, day_str in enumerate(sorted_days):
        entries = buckets[day_str]
        temps = [e["data"]["instant"]["details"]["air_temperature"] for e in entries]
        precips = [
            e["data"].get("next_1_hours", {}).get("details", {}).get("precipitation_amount", 0)
            for e in entries
        ]
        winds_ms = [e["data"]["instant"]["details"].get("wind_speed", 0) for e in entries]
        midday_dt = datetime.fromisoformat(f"{day_str}T12:00:00+00:00")
        midday = min(entries, key=lambda e: abs((_parse_dt(e) - midday_dt).total_seconds()))
        symbol = (
            midday["data"].get("next_1_hours") or midday["data"].get("next_6_hours") or {}
        ).get("summary", {}).get("symbol_code", "")
        label = "Today" if i == 0 else datetime.strptime(day_str, "%Y-%m-%d").strftime("%A %b %d")
        forecast_days.append({
            "date": day_str,
            "label": label,
            "weather_code": None,
            "description": _met_desc(symbol),
            "temp_min": round(min(temps), 1),
            "temp_max": round(max(temps), 1),
            "precip_mm": round(sum(precips), 1),
            "precip_prob": None,
            "wind_max": round(max(winds_ms) * 3.6, 1),
            "uv_max": None,
            "sunrise": None,
            "sunset": None,
        })

    return {
        "location": cfg["location_name"],
        "source": "met-norway",
        "current": {
            "temperature": round(cur_instant["air_temperature"], 1),
            "feels_like": round(cur_instant["air_temperature"], 1),
            "weather_code": None,
            "description": _met_desc(cur_symbol),
            "wind": round(cur_instant.get("wind_speed", 0) * 3.6, 1),
            "wind_gusts": round(cur_instant.get("wind_speed_of_gust", cur_instant.get("wind_speed", 0)) * 3.6, 1),
            "humidity": round(cur_instant.get("relative_humidity", 0), 1),
        },
        "today": forecast_days[0] if forecast_days else None,
        "upcoming": forecast_days[1:] if len(forecast_days) > 1 else [],
    }


def to_text(data: dict) -> str:
    """Plaintext rendering for --collect dumps."""
    if not data:
        return "[No weather data]"
    cur = data["current"]
    today = data["today"]
    source = data.get("source", "")
    source_tag = f" [{source}]" if source and source != "open-meteo" else ""
    lines = [
        f"Location: {data['location']}{source_tag}",
        f"Current: {cur['temperature']}°C (feels {cur['feels_like']}°C), {cur['description']}",
        f"Wind: {cur['wind']} km/h (gusts {cur['wind_gusts']}), Humidity: {cur['humidity']}%",
    ]
    if today:
        precip_prob = f" ({today['precip_prob']}%)" if today.get("precip_prob") is not None else ""
        uv = f", UV: {today['uv_max']}" if today.get("uv_max") is not None else ""
        sun = f", Sun: {today['sunrise']} → {today['sunset']}" if today.get("sunrise") else ""
        lines.append(
            f"Today: {today['temp_min']}–{today['temp_max']}°C, {today['description']}, "
            f"Rain: {today['precip_mm']}mm{precip_prob}{uv}{sun}"
        )
    for day in data.get("upcoming", []):
        precip_prob = f" ({day['precip_prob']}%)" if day.get("precip_prob") is not None else ""
        lines.append(
            f"{day['label']}: {day['temp_min']}–{day['temp_max']}°C, {day['description']}, "
            f"Rain: {day['precip_mm']}mm{precip_prob}"
        )
    return "\n".join(lines)
