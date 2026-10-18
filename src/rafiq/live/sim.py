"""
Sim live data - deterministic seeded near Arafat/Mina/Muzdalifah.
"""

import datetime
from typing import Any, Dict, List


def get_weather_sim(location: str = "عرفة") -> Dict[str, Any]:
    # Deterministic hot day in Arafat
    return {
        "location": location,
        "temperature_c": 42.5,
        "apparent_temperature_c": 48.0,
        "humidity_percent": 25,
        "uv_index": 10,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "data_source": "sim",
        "disclaimer": "البيانات محاكاة",
    }


def get_fleet_sim() -> List[Dict[str, Any]]:
    return [
        {
            "bus_id": "حافلة-1",
            "location": "عرفة",
            "engine_temp_c": 105,
            "status": "OVERHEAT",
            "lat": 21.355,
            "lon": 39.983,
        },
        {
            "bus_id": "حافلة-2",
            "location": "منى",
            "engine_temp_c": 85,
            "status": "OK",
            "lat": 21.41,
            "lon": 39.89,
        },
    ]


def get_truck_temps_sim() -> List[Dict[str, Any]]:
    # Fixed base (9 Dhu al-Hijjah 1446) so repeated calls match and certs verify
    now = datetime.datetime(2025, 6, 5, 12, 0, 0)
    # truck هدي-1 has breach window, هدي-2 intact
    return [
        {
            "truck_id": "هدي-1",
            "readings": [
                {"ts": (now - datetime.timedelta(minutes=60)).isoformat(), "temp_c": 2.0},
                {
                    "ts": (now - datetime.timedelta(minutes=30)).isoformat(),
                    "temp_c": 8.5,
                },  # breach >4C
                {"ts": now.isoformat(), "temp_c": 3.0},
            ],
            "threshold_chilled": {"min": 0, "max": 4},
            "status": "breached",
            "data_source": "sim",
        },
        {
            "truck_id": "هدي-2",
            "readings": [
                {"ts": (now - datetime.timedelta(minutes=60)).isoformat(), "temp_c": 1.5},
                {"ts": (now - datetime.timedelta(minutes=30)).isoformat(), "temp_c": 2.0},
                {"ts": now.isoformat(), "temp_c": 1.8},
            ],
            "threshold_chilled": {"min": 0, "max": 4},
            "status": "cold_chain_intact",
            "data_source": "sim",
        },
    ]


def get_well_sensors_sim() -> Dict[str, Any]:
    return {
        "well_id": "بئر-عرفة-1",
        "level_percent": 78,
        "data_source": "sim",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }


def get_prayer_times_sim(location: str = "عرفة") -> Dict[str, Any]:
    return {
        "location": location,
        "fajr": "04:30",
        "dhuhr": "12:15",
        "asr": "15:40",
        "maghrib": "18:50",
        "isha": "20:20",
        "data_source": "sim",
        "hijri_disclaimer": "التواريخ الهجرية المحسوبة قد تختلف يوما عن الرؤية",
    }
