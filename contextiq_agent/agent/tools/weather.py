"""Weather tool — OpenWeatherMap 5-day forecast API (free tier)."""

from __future__ import annotations

from strands import tool

# Set WEATHER_MOCK=true to return hardcoded forecast without a real API key.
# Mock returns: rain on 2026-04-22, clear on 2026-04-23 and 2026-04-24.
_MOCK_FORECAST = {
    "2026-04-22": {"temperature_f": 54, "condition": "light rain", "rain": True, "precipitation_pct": 90},
    "2026-04-23": {"temperature_f": 58, "condition": "clear sky", "rain": False, "precipitation_pct": 5},
    "2026-04-24": {"temperature_f": 61, "condition": "few clouds", "rain": False, "precipitation_pct": 10},
}


@tool
def check_weather(
    location: str, date: str = None
) -> dict:
    """Check weather forecast for a location.

    Args:
        location: City name (e.g. "Seattle" or "Seattle, WA").
        date: Optional ISO date (YYYY-MM-DD) to get forecast for that day.
              Omit for current weather. Supports up to 5 days ahead.

    Returns:
        Dict with temperature, conditions, rain flag, and wind,
        or 'error' key if the weather service is unavailable.
    """
    import os
    if os.environ.get("WEATHER_MOCK", "").lower() == "true":
        if date and date in _MOCK_FORECAST:
            return {"location": location, "date": date, **_MOCK_FORECAST[date]}
        return {
            "location": location, "date": date or "now",
            "temperature_f": 58, "condition": "clear sky",
            "rain": False, "precipitation_pct": 5,
        }

    from contextiq_agent.agent.config import get_config

    config = get_config()

    if not config.openweathermap_api_key:
        return {"error": "Weather API key not configured"}

    try:
        import httpx

        resp = httpx.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={
                "q": location,
                "appid": config.openweathermap_api_key,
                "units": "imperial",
                "cnt": 40,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("list", [])

        if date:
            # Group 3-hour slots by day
            days: dict = {}
            for item in items:
                day = item["dt_txt"][:10]
                if day not in days:
                    days[day] = {"temps": [], "conditions": [], "rain": False}
                days[day]["temps"].append(item["main"]["temp"])
                desc = item["weather"][0]["description"]
                days[day]["conditions"].append(desc)
                if any(w in desc.lower() for w in ["rain", "storm", "drizzle", "shower"]):
                    days[day]["rain"] = True

            if date in days:
                info = days[date]
                avg_temp = round(sum(info["temps"]) / len(info["temps"]))
                main_cond = max(set(info["conditions"]), key=info["conditions"].count)
                return {
                    "location": location,
                    "date": date,
                    "temperature_f": avg_temp,
                    "condition": main_cond,
                    "rain": info["rain"],
                    "precipitation_pct": 100 if info["rain"] else 0,
                }

            # Requested date not in 5-day window — return available days
            summary = []
            for d, info in sorted(days.items()):
                avg = round(sum(info["temps"]) / len(info["temps"]))
                cond = max(set(info["conditions"]), key=info["conditions"].count)
                rain_flag = " (rain)" if info["rain"] else ""
                summary.append(f"{d}: {avg}°F, {cond}{rain_flag}")
            return {
                "location": location,
                "note": f"Date {date} not in 5-day forecast window",
                "available_forecast": summary,
            }

        # No date — return current conditions from first slot
        current = items[0] if items else {}
        desc = current.get("weather", [{}])[0].get("description", "unknown")
        return {
            "location": location,
            "date": "now",
            "temperature_f": round(current.get("main", {}).get("temp", 0)),
            "condition": desc,
            "rain": any(w in desc.lower() for w in ["rain", "storm", "drizzle", "shower"]),
            "wind_mph": round(current.get("wind", {}).get("speed", 0)),
        }

    except Exception as exc:
        return {"error": f"Weather data unavailable: {type(exc).__name__}: {exc}"}
