"""
Muhaddith agent - isnad check and grade lookup.
Uses fictional narrators only for PoC.
"""

import json
import pathlib

from rafiq.core.messages import BANNERS, ERRORS
from rafiq.core.state import AgentOutput, Finding

RIJAL_PATH = pathlib.Path("data/rijal/rijal.json")


def load_rijal():
    if not RIJAL_PATH.exists():
        return {}
    with open(RIJAL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def check_isnad(chain: list) -> dict:
    """
    chain: list of narrator ids in order
    Returns per adjacent pair: connected_plausible | break_suspected | insufficient_data
    Uses life-span overlap and city co-presence windows.
    """
    rijal = load_rijal()
    result = []
    for i in range(len(chain) - 1):
        a_id = chain[i]
        b_id = chain[i + 1]
        a = rijal.get(a_id)
        b = rijal.get(b_id)
        if not a or not b:
            result.append({"pair": (a_id, b_id), "status": "insufficient_data"})
            continue
        # simple overlap check: birth/death years
        # If lifespans overlap and share city at some point -> plausible
        a_birth = a.get("birth_year", 0)
        a_death = a.get("death_year", 0)
        b_birth = b.get("birth_year", 0)
        b_death = b.get("death_year", 0)
        overlap = not (a_death < b_birth or b_death < a_birth)
        cities_a = set(a.get("cities", []))
        cities_b = set(b.get("cities", []))
        co_presence = bool(cities_a & cities_b)
        if overlap and co_presence:
            status = "connected_plausible"
        elif not overlap:
            status = "break_suspected"
        else:
            status = "insufficient_data"
        result.append(
            {"pair": (a_id, b_id), "status": status, "overlap": overlap, "co_presence": co_presence}
        )
    return {"chain": chain, "checks": result}


def grade_lookup(hadith_id: str) -> dict:
    """
    Grade only from sourced record, otherwise not-found phrase.
    """
    # In PoC, we have no hadith db, so return not-found
    # But we keep structure
    return {
        "hadith_id": hadith_id,
        "grade": None,
        "message": ERRORS["not_found"],
        "note": BANNERS["hadith_not_found"],
    }


def viral_hadith_check(text: str) -> dict:
    # Empty seed list per spec, "no match" never implies authenticity
    known_fabricated = []  # empty seed
    for fab in known_fabricated:
        if fab in text:
            return {"match": True, "fabricated": True}
    return {"match": False, "note": BANNERS["hadith_not_found"]}


def muhaddith_agent(query: str, chain: list = None) -> AgentOutput:
    findings = []
    if chain:
        chk = check_isnad(chain)
        # create a synthetic finding for audit
        findings.append(
            Finding(
                source_id=f"isnad_check_{'_'.join(chain)}",
                excerpt=str(chk),
                work="rijal",
                verified=False,
                topic_tags=["isnad"],
            )
        )
    else:
        # grade lookup attempt
        g = grade_lookup(query)
        findings.append(
            Finding(
                source_id=f"hadith_grade_{hash(query)}",
                excerpt=g["message"],
                work="hadith_db",
                verified=False,
                topic_tags=["hadith_grade"],
            )
        )

    return AgentOutput(
        agent="muhaddith",
        status="ok",
        findings=findings,
        informational_only=True,
        disclaimers=[BANNERS["hadith_not_found"], BANNERS["unverified"]],
        data_source="db",
    )
