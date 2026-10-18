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
# Noun-form ruling words are only trusted AFTER the asked subject («الجماعة …
# سنة»); before it they are usually component lists («وواجبه نية وموالاة»).
_NOUN_KEYWORDS = {
    "حرام",
    "مكروه",
    "كراهة",
    "واجب",
    "فرض",
    "فريضة",
    "سنة",
    "مسنون",
    "مستحب",
    "مندوب",
    "مباح",
    "جائز",
    "حلال",
}
_PREFIXES = ("وال", "فال", "ال", "و", "ف")
# Glued «بـ» qualifiers: «الجماعة بفرض غير جمعة سنة» - بفرض is a condition
# («when obligatory»), not the ruling; the real hukm follows it.
_QUALIFIER_WAJIB = (
    "بفرض",
    "بالفرض",
    "بفريضة",
    "بالفريضة",
    "بوجب",
    "بوجوب",
    "وبفرض",
    "وبالفرض",
    "وبفريضة",
    "وبالفريضة",
    "وبوجب",
    "وبوجوب",
)
# The ruling sentence may carry a parenthetical gloss between the subject and
# the keyword («( الجماعة ) أي فعل الصلاة جماعة … ( غير جمعة سنة ) مؤكدة»),
# so the scan window is sentence-sized, with the guards below keeping it safe.
_HUKM_AFTER = 24
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


def _matched_keyword(bare: str):
    """(family, matched_keyword) for a token, or (None, None)."""
    if not bare:
        return None, None
    hits = []
    for fam, kw in _KEYWORDS:
        if bare == kw or bare in (kw + "ا", kw + "ه"):
            hits.append((fam, kw))
        elif len(kw) >= 4 and bare.startswith(kw):
            hits.append((fam, kw))
    if not hits:
        return None, None
    # longest keyword wins: «سنة مؤكدة» pattern is handled separately, and
    # «مكروه» must not be shadowed by a shorter family keyword.
    return max(hits, key=lambda fk: len(fk[1]))


def _followed_by(tokens: list, j: int, prefix: str) -> bool:
    """True when the next letter-carrying token (skipping «)»/«(»/digits-only)
    starts with prefix: «( غير جمعة سنة ) مؤكدة» still reads as سنة مؤكدة."""
    for k in range(j + 1, min(len(tokens), j + 3)):
        b = _bare(tokens[k])
        if not b:
            continue
        return b.startswith(prefix)
    return False


def _hukm_hits_detail(tokens: list) -> list:
    """[(index, family, is_noun_form)] hits in a token span, negation handled."""
    hits = []
    for j, tok in enumerate(tokens):
        b = _bare(tok)
        if not b:
            continue
        neg = j > 0 and _bare(tokens[j - 1]) in _NEGATIONS
        if b == "باس" and neg:
            hits.append((j, "mubah", False))  # «لا بأس» = permitted (phrase)
            continue
        if b == "سنه" and _followed_by(tokens, j, "مؤكد"):  # normalized «سنة»
            fam, kw = "sunna_muakkada", "سنة"
        else:
            fam, kw = _matched_keyword(b)
            if fam is None:
                continue
        if fam == "wajib" and j > 0 and _bare(tokens[j - 1]) in _TOPIC_PREPS:
            continue
        if fam == "wajib" and normalize_for_search(tokens[j]).startswith(_QUALIFIER_WAJIB):
            continue  # «بفرض» = qualifier, not a ruling («الجماعة بفرض … سنة»)
        if j > 0 and _bare(tokens[j - 1]) == "اي":
            # «... أي يحرم ابتداؤها» glosses another مسألة (e.g. a negated matn
            # phrase before it), not the asked subject: never read it as hukm.
            continue
        if neg:
            if fam == "mubah":
                fam = "haram"  # «لا يجوز/لا يحل»
            else:
                fam = None  # negated obligation/recommendation: cannot decide
        if fam:
            hits.append((j, fam, kw in _NOUN_KEYWORDS))
    return hits


def _hukm_hits(tokens: list) -> list:
    """Family hits in a token span, with immediate negation handled."""
    return [fam for _, fam, _ in _hukm_hits_detail(tokens)]


def _tokens(text: str) -> list:
    return _TOKEN_RE.findall(text or "")


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


