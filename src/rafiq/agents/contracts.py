"""
Contracts agent - PDF or plain text -> clause segmentation -> rule-based flags
for riba, gharar, jahala. Arabic, French, English.
"""

import re
from typing import Any, Dict, List

from rafiq.core.messages import BANNERS
from rafiq.core.state import AgentOutput, Finding

RIBA_PATTERNS = [r"ربا", r"فائدة.*\d+%", r"interest.*\d+%", r"intérêt", r"riba", r"usury"]
GHARAR_PATTERNS = [r"غرر", r"جهالة.*فاحشة", r"gharar", r"uncertainty.*excessive", r"incertitude"]
JAHALA_PATTERNS = [r"جهالة", r"مجهول", r"jahala", r"unknown.*price", r"prix.*inconnu"]

ALTERNATIVES = {
    "riba": ["مرابحة", "إجارة", "مشاركة"],
    "gharar": ["سلم", "استصناع", "مرابحة موصوفة"],
    "jahala": ["تحديد الثمن والموصوف بوضوح"],
}


def segment_clauses(text: str) -> List[Dict[str, Any]]:
    # simple split by sentences or lines
    parts = re.split(r"[\n\.،;]+", text)
    clauses = []
    for idx, part in enumerate(parts):
        part = part.strip()
        if len(part) < 5:
            continue
        clauses.append({"id": f"clause_{idx}", "text": part})
    return clauses


def flag_clause(clause: Dict[str, Any]) -> List[Dict[str, Any]]:
    flags = []
    txt = clause["text"].lower()
    for pat in RIBA_PATTERNS:
        if re.search(pat, txt, re.IGNORECASE):
            flags.append(
                {
                    "clause_id": clause["id"],
                    "excerpt": clause["text"],
                    "category": "riba",
                    "explanation": "اشتباه ربا - وجود فائدة محددة",
                    "review_question": "هل هذه الفائدة مشروطة في القرض؟",
                    "alternatives": ALTERNATIVES["riba"],
                }
            )
            break
    for pat in GHARAR_PATTERNS:
        if re.search(pat, txt, re.IGNORECASE):
            flags.append(
                {
                    "clause_id": clause["id"],
                    "excerpt": clause["text"],
                    "category": "gharar",
                    "explanation": "اشتباه غرر",
                    "review_question": "هل المبيع معلوم الوصف؟",
                    "alternatives": ALTERNATIVES["gharar"],
                }
            )
            break
    for pat in JAHALA_PATTERNS:
        if re.search(pat, txt, re.IGNORECASE):
            flags.append(
                {
                    "clause_id": clause["id"],
                    "excerpt": clause["text"],
                    "category": "jahala",
                    "explanation": "اشتباه جهالة",
                    "review_question": "هل الثمن والمبيع محددان؟",
                    "alternatives": ALTERNATIVES["jahala"],
                }
            )
            break
    return flags


def contracts_agent(text: str, is_pdf: bool = False) -> AgentOutput:
    clauses = segment_clauses(text)
    all_flags = []
    for c in clauses:
        all_flags.extend(flag_clause(c))

    findings = []
    for fl in all_flags:
        findings.append(
            Finding(
                source_id=fl["clause_id"],
                excerpt=f"{fl['category']}: {fl['excerpt']} - {fl['explanation']}",
                work="contract",
                verified=False,
                topic_tags=[fl["category"]],
            )
        )

    return AgentOutput(
        agent="contracts",
        status="ok" if findings else "ok",
        findings=findings,
        informational_only=True,
        disclaimers=[BANNERS["contract_flag"], BANNERS["unverified"]],
        data_source="contract_text",
        extra={"flags": all_flags, "clauses_count": len(clauses)},
    )


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        return f"PDF extract error: {e}"
