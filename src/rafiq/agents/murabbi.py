import json
import pathlib

from rafiq.core.messages import BANNERS, ERRORS
from rafiq.core.state import AgentOutput, Finding

ADHKAR_PATH = pathlib.Path("data/adhkar/seed.jsonl")


def load_adhkar():
    adhkar = []
    if not ADHKAR_PATH.exists():
        return adhkar
    with open(ADHKAR_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                adhkar.append(json.loads(line))
    return adhkar


def murabbi_agent(query: str, tariqa: str = None, time_context: str = None) -> AgentOutput:
    all_adhkar = load_adhkar()
    # filter general masnun, at most 8
    general = [a for a in all_adhkar if not a.get("tariqa_specific", False)]
    # tariqa handling per rule 9
    if tariqa:
        tariqa_specific = [
            a for a in all_adhkar if a.get("tariqa") == tariqa and a.get("ijaza_approved", False)
        ]
        # if none approved, add note
        if tariqa_specific:
            general.extend(tariqa_specific)
        # else note will be added

    selected = general[:8]

    findings = []
    for a in selected:
        findings.append(
            Finding(
                source_id=a.get("id", "adhkar"),
                excerpt=a.get("text", ""),
                work=a.get("work", "adhkar"),
                verified=a.get("verified", False),
                topic_tags=a.get("tags", []),
            )
        )

    disclaimers = [BANNERS["unverified"]]
    if tariqa:
        # check if any tariqa-specific not approved
        has_unapproved = any(
            ad.get("tariqa") == tariqa and not ad.get("ijaza_approved", False) for ad in all_adhkar
        )
        if has_unapproved:
            disclaimers.append(ERRORS["sufi_ijaza"])

    if not findings:
        return AgentOutput(
            agent="murabbi",
            status="not_found",
            findings=[],
            informational_only=True,
            disclaimers=disclaimers,
            data_source="db",
        )

    return AgentOutput(
        agent="murabbi",
        status="ok",
        findings=findings,
        informational_only=True,
        disclaimers=disclaimers,
        data_source="db",
    )
