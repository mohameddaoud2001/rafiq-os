from rafiq.core.messages import BANNERS
from rafiq.core.state import AgentOutput, Finding
from rafiq.live.real import get_weather_real
from rafiq.live.sim import get_weather_sim


def heat_stress_level(temp_c: float, apparent_c: float, humidity: float, uv: float) -> str:
    # configurable bands
    if apparent_c >= 45 or temp_c >= 42:
        return "extreme"
    elif apparent_c >= 38 or temp_c >= 38:
        return "high"
    elif apparent_c >= 32:
        return "moderate"
    else:
        return "low"


def weather_health_agent(query: str, location: str = "عرفة", live_mode: str = "sim") -> AgentOutput:
    if live_mode == "real":
        weather = get_weather_real()
    else:
        weather = get_weather_sim(location)

    if "error" in weather:
        return AgentOutput(
            agent="weather_health",
            status="insufficient_data",
            findings=[],
            informational_only=True,
            disclaimers=["data unavailable"],
            data_source=live_mode,
        )

    level = heat_stress_level(
        weather.get("temperature_c", 0),
        weather.get("apparent_temperature_c", 0),
        weather.get("humidity_percent", 0),
        weather.get("uv_index", 0),
    )

    guidance_map = {
        "extreme": "تجنب التعرض المباشر للشمس، أكثر من شرب الماء، اطلب المساعدة الطبية عند الحاجة",
        "high": "قلل النشاط في الشمس، اشرب ماء بانتظام، استرح في الظل",
        "moderate": "احرص على الترطيب والظل",
        "low": "الوضع طبيعي",
    }

    findings = [
        Finding(
            source_id=f"weather_{location}_{weather.get('timestamp', '')}",
            excerpt=(
                f"Temp {weather.get('temperature_c')}C apparent "
                f"{weather.get('apparent_temperature_c')}C humidity "
                f"{weather.get('humidity_percent')}% UV {weather.get('uv_index')} "
                f"stress {level} - {guidance_map[level]}"
            ),
            work="weather",
            verified=False,
            topic_tags=["weather", "health", level],
        )
    ]

    disclaimers = [
        BANNERS["sim_data"] if live_mode == "sim" else "",
        "إرشاد عام غير طبي - اطلب المساعدة الطبية عند الحاجة",
    ]

    return AgentOutput(
        agent="weather_health",
        status="ok",
        findings=findings,
        informational_only=True,
        disclaimers=[d for d in disclaimers if d],
        data_source=live_mode,
        extra={"weather": weather, "heat_level": level},
    )
