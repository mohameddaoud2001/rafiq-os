"""
Toolbus - agents reach data ONLY through here.
Supports inproc and http mode via langchain-mcp-adapters.
"""

from rafiq.config import settings


# Inproc direct calls
def search_passages_tool(query: str, madhhab: str = None, limit: int = 5):
    from rafiq.rag.madhhab_stores import search_all_madhhabs, search_passages

    if madhhab:
        return search_passages(madhhab, query, limit)
    else:
        return search_all_madhhabs(query, limit)


def get_passage_tool(passage_id: str, madhhab: str):
    from rafiq.rag.madhhab_stores import search_passages

    # simple: search by id
    res = search_passages(madhhab, passage_id, limit=5)
    for p in res:
        if p.id == passage_id:
            return p
    return None


def get_ayah_ref(sura: int, ayah: int):
    # In real mode, return from Quran.com API placeholder
    # In sim mode, placeholder
    return {
        "sura": sura,
        "ayah": ayah,
        "text": (
            f"[SIM placeholder Qur'an {sura}:{ayah} - real mode returns verbatim from provider]"
        ),
        "data_source": "sim",
    }


def get_hadith_record(collection: str, number: str):
    return {
        "collection": collection,
        "number": number,
        "text": "[SIM placeholder - real mode returns verbatim]",
        "data_source": "sim",
    }


def prayer_times_tool(location: str = "عرفة"):
    if settings.RAFIQ_LIVE == "real":
        from rafiq.live.real import get_prayer_times_real

        return get_prayer_times_real()
    else:
        from rafiq.live.sim import get_prayer_times_sim

        return get_prayer_times_sim(location)


def qibla_tool(lat: float = 21.35, lon: float = 39.98):
    if settings.RAFIQ_LIVE == "real":
        from rafiq.live.real import get_qibla_real

        return get_qibla_real(lat, lon)
    else:
        return {"qibla_direction": 290.5, "location": f"{lat},{lon}", "data_source": "sim"}


def hijri_tool(date: str = None):
    if settings.RAFIQ_LIVE == "real":
        from rafiq.live.real import get_hijri_real

        return get_hijri_real(date)
    else:
        return {
            "hijri": "1446-12-09",
            "gregorian": date,
            "data_source": "sim",
            "disclaimer": "قد تختلف يوما عن الرؤية",
        }


def council_resolutions_tool(topic: str = None):
    # seed placeholders, resolution_no null
    return [
        {
            "topic": topic or "general",
            "resolution_no": None,
            "text": "قرار مجمعي توضيحي غير محقق",
            "verified": False,
        }
    ]


def weather_tool(location: str = "عرفة"):
    if settings.RAFIQ_LIVE == "real":
        from rafiq.live.real import get_weather_real

        return get_weather_real()
    else:
        from rafiq.live.sim import get_weather_sim

        return get_weather_sim(location)


def fleet_status_tool():
    if settings.RAFIQ_LIVE == "real":
        from rafiq.live.real import get_fleet_real

        return get_fleet_real()
    else:
        from rafiq.live.sim import get_fleet_sim

        return get_fleet_sim()


def truck_temps_tool():
    from rafiq.live.sim import get_truck_temps_sim

    return get_truck_temps_sim()


def well_sensors_tool():
    from rafiq.live.sim import get_well_sensors_sim

    return get_well_sensors_sim()


# Registry for dynamic discovery
TOOLS = {
    "search_passages": search_passages_tool,
    "get_passage": get_passage_tool,
    "get_ayah_ref": get_ayah_ref,
    "get_hadith_record": get_hadith_record,
    "prayer_times": prayer_times_tool,
    "qibla": qibla_tool,
    "hijri_from_gregorian": hijri_tool,
    "council_resolutions": council_resolutions_tool,
    "weather": weather_tool,
    "fleet_status": fleet_status_tool,
    "truck_temps": truck_temps_tool,
    "well_sensors": well_sensors_tool,
}


def discover_tools():
    return list(TOOLS.keys())


def call_tool(name: str, **kwargs):
    if name not in TOOLS:
        raise ValueError(f"Tool {name} not found. Available: {discover_tools()}")
    return TOOLS[name](**kwargs)
