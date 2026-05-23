"""
Weather collector — Open-Meteo API.

Returns structured dict; use to_text() for plaintext dumps.
Docs: https://open-meteo.com/en/docs
"""

import requests
from datetime import datetime

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


def collect_weather(cfg: dict) -> dict:
    """Fetch weather and return structured dict."""
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

    # Parse today (index 0) and next 3 days
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


def to_text(data: dict) -> str:
    """Plaintext rendering for --collect dumps."""
    if not data:
        return "[No weather data]"
    cur = data["current"]
    today = data["today"]
    lines = [
        f"Location: {data['location']}",
        f"Current: {cur['temperature']}°C (feels {cur['feels_like']}°C), {cur['description']}",
        f"Wind: {cur['wind']} km/h (gusts {cur['wind_gusts']}), Humidity: {cur['humidity']}%",
    ]
    if today:
        lines.append(
            f"Today: {today['temp_min']}–{today['temp_max']}°C, {today['description']}, "
            f"Rain: {today['precip_mm']}mm ({today['precip_prob']}%), "
            f"UV: {today['uv_max']}, Sun: {today['sunrise']} → {today['sunset']}"
        )
    for day in data.get("upcoming", []):
        lines.append(
            f"{day['label']}: {day['temp_min']}–{day['temp_max']}°C, {day['description']}, "
            f"Rain: {day['precip_mm']}mm ({day['precip_prob']}%)"
        )
    return "\n".join(lines)
