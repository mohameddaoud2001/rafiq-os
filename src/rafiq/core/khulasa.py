"""Extractive plain-language layer («خلاصة النقول») for ruling answers.

Owner request 2026-10-18: ordinary users get a one-sentence summary first,
then the verbatim quotes as collapsible evidence. The summary text contains
ONLY: (a) contiguous verbatim corpus words, (b) a fixed template, (c) a hukm
label detected inside the same verbatim span. No generated fiqh wording and
no new hukm - if the span carries no explicit ruling keyword, or two spans
disagree, the hukm is «غير واضح» and the summary says the text is not enough.

Ranking keeps the answer anchored to the best 2-3 pages only (the p038/p044
style noise from Khalil pages is dropped from the response entirely).
"""

import re
from typing import Optional

from rafiq.core.messages import MADHHAB_NAMES
from rafiq.rag.arabic import normalize_for_search
from rafiq.rag.madhhab_stores import query_cores

START = "بناءً على ما نقل من الكتب المذكورة"
END = "وليست فتوى معتمدة، وللفتوى المعتمدة راجع أهل العلم."
INSUFFICIENT = "النص المنقول غير كافٍ لتحديد حكم واضح"
UNKNOWN = "غير واضح"

HUKM_VALUES = ["سنة", "سنة مؤكدة", "مستحب", "مباح", "مكروه", "حرام", "واجب", UNKNOWN]

_FAMILIES = {
    "haram": ["حرام", "يحرم"],
    "makruh": ["مكروه", "يكره", "كراهة"],
    "wajib": ["واجب", "وجب", "فرض", "فريضة", "يفترض"],
    "sunna_muakkada": ["سنة مؤكدة"],
    "sunna": ["سنة", "مسنون", "يسن"],
    "mustahabb": ["مستحب", "يستحب", "مندوب", "يندب", "ندب"],
    "mubah": ["مباح", "يباح", "جائز", "يجوز", "تجوز", "حلال", "يحل"],
}
_ENUM = {
    "haram": "حرام",
    "makruh": "مكروه",
    "wajib": "واجب",
    "sunna_muakkada": "سنة مؤكدة",
    "sunna": "سنة",
    "mustahabb": "مستحب",
    "mubah": "مباح",
}
_KEYWORDS = [(fam, normalize_for_search(kw)) for fam, kws in _FAMILIES.items() for kw in kws]

_NEGATIONS = {"لا", "ما", "لم", "لن"}
# «في فرض / غير فرض» is a topic phrase, not a ruling: never read it as wajib.
_TOPIC_PREPS = {"في", "على", "عن", "من", "الى", "غير", "الا"}
_PREFIXES = ("وال", "فال", "ال", "و", "ف")
_TOKEN_RE = re.compile(r"\S+")
_GLUED_DIGITS_RE = re.compile(r"([\u0621-\u064a])[0-9\u0660-\u0669\u06f0-\u06f9]+")


def _bare(token: str) -> str:
    """Normalized token without footnote digits and leading conjunction/article."""
    tok = normalize_for_search(token)
    tok = _GLUED_DIGITS_RE.sub(r"\1", tok)
    tok = tok.strip()
    for pref in _PREFIXES:
        if tok.startswith(pref) and len(tok) - len(pref) >= 3:
            tok = tok[len(pref) :]
            break
    return tok


def _match_family(bare: str) -> Optional[str]:
    if not bare:
        return None
    hits = []
    for fam, kw in _KEYWORDS:
        if bare == kw or bare in (kw + "ا", kw + "ه"):
            hits.append(fam)
        elif len(kw) >= 4 and bare.startswith(kw):
            hits.append(fam)
    if not hits:
        return None
    # longest keyword wins: «سنة مؤكدة» pattern is handled separately, and
    # «مكروه» must not be shadowed by a shorter family keyword.
    return max(hits, key=lambda f: max(len(k) for k in _FAMILIES[f]))


def _tokens(text: str) -> list:
    return _TOKEN_RE.findall(text or "")


def _hukm_hits(tokens: list) -> list:
    """Family hits in a token span, with immediate negation handled."""
    hits = []
    for j, tok in enumerate(tokens):
        b = _bare(tok)
        if not b:
            continue
        neg = j > 0 and _bare(tokens[j - 1]) in _NEGATIONS
        if b == "باس" and neg:
            hits.append("mubah")  # «لا بأس» = permitted
            continue
        if b == "سنة" and j + 1 < len(tokens) and _bare(tokens[j + 1]).startswith("مؤكد"):
            fam = "sunna_muakkada"
        else:
            fam = _match_family(b)
            if fam is None:
                continue
        if fam == "wajib" and j > 0 and _bare(tokens[j - 1]) in _TOPIC_PREPS:
            continue
        if neg:
            if fam == "mubah":
                fam = "haram"  # «لا يجوز/لا يحل»
            else:
                fam = None  # negated obligation/recommendation: cannot decide
        if fam:
            hits.append(fam)
    return hits


def _resolve(hits: list) -> str:
    families = set(hits)
    if "sunna_muakkada" in families and families <= {"sunna_muakkada", "sunna"}:
        families = {"sunna_muakkada"}
    if not families:
        return UNKNOWN
    if len(families) > 1:
        return UNKNOWN  # conflicting rulings in the served span
    return _ENUM[families.pop()]


