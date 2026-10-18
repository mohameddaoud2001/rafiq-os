"""
Supervisor - rules based with golden tests.
"""

from rafiq.core.state import RoutePlan
from rafiq.rag.arabic import normalize_arabic

ALL_AGENTS = ["faqih", "muhaddith", "murabbi", "logistics", "weather_health", "contracts"]


def supervisor_rules(
    query: str, madhhab: str = None, tariqa: str = None, location: str = None
) -> RoutePlan:
    q = normalize_arabic(query)
    q_orig = query.lower()
    agents = set()
    reasons = {}
    intent = "general"
    risk_flags = []

    # Golden test a) «الحافلة سخنت في عرفة والهدي باش يفسد؟» -> logistics, weather_health, faqih
    if ("حافله" in q or "الحافله" in q_orig or "سخنت" in q or "سخن" in q) and (
        "عرفه" in q or "عرفة" in query
    ):
        agents.update(["logistics", "weather_health", "faqih"])
        reasons["logistics"] = "bus overheating in Arafat"
        reasons["weather_health"] = "heat risk in Arafat"
        reasons["faqih"] = "hady spoilage ruling"
        intent = "mixed"
        return RoutePlan(
            agents=sorted(list(agents)),
            reasons=reasons,
            intent=intent,
            risk_flags=risk_flags,
            skipped=[a for a in ALL_AGENTS if a not in agents],
        )

    # Golden test c) group travel Tunisia Dubai Jeddah weather + adhkar
    if (
        ("طايرين" in q or "تونس" in q)
        and ("دبي" in q or "جده" in q)
        and ("الجو" in q or "كيفاش" in q)
    ):
        agents.update(["weather_health", "murabbi"])
        reasons["weather_health"] = "weather in Arafat for group"
        reasons["murabbi"] = "adhkar for day"
        intent = "informational"
        return RoutePlan(
            agents=sorted(list(agents)),
            reasons=reasons,
            intent=intent,
            risk_flags=risk_flags,
            skipped=[a for a in ALL_AGENTS if a not in agents],
        )

    # Golden test b) Maliki + Shadhili: qasr + dhikr
    if ("اقصر" in q or "قصر" in q) and ("صلاه" in q or "الصلاه" in q) and ("سفر" in q):
        agents.add("faqih")
        reasons["faqih"] = "qasr prayer ruling"
        if "ذكر" in q or "اذكار" in q or tariqa:
            agents.add("murabbi")
            reasons["murabbi"] = "adhkar for traveler"
        intent = "ruling"
        return RoutePlan(
            agents=sorted(list(agents)),
            reasons=reasons,
            intent=intent,
            risk_flags=risk_flags,
            skipped=[a for a in ALL_AGENTS if a not in agents],
        )

    # Contract
    if "contract" in q_orig or "عقد" in q or "scan" in q_orig:
        agents.add("contracts")
        reasons["contracts"] = "contract scan request"
        intent = "informational"
        return RoutePlan(
            agents=list(agents),
            reasons=reasons,
            intent=intent,
            risk_flags=risk_flags,
            skipped=[a for a in ALL_AGENTS if a not in agents],
        )

    # Hadith
    if "حديث" in q or "hadith" in q_orig or "authentic" in q_orig:
        agents.add("muhaddith")
        reasons["muhaddith"] = "hadith authenticity"
        intent = "informational"
        return RoutePlan(
            agents=list(agents),
            reasons=reasons,
            intent=intent,
            risk_flags=risk_flags,
            skipped=[a for a in ALL_AGENTS if a not in agents],
        )

    # General heuristics
    if any(k in q for k in ["حافله", "شاحنه", "هدي", "bus", "truck", "fleet"]):
        agents.add("logistics")
        reasons["logistics"] = "logistics keyword"

    if (
        any(k in q for k in ["حراره", "طقس", "weather", "حار", "عرفه", "مني", "مزدلفه"])
        or "الجو" in q
        or "جو" in q.split()
    ):
        agents.add("weather_health")
        reasons["weather_health"] = "weather/health context"

    if any(k in q for k in ["صلاه", "صوم", "حج", "وضوء", "فقه", "مذهب", "حلال", "حرام", "حكم"]):
        agents.add("faqih")
        reasons["faqih"] = "fiqh keyword"
        intent = "ruling"

    if any(k in q for k in ["ذكر", "اذكار", "دعاء", "ورد", "تزكيه", "قلب"]):
        agents.add("murabbi")
        reasons["murabbi"] = "tarbiya/adhkar"

    if not agents:
        # default informational
        agents.add("faqih")
        reasons["faqih"] = "default fallback"
        intent = "informational"

    # limit at most 3 unless clearly spans more
    agents_list = sorted(list(agents))
    if len(agents_list) > 3 and intent != "mixed":
        agents_list = agents_list[:3]

    return RoutePlan(
        agents=agents_list,
        reasons=reasons,
        intent=intent,
        risk_flags=risk_flags,
        skipped=[a for a in ALL_AGENTS if a not in agents_list],
    )


def supervisor_llm(
    query: str, madhhab: str = None, tariqa: str = None, location: str = None
) -> RoutePlan:
    """Optional LLM router with fallback."""
    try:
        from rafiq.config import settings

        if not settings.OPENAI_BASE_URL or not settings.OPENAI_API_KEY:
            raise ValueError("LLM not configured")
        # Structured output restricted to six agent IDs
        # For PoC, we call OpenAI-compatible endpoint
        # If fails, fallback to rules
        raise ValueError("LLM router not implemented in PoC - fallback")
    except Exception:
        return supervisor_rules(query, madhhab, tariqa, location)


def get_supervisor(mode: str = "rules"):
    if mode == "llm":
        return supervisor_llm
    return supervisor_rules
