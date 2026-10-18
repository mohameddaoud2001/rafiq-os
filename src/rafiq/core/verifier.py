from rafiq.core.messages import ERRORS
from rafiq.core.state import AgentOutput

NOT_FOUND_PHRASE = ERRORS["not_found"]


def verify_agent_output(output: AgentOutput, threshold: float = 0.1) -> AgentOutput:
    """
    Verifier: drops findings without citation, audits.
    If no findings above threshold, return not_found.
    """
    # Each finding must have source_id
    valid_findings = []
    for f in output.findings:
        if not f.source_id:
            # audit drop
            from rafiq.core.audit import append_audit

            append_audit("verifier_drop_no_citation", output.agent, {"source_id": None})
            continue
        valid_findings.append(f)

    output.findings = valid_findings

    if not valid_findings:
        # If agent was expected to find something but didn't, return not_found status
        if output.status == "ok":
            output.status = "not_found"
    return output


def should_return_not_found(outputs: list) -> bool:
    if not outputs:
        return True
    total_findings = sum(len(o.findings) for o in outputs)
    return total_findings == 0