def _is_definite_core(tok: str, cores: list) -> bool:
    """True for «ال»-prefixed forms like الجماعة/والجماعة (vs clipped كجماعة)."""
    raw = normalize_for_search(tok)
    return any(("ال" + c) in raw for c in cores)


def _longest_core(bare: str, cores: list) -> bool:
    """True when the token carries the question's most specific (longest) term.

    Generic terms like «حكم/صلاة» appear on almost every page; a hukm found
    near them must not be read as a ruling on the asked subject (e.g. «ويخرج
    من الكراهة» near «الصلاة» on a page that never mentions الجماعة).
    """
    if not cores:
        return False
    return max(cores, key=len) in bare


def _best_core_index(tokens: list, cores: list):
    """Occurrence followed by an explicit hukm keyword on the specific term
    wins, then a definite («ال…») form, else earliest."""
    best_i, best_key = None, None
    for i in _core_positions(tokens, cores):
        span = tokens[max(0, i - 3) : i + 9]
        key = (
            1 if _hukm_hits(span) and _longest_core(_bare(tokens[i]), cores) else 0,
            1
            if _longest_core(_bare(tokens[i]), cores) and _is_definite_core(tokens[i], cores)
            else 0,
            1 if _is_definite_core(tokens[i], cores) else 0,
            -i,
        )
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
    if not _longest_core(_bare(tokens[best_i]), cores):
        return UNKNOWN, clause_from_excerpt(excerpt, cores)  # no specific subject
    lo = max(0, best_i - 6)
    detail = _hukm_hits_detail(tokens[lo : best_i + _HUKM_AFTER])
    fams = [
        fam
        for j, fam, is_noun in detail
        if not (is_noun and lo + j < best_i)  # noun rulings must follow the subject
    ]
    h = _resolve(fams)
    after = _HUKM_AFTER if h != UNKNOWN else 11
    return h, clause_from_excerpt(excerpt, cores, after=after)


def _resolved_hukm(tokens: list, cores: list) -> Optional[str]:
    """The hukm a token span resolves to, or None when nothing is detectable."""
    best_i = _best_core_index(tokens, cores)
    if best_i is None or not _longest_core(_bare(tokens[best_i]), cores):
        return None
    lo = max(0, best_i - 6)
    detail = _hukm_hits_detail(tokens[lo : best_i + _HUKM_AFTER])
    fams = [fam for j, fam, is_noun in detail if not (is_noun and lo + j < best_i)]
    h = _resolve(fams)
    return h if h != UNKNOWN else None


def has_resolved_hukm(text: str, cores: list) -> bool:
    """True when a verbatim span carries an explicit ruling on the asked term."""
    return _resolved_hukm(_tokens(text or ""), cores) is not None


def served_excerpt(text: str, cores: list, width: int = 400) -> Optional[str]:
    """Verbatim slice around an explicit ruling on the asked term, if any.

    The default window (arabic.matched_window) maximises query-term coverage
    and can miss the ruling sentence on a verbose page («الجماعة … سنة مؤكدة»
    sits mid-page while the window covers other terms). When that happens the
    khulasa would say «غير واضح» although the page contains the ruling - so
    faqih serves this slice instead. Only characters are sliced, never edited.
    """
    matches = list(_TOKEN_RE.finditer(text or ""))
    if not matches or not cores:
        return None
    tokens = [m.group(0) for m in matches]
    best = None
    for i, tok in enumerate(tokens):
        if not _longest_core(_bare(tok), cores):
            continue
        lo = max(0, i - 6)
        hi = min(len(tokens), i + _HUKM_AFTER)
        detail = _hukm_hits_detail(tokens[lo:hi])
        fams = [fam for j, fam, is_noun in detail if not (is_noun and lo + j < i)]
        h = _resolve(fams)
        if h == UNKNOWN:
            continue
        window_norm = normalize_for_search(" ".join(tokens[lo:hi]))
        distinct = sum(1 for c in set(cores) if c in window_norm)
        key = (distinct, -i)
        if best is None or key > best[0]:
            best = (key, lo, hi)
    if best is None:
        return None
    _, lo, hi = best
    start = matches[lo].start()
    end = matches[hi - 1].end()
    if end - start > width:
        cut = start + width
        while hi > lo and matches[hi - 1].end() > cut:
            hi -= 1
        end = matches[hi - 1].end()
    out = text[start:end].strip()
    if start > 0:
        out = "… " + out
    if end < len(text):
        out = out + " …"
    return out


