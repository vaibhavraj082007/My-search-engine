"""Weather API – proxy to Open-Meteo with 15-minute in-memory cache."""

import time

import httpx
from fastapi import APIRouter, Query

router = APIRouter()

# In-memory cache: key → (timestamp, data)
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 15 * 60  # 15 minutes in seconds

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _cache_key(lat: float, lon: float) -> str:
    """Round to 1 decimal place for cache grouping."""
    return f"{round(lat, 1)},{round(lon, 1)}"


def _get_cached(key: str) -> dict | None:
    """Return cached data if still valid, else None."""
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        else:
            del _cache[key]
    return None


@router.get("/api/weather")
async def weather(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    key = _cache_key(lat, lon)

    # Check cache
    cached = _get_cached(key)
    if cached is not None:
        return cached

    # Fetch from Open-Meteo
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,wind_speed_10m,wind_direction_10m,rain,cloud_cover,weather_code,is_day",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code,rain_sum,wind_speed_10m_max",
        "forecast_days": 16,
        "timezone": "auto",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        raw = resp.json()

    # Transform into our API shape
    current_data = raw.get("current", {})
    daily_data = raw.get("daily", {})

    current = {
        "temperature": current_data.get("temperature_2m"),
        "wind_speed": current_data.get("wind_speed_10m"),
        "wind_direction": current_data.get("wind_direction_10m"),
        "rain": current_data.get("rain"),
        "cloud_cover": current_data.get("cloud_cover"),
        "weather_code": current_data.get("weather_code"),
        "is_day": current_data.get("is_day"),
    }

    # Build daily forecast list
    daily = []
    dates = daily_data.get("time", [])
    temp_maxes = daily_data.get("temperature_2m_max", [])
    temp_mins = daily_data.get("temperature_2m_min", [])
    weather_codes = daily_data.get("weather_code", [])
    rain_sums = daily_data.get("rain_sum", [])
    wind_maxes = daily_data.get("wind_speed_10m_max", [])

    for i in range(len(dates)):
        daily.append(
            {
                "date": dates[i],
                "temp_max": temp_maxes[i] if i < len(temp_maxes) else None,
                "temp_min": temp_mins[i] if i < len(temp_mins) else None,
                "weather_code": weather_codes[i] if i < len(weather_codes) else None,
                "rain_sum": rain_sums[i] if i < len(rain_sums) else None,
                "wind_speed_max": wind_maxes[i] if i < len(wind_maxes) else None,
            }
        )

    result = {
        "current": current,
        "daily": daily,
        "timezone": raw.get("timezone"),
        "utc_offset_seconds": raw.get("utc_offset_seconds"),
    }

    # Cache it
    _cache[key] = (time.time(), result)

    return result
