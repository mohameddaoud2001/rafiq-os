"""
LangGraph core: guard_in -> supervisor -> Send fan-out to agents -> verifier
-> guard_out -> dossier -> mufti_review (interrupt) -> END
"""

import pathlib
import sqlite3
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from rafiq.config import settings
from rafiq.core.audit import append_audit, get_last_hash
from rafiq.core.dossier import add_decision
from rafiq.core.guardrails import check_all_input, check_output_adab
from rafiq.core.messages import BANNERS, ERRORS
from rafiq.core.state import AgentOutput, RoutePlan
from rafiq.core.supervisor import get_supervisor
from rafiq.core.verifier import verify_agent_output

DB_PATH = pathlib.Path("data/db/graph_checkpoints.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class GraphState(TypedDict, total=False):
    query: str
    madhhab: Optional[str]
    tariqa: Optional[str]
    location: Optional[str]
    route_plan: Optional[Dict[str, Any]]
    agent_outputs: List[Dict[str, Any]]
    dossier_id: Optional[str]
    dossier_status: Optional[str]
    warnings: List[str]
    flags: List[str]
    is_ruling_seeking: bool
    banners: List[str]
    blocked: bool
    final_message: Optional[str]
    reviewer: Optional[str]


# Agent dispatcher
def dispatch_agents(
    route_plan: RoutePlan, query: str, madhhab: str, tariqa: str, location: str, live_mode: str
) -> List[AgentOutput]:
    outputs = []
    for agent_name in route_plan.agents:
        try:
            if agent_name == "faqih":
                from rafiq.agents.faqih import faqih_agent

                # if comparison requested (info)
                comparison = "مقارنة" in query or "comparison" in query.lower()
                out = faqih_agent(query, madhhab=madhhab or "maliki", comparison=comparison)
            elif agent_name == "muhaddith":
                from rafiq.agents.muhaddith import muhaddith_agent

                out = muhaddith_agent(query)
            elif agent_name == "murabbi":
                from rafiq.agents.murabbi import murabbi_agent

                out = murabbi_agent(query, tariqa=tariqa)
            elif agent_name == "logistics":
                from rafiq.agents.logistics import logistics_agent

                out = logistics_agent(query, live_mode=live_mode)
            elif agent_name == "weather_health":
                from rafiq.agents.weather_health import weather_health_agent

                out = weather_health_agent(query, location=location or "عرفة", live_mode=live_mode)
            elif agent_name == "contracts":
                from rafiq.agents.contracts import contracts_agent

                out = contracts_agent(query)
            else:
                continue
            outputs.append(out)
        except Exception as e:
            outputs.append(
                AgentOutput(
                    agent=agent_name,
                    status="error",
                    findings=[],
                    informational_only=True,
                    disclaimers=[str(e)],
                    data_source=live_mode,
                )
            )
    return outputs


# Node definitions - using dict state for LangGraph compatibility
def guard_in_node(state: Dict[str, Any]) -> Dict[str, Any]:
    query = state.get("query", "")
    blocked, warnings, flags = check_all_input(query)
    if blocked:
        append_audit("guard_in_block", "system", {"query_digest": hash(query), "flags": flags})
        return {
            "blocked": True,
            "warnings": warnings,
            "flags": flags,
            "agent_outputs": [],
            "is_ruling_seeking": False,
        }
    append_audit("guard_in_pass", "system", {"query_digest": hash(query)})
    return {"blocked": False, "warnings": warnings, "flags": flags}


def supervisor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    query = state["query"]
    madhhab = state.get("madhhab")
    tariqa = state.get("tariqa")
    location = state.get("location")
    sup_fn = get_supervisor(settings.RAFIQ_ROUTER)
    plan = sup_fn(query, madhhab, tariqa, location)
    # Determine if ruling seeking
    is_ruling = plan.intent in ["ruling", "mixed"]
    if any(a == "faqih" for a in plan.agents):
        # if faqih present, consider ruling seeking unless explicitly informational
        if "قصر" in query or "حكم" in query or "هل يجوز" in query:
            is_ruling = True
    append_audit("supervisor_route", "supervisor", {"agents": plan.agents, "intent": plan.intent})
    return {
        "route_plan": plan.model_dump(),
        "is_ruling_seeking": is_ruling,
        "banners": state.get("banners", []),
    }


def agents_node(state: Dict[str, Any]) -> Dict[str, Any]:
    query = state["query"]
    route_plan_dict = state.get("route_plan")
    if not route_plan_dict:
        return {"agent_outputs": []}
    plan = RoutePlan(**route_plan_dict)
    madhhab = state.get("madhhab")
    tariqa = state.get("tariqa")
    location = state.get("location")
    live_mode = settings.RAFIQ_LIVE

    outputs = dispatch_agents(plan, query, madhhab, tariqa, location, live_mode)
    # verifier per output
    verified_outputs = []
    for out in outputs:
        verified = verify_agent_output(out)
        verified_outputs.append(verified.model_dump())

    append_audit(
        "agents_done", "system", {"agents": plan.agents, "outputs_count": len(verified_outputs)}
    )
    return {"agent_outputs": verified_outputs}


def verifier_node(state: Dict[str, Any]) -> Dict[str, Any]:
    outputs_raw = state.get("agent_outputs", [])
    # outputs already verified in agents_node, but check overall not-found
    if not outputs_raw:
        return {"final_message": ERRORS["not_found"], "banners": [BANNERS["unverified"]]}
    total_findings = sum(len(o.get("findings", [])) for o in outputs_raw)
    if total_findings == 0:
        return {"final_message": ERRORS["not_found"], "banners": [BANNERS["unverified"]]}
    return {}


def guard_out_node(state: Dict[str, Any]) -> Dict[str, Any]:
    outputs_raw = state.get("agent_outputs", [])
    for out in outputs_raw:
        for f in out.get("findings", []):
            blocked, msg = check_output_adab(f.get("excerpt", ""))
            if blocked:
                append_audit("guard_out_block", "system", {"finding": f.get("source_id")})
                # filter that finding
                out["findings"] = [x for x in out["findings"] if x["source_id"] != f["source_id"]]
    return {"agent_outputs": outputs_raw}


def dossier_node(state: Dict[str, Any]) -> Dict[str, Any]:
    is_ruling = state.get("is_ruling_seeking")
    outputs_raw = state.get("agent_outputs", [])
    total_findings = sum(len(o.get("findings", [])) for o in outputs_raw)
    if not is_ruling and total_findings > 0:
        return {}
    # Non-ruling with zero findings: KICKOFF fail-safe knowledge gap -> still
    # filed as a PENDING dossier ("لا أعلم" is returned by verifier_node).
    kind = "masala" if is_ruling else "gap"
    query = state["query"]
    # per-madhhab ruling summary
    per_madhhab = {}
    for out in outputs_raw:
        if out["agent"] == "faqih":
            per_madhhab[out.get("extra", {}).get("madhhab", "maliki")] = {
                "findings": out["findings"],
                "work": [f.get("work") for f in out["findings"]],
                "mutamad": [f.get("mutamad") for f in out["findings"]],
            }
    waqi = {}
    hadith = {}
    for out in outputs_raw:
        if out["agent"] in ["logistics", "weather_health"]:
            waqi[out["agent"]] = out.get("extra", {})
        if out["agent"] == "muhaddith":
            hadith = out.get("findings", [])

    unsigned_findings = [
        f
        for out in outputs_raw
        if out["agent"] == "faqih"
        for f in out.get("findings", [])
        if not f.get("verified")
    ]
    unsigned_ids = [f.get("source_id") for f in unsigned_findings]

    prev_hash = get_last_hash()
    from rafiq.core.dossier import create_dossier as _create

    dossier = _create(
        query,
        per_madhhab,
        hadith,
        waqi,
        state.get("warnings", []),
        previous_audit_hash=prev_hash,
        kind=kind,
        unsigned_hits=unsigned_ids,
    )
    append_audit("dossier_created", "system", {"dossier_id": dossier.id, "kind": kind})
    if unsigned_findings:
        from rafiq.core.analytics import record_unsigned_hit

        record_unsigned_hit(
            query,
            state.get("madhhab"),
            [
                {"madhhab": f.get("madhhab") or state.get("madhhab"), "passage_id": f["source_id"]}
                for f in unsigned_findings
                if f.get("source_id")
            ],
            intent="ruling" if is_ruling else "general",
            dossier_id=dossier.id,
        )
    return {"dossier_id": dossier.id, "dossier_status": "PENDING"}


def mufti_review_node(state: Dict[str, Any]) -> Dict[str, Any]:
    dossier_id = state.get("dossier_id")
    if not dossier_id:
        return {}
    # Interrupt for human review - saves graph state via SQLite checkpointer
    # In PoC, this waits indefinitely until resumed with Command
    decision = interrupt(
        {"dossier_id": dossier_id, "message": "فما حكمكم يا مشايخنا؟", "status": "PENDING"}
    )
    # After resume, decision contains reviewer input
    # decision expected to be dict with reviewer, decision, note
    reviewer = decision.get("reviewer", "sheikh")
    dec = decision.get("decision", "APPROVED")
    note = decision.get("note", "")
    edited = decision.get("edited_version")
    auto = bool(decision.get("auto", False))
    add_decision(dossier_id, reviewer, dec, note, edited, auto=auto)
    append_audit(
        "dossier_decision", reviewer, {"dossier_id": dossier_id, "decision": dec, "auto": auto}
    )
    return {"dossier_status": dec, "reviewer": reviewer}


def build_graph():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    graph = StateGraph(GraphState)

    graph.add_node("guard_in", guard_in_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("agents", agents_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("guard_out", guard_out_node)
    graph.add_node("dossier", dossier_node)
    graph.add_node("mufti_review", mufti_review_node)

    graph.set_entry_point("guard_in")

    def route_after_guard_in(state):
        if state.get("blocked"):
            return END
        return "supervisor"

    def route_after_supervisor(state):
        return "agents"

    def route_after_agents(state):
        return "verifier"

    def route_after_verifier(state):
        return "guard_out"

    def route_after_guard_out(state):
        total = sum(len(o.get("findings", [])) for o in state.get("agent_outputs", []))
        if state.get("is_ruling_seeking") or total == 0:
            return "dossier"
        return END

    def route_after_dossier(state):
        return "mufti_review"

    graph.add_conditional_edges("guard_in", route_after_guard_in)
    graph.add_edge("supervisor", "agents")
    graph.add_edge("agents", "verifier")
    graph.add_edge("verifier", "guard_out")
    graph.add_conditional_edges("guard_out", route_after_guard_out)
    graph.add_edge("dossier", "mufti_review")
    graph.add_edge("mufti_review", END)

    compiled = graph.compile(checkpointer=checkpointer)
    return compiled


# For CLI usage: run query through graph without interrupt (auto-approve in demo mode)
def run_query(
    query: str,
    madhhab: str = None,
    tariqa: str = None,
    location: str = None,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    graph = build_graph()
    config = {"configurable": {"thread_id": f"cli_{hash(query)}"}}
    initial = {
        "query": query,
        "madhhab": madhhab,
        "tariqa": tariqa,
        "location": location,
        "agent_outputs": [],
        "warnings": [],
        "flags": [],
        "banners": [],
        "is_ruling_seeking": False,
    }
    # Stream
    for _ in graph.stream(initial, config=config):
        pass

    # Get final state
    final_state = graph.get_state(config)
    values = final_state.values if hasattr(final_state, "values") else final_state

    # If pending dossier and auto_approve
    if values.get("dossier_id") and auto_approve:
        if settings.is_prod():
            raise RuntimeError("auto-approve is a demo-only path and is disabled in prod")
        # Resume with an explicitly-labelled automated approval (audited as auto=True)
        for event in graph.stream(
            Command(
                resume={
                    "reviewer": "demo_auto_sheikh",
                    "decision": "APPROVED",
                    "note": "auto approved in demo",
                    "auto": True,
                }
            ),
            config=config,
        ):
            pass
        final_state = graph.get_state(config)
        values = final_state.values if hasattr(final_state, "values") else final_state

    return values