def finding_score(finding: dict, cores: list) -> tuple:
    """Sort key: query-term density, explicit ruling, «سنة مؤكدة» specificity."""
    excerpt = finding.get("excerpt") or ""
    norm = normalize_for_search(excerpt)
    distinct = sum(1 for c in set(cores) if c in norm)
    tokens = _tokens(excerpt)
    hits = 0
    muakkada = 0
    for i in _core_positions(tokens, cores):
        if not _longest_core(_bare(tokens[i]), cores):
            continue
        lo = max(0, i - 6)
        detail = _hukm_hits_detail(tokens[lo : i + _HUKM_AFTER])
        fams = [fam for j, fam, is_noun in detail if not (is_noun and lo + j < i)]
        if _resolve(fams) != UNKNOWN:
            hits += 1
        if "sunna_muakkada" in fams:
            muakkada += 1
    return (distinct, hits, muakkada)


# Beginner matn layer («الحلقة الميسّرة»): short readable passages whose only
# job is to carry one-line rulings, so they get a preference in the ranking.
EASY_PREFIXES = ("ashmawiya_", "ibn_ashir_", "risala_")


def _excerpt_bonus(finding: dict, cores: list) -> int:
    """Easy-layer / short ruling-bearing excerpts get a small ranking bump."""
    sid = finding.get("source_id") or ""
    excerpt = finding.get("excerpt") or ""
    easy = sid.startswith(EASY_PREFIXES)
    tokens = _tokens(excerpt)
    has_rule = _resolved_hukm(tokens, cores) is not None
    if easy and has_rule:
        return 2
    if easy or (has_rule and len(excerpt) < 260):
        return 1
    return 0


def rank_findings(findings: list, cores: list, cap: int = 3) -> list:
    """Best 2-3 pages only.

    Keeps the pages that carry the asked terms (a page matching only one of
    them, like an unrelated chapter page, is dropped). On terse matn the full
    peak usually co-occurs on one page; on verbose commentary (Dardir) it
    rarely does, so a two-term floor still fills the slots with relevant pages
    while dropping the single-term noise, then ranks by explicit-ruling hits
    and prefers the easy-layer / short ruling-bearing excerpts.
    """
    scored = [(i, f, finding_score(f, cores)) for i, f in enumerate(findings)]
    peak = max((s[0] for _, _, s in scored), default=0)
    floor = min(peak, 2)
    pool = [x for x in scored if x[2][0] >= floor] if peak > 0 else scored[:1]
    # «سنة مؤكدة» on the asked term is the strongest readable evidence a page
    # can carry, so it outranks raw term coverage (a page answering with the
    # canonical phrase beats a denser page that only mentions siblings).
    pool = sorted(
        pool,
        key=lambda x: (-x[2][2], -x[2][1], -x[2][0], -_excerpt_bonus(x[1], cores), x[0]),
    )
    return [f for _, f, _ in pool[:cap]]


def build_khulasa(findings: list, query: str) -> Optional[dict]:
    """Extractive summary + hukm label from the served findings (flat list).

    Returns {"text", "hukm", "clause", "source_id"} or None when nothing was
    retrieved. `text` always starts with START and ends with END.
    """
    findings = [f for f in (findings or []) if (f.get("excerpt") or "").strip()]
    if not findings:
        return None
    cores = query_cores(query)
    ladder = findings[:2]

    # The ladder is already rank-ordered (best evidence first), so the first
    # page that resolves a hukm on the asked subject wins; only when no page
    # resolves do we stay vague. (M21 required full agreement, but served
    # excerpts now carry the ruling sentence itself, so a neighbouring
    # مسألة's generic «يكره» on a secondary page must not veto the top page.)
    hukm, chosen, clause = UNKNOWN, findings[0], None
    for f in ladder:
        h, c = finding_hukm(f, cores)
        if h != UNKNOWN:
            hukm, chosen, clause = h, f, c
            break

    if clause is None:
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
