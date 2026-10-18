"""
Real live providers - Open-Meteo (weather), Aladhan (prayer times, qibla, Hijri)
Keyless, with timeouts, retries, explicit data unavailable result.
"""

from typing import Any, Dict

import httpx

TIMEOUT = 5


def get_weather_real(lat: float = 21.35, lon: float = 39.98) -> Dict[str, Any]:
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,uv_index"
        r = httpx.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        current = data.get("current", {})
        return {
            "location": f"{lat},{lon}",
            "temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "humidity_percent": current.get("relative_humidity_2m"),
            "uv_index": current.get("uv_index"),
            "timestamp": current.get("time"),
            "data_source": "real",
        }
    except Exception as e:
        return {"error": "data unavailable", "exception": str(e), "data_source": "real"}


def get_prayer_times_real(lat: float = 21.35, lon: float = 39.98) -> Dict[str, Any]:
    try:
        url = f"http://api.aladhan.com/v1/timings?latitude={lat}&longitude={lon}&method=4"
        r = httpx.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        timings = data.get("data", {}).get("timings", {})
        return {
            "location": f"{lat},{lon}",
            "fajr": timings.get("Fajr"),
            "dhuhr": timings.get("Dhuhr"),
            "asr": timings.get("Asr"),
            "maghrib": timings.get("Maghrib"),
            "isha": timings.get("Isha"),
            "data_source": "real",
        }
    except Exception as e:
        return {"error": "data unavailable", "exception": str(e), "data_source": "real"}


def get_qibla_real(lat: float = 21.35, lon: float = 39.98) -> Dict[str, Any]:
    try:
        url = f"http://api.aladhan.com/v1/qibla/{lat}/{lon}"
        r = httpx.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return {"qibla": data.get("data"), "data_source": "real"}
    except Exception as e:
        return {"error": "data unavailable", "exception": str(e), "data_source": "real"}


def get_hijri_real(date: str = None) -> Dict[str, Any]:
    try:
        if date is None:
            from datetime import datetime

            date = datetime.utcnow().strftime("%d-%m-%Y")
        url = f"http://api.aladhan.com/v1/gToH/{date}"
        r = httpx.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return {
            "hijri": data.get("data", {}).get("hijri"),
            "data_source": "real",
            "disclaimer": "قد تختلف يوما عن الرؤية",
        }
    except Exception as e:
        return {"error": "data unavailable", "exception": str(e), "data_source": "real"}


def get_fleet_real() -> Dict[str, Any]:
    from rafiq.config import settings

    if not settings.RAFIQ_FLEET_URL:
        return {
            "error": "data unavailable",
            "reason": "RAFIQ_FLEET_URL not set",
            "data_source": "real",
        }
    try:
        r = httpx.get(settings.RAFIQ_FLEET_URL, timeout=TIMEOUT)
        r.raise_for_status()
        return {"data": r.json(), "data_source": "real"}
    except Exception as e:
        return {"error": "data unavailable", "exception": str(e), "data_source": "real"}