def _core_positions(tokens: list, cores: list) -> list:
    out = []
    for i, tok in enumerate(tokens):
        b = _bare(tok)
        if b and any(c in b for c in cores):
            out.append(i)
    return out


def _best_core_index(tokens: list, cores: list):
    """Occurrence followed by an explicit hukm keyword wins, else earliest."""
    best_i, best_key = None, None
    for i in _core_positions(tokens, cores):
        span = tokens[max(0, i - 3) : i + 9]
        key = (1 if _hukm_hits(span) else 0, -i)
        if best_key is None or key > best_key:
            best_i, best_key = i, key
    return best_i


def clause_from_excerpt(excerpt: str, cores: list, before: int = 3, after: int = 11):
    """Contiguous verbatim token slice around the best query-core occurrence.

    Prefers the occurrence that is followed by an explicit hukm keyword inside
    the scan span ("الجماعة ... سنة"), so the summary sentence carries both the
    asked subject and the ruling. Footnotes digits and window markers («…»)
    are the only things ever removed - from this display layer only; the
    citations keep the untouched text.
    """
    tokens = _tokens(excerpt)
    if not tokens or not cores:
        return None
    best_i = _best_core_index(tokens, cores)
    if best_i is None:
        return None
    clause = " ".join(tokens[max(0, best_i - before) : best_i + after])
    clause = clause.replace("«", " ").replace("»", " ").replace("…", " ")
    clause = _GLUED_DIGITS_RE.sub(r"\1", clause)
    clause = re.sub(r"\s+", " ", clause).strip()
    if len(clause) > 240:
        cut = clause[:240].rsplit(" ", 1)[0]
        clause = cut + " …"
    return clause or None


def finding_hukm(finding: dict, cores: list):
    """(hukm, clause) for one finding, derived only from its own verbatim span."""
    excerpt = finding.get("excerpt") or ""
    tokens = _tokens(excerpt)
    best_i = _best_core_index(tokens, cores)
    if best_i is None:
        return UNKNOWN, clause_from_excerpt(excerpt, cores)
    clause = clause_from_excerpt(excerpt, cores)
    hits = _hukm_hits(tokens[max(0, best_i - 3) : best_i + 9])
    return _resolve(hits), clause


def finding_score(finding: dict, cores: list) -> tuple:
    """Sort key: query-term density first, explicit ruling next."""
    excerpt = finding.get("excerpt") or ""
    norm = normalize_for_search(excerpt)
    distinct = sum(1 for c in set(cores) if c in norm)
    tokens = _tokens(excerpt)
    hits = 0
    for i in _core_positions(tokens, cores):
        if _hukm_hits(tokens[max(0, i - 3) : i + 9]):
            hits += 1
    return (distinct, hits)


def rank_findings(findings: list, cores: list, cap: int = 3) -> list:
    """Best 2-3 pages only.

    Keeps the pages that carry the full density peak of the asked terms (a
    page matching only some of them, like an unrelated Khalil chapter page,
    is dropped), then ranks by explicit-ruling hits and keeps the cap.
    """
    scored = [(i, f, finding_score(f, cores)) for i, f in enumerate(findings)]
    peak = max((s[0] for _, _, s in scored), default=0)
    pool = [x for x in scored if x[2][0] >= peak] if peak > 0 else scored[:1]
    pool = sorted(pool, key=lambda x: (-x[2][0], -x[2][1], x[0]))
    return [f for _, f, _ in pool[:cap]]


def build_khulasa(citations: list, query: str) -> Optional[dict]:
    """Extractive summary + hukm label from the top-scored citations only.

    Returns {"text", "hukm", "clause", "source_id"} or None when nothing was
    retrieved. `text` always starts with START and ends with END.
    """
    findings = [f for cit in citations for f in (cit.get("findings") or [])]
    if not findings:
        return None
    cores = query_cores(query)
    ladder = [f for f in findings[:2] if (f.get("excerpt") or "").strip()]

    hukm, chosen = UNKNOWN, findings[0]
    known = []
    for f in ladder:
        h, clause = finding_hukm(f, cores)
        if h != UNKNOWN:
            known.append((h, f, clause))
    if len({h for h, _, _ in known}) == 1:
        hukm, chosen, _ = known[0]
    elif len(known) > 1:
        hukm, chosen = UNKNOWN, findings[0]  # conflicting pages: stay vague

    clause = clause_from_excerpt(chosen.get("excerpt") or "", cores)
    work = chosen.get("work") or ""
    madhhab_name = MADHHAB_NAMES.get(chosen.get("madhhab") or "", "")
    mh_part = f"المذهب {madhhab_name}" if madhhab_name else ""
    attribution = "، ".join(x for x in (work, mh_part) if x)

    if hukm != UNKNOWN and clause:
        text = (
            f"{START}، الحكم المستفاد من النص المنقول: {hukm} - «{clause}»"
            f"{f' ({attribution})' if attribution else ''}، {END}"
        )
    else:
        extra = ""
        if clause:
            tail = f" - {work}" if work else ""
            extra = f" (أقرب ما وُجد في النصوص: «{clause}»{tail})"
        text = f"{START}، {INSUFFICIENT}{extra}، {END}"
    return {
        "text": text,
        "hukm": hukm,
        "clause": clause,
        "source_id": chosen.get("source_id"),
    }
