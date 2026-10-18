from rafiq.core.khulasa import has_resolved_hukm, served_excerpt
from rafiq.core.messages import BANNERS
from rafiq.core.state import AgentOutput, Finding
from rafiq.rag.arabic import matched_window
from rafiq.rag.madhhab_stores import query_cores
from rafiq.rag.retriever import MadhhabRetriever
from rafiq.rag.source_links import scan_url as resolve_scan_url

retriever = MadhhabRetriever()


def faqih_agent(query: str, madhhab: str = "maliki", comparison: bool = False) -> AgentOutput:
    """
    User's madhhab store only by default; comparison queries all four.
    Returns findings with source ids.

    Owner decision 2026-10-18: real book text is served in every environment
    without any sign-off gate - every quote carries its source and is labelled
    «منقول من الكتب - بلا توقيع مفتٍ» with the "ليست فتوى مفتٍ" banner. Only
    real OpenITI book text is ever served (seed placeholders are excluded).
    """
    want = 3 if comparison else 5
    fetch = want * 2
    if comparison:
        results = retriever.search(query, madhhab=None, limit=fetch)
    else:
        results = retriever.search(query, madhhab=madhhab, limit=fetch)

    # Dev seed placeholders are not real sources ("ملخص توضيحي غير محقق"):
    # they must never be shown to users as excerpts from a printed edition.
    results = [p for p in results if not (p.provenance or "").startswith("seed")][:want]

    cores = query_cores(query)
    findings = []
    for p in results:
        excerpt = matched_window(p.text, cores)
        # When the default window covers the asked terms but misses the page's
        # explicit ruling sentence ("الجماعة … سنة مؤكدة" mid-page), serve the
        # ruling slice instead - still verbatim, only characters are sliced.
        if not has_resolved_hukm(excerpt, cores):
            span = served_excerpt(p.text, cores)
            if span:
                excerpt = span
        findings.append(
            Finding(
                source_id=p.id,
                excerpt=excerpt,
                work=p.work,
                author=p.author,
                edition=p.edition,
                volume=p.volume,
                page=p.page,
                mutamad=p.mutamad,
                verified=p.verified,
                madhhab=p.madhhab,
                topic_tags=p.topic_tags,
                provenance=p.provenance,
                scan_url=resolve_scan_url(provenance=p.provenance),
            )
        )

    if not findings:
        return AgentOutput(
            agent="faqih",
            status="not_found",
            findings=[],
            informational_only=False,
            disclaimers=[BANNERS["unverified"], BANNERS["hijri_disclaimer"]],
            data_source="db",
        )

    return AgentOutput(
        agent="faqih",
        status="ok",
        findings=findings,
        informational_only=False,
        disclaimers=[BANNERS["unverified"]],
        data_source="db",
        extra={"madhhab": madhhab, "comparison": comparison},
    )
