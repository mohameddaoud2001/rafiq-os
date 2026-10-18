"""
Arabic normalization per spec.
"""

import re

TASHKEEL_RE = re.compile(r"[\u064B-\u0652\u0670]")
TATWEEL = "\u0640"

MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ة": "ه",
    }
)

ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

SEARCH_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)


def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    # strip tashkeel
    text = TASHKEEL_RE.sub("", text)
    text = text.replace(TATWEEL, "")
    text = text.translate(MAP)
    text = text.translate(ARABIC_INDIC_DIGITS)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_for_search(text: str) -> str:
    text = normalize_arabic(text)
    # punctuation (؟ ، . ! « » ...) must never glue onto query cores, otherwise
    # "الإحرام؟" becomes the core "احرام؟" and relaxed matching silently misses
    text = SEARCH_PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _search_normalized_with_map(text: str) -> tuple:
    """normalize_for_search(text) plus a map normalized index -> original index.

    Used to slice the ORIGINAL (tashkeel-bearing) text around a matched term.
    """
    out = []
    idx_map = []
    prev_space = False
    for i, ch in enumerate(text):
        if TASHKEEL_RE.match(ch) or ch == TATWEEL:
            continue
        ch = ch.translate(MAP).translate(ARABIC_INDIC_DIGITS)
        if ch.isspace() or SEARCH_PUNCT_RE.match(ch):
            ch = " "
        else:
            ch = ch.lower()
        if ch == " " and (prev_space or not out):
            prev_space = True
            continue
        out.append(ch)
        idx_map.append(i)
        prev_space = ch == " "
    while out and out[-1] == " ":
        out.pop()
        idx_map.pop()
    return "".join(out), idx_map


def matched_window(text: str, cores, width: int = 400) -> str:
    """Verbatim slice of text around the best cluster of query cores.

    Returns the smallest excerpt that keeps as many distinct query cores as
    possible (tie-break: earliest), cut on word boundaries and clearly marked
    with «…» where text was removed. Never edits the original characters.
    """
    if not text:
        return text
    if len(text) <= width or not cores:
        return text
    norm, idx_map = _search_normalized_with_map(text)
    if not norm:
        return text

    positions = {}
    for c in cores:
        pos = norm.find(c)
        if pos >= 0:
            positions.setdefault(pos, set()).add(c)
    if not positions:
        return text[:width].rstrip() + " …"

    best_start, best_count = None, -1
    for pos in positions:
        start = max(0, pos - width // 3)
        end = min(len(norm), start + width)
        count = sum(1 for p in positions if start <= p < end)
        if count > best_count or (count == best_count and start < best_start):
            best_start, best_count = start, count

    start = best_start
    end = min(len(norm), start + width)
    while start > 0 and norm[start - 1] != " ":
        start -= 1
    while end < len(norm) and norm[end] != " ":
        end += 1
    o_start = idx_map[start] if start < len(idx_map) else 0
    o_end = idx_map[end - 1] + 1 if end > 0 else len(text)
    out = text[o_start:o_end].strip()
    if o_start > 0:
        out = "… " + out
    if o_end < len(text):
        out = out + " …"
    return out
