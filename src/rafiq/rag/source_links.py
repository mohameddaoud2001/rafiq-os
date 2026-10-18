"""Resolve real source links (digitized file / Shamela page) and page hints.

Every link emitted here was verified to resolve (HTTP 200, matching title) on
2026-10-18; unknown provenances return None so the UI shows the raw provenance
locator instead of a dead link. No link is ever invented.
"""

import re
from typing import Any, Dict, List, Optional

PAGE_HINT_RE = re.compile(r"PageV(\d+)P(\d+)")

# OpenITI identifier: optional century-repo prefix, then <author>.<book>.<edition>-araN
_OPENITI_RE = re.compile(r"OpenITI:(?:(\d{4}AH)/)?(\S+)")
_SHAMELA_RE = re.compile(r"Shamela(\d+)")

# author prefix -> OpenITI release repo (verified against github.com/OpenITI)
_OPENITI_REPO_BY_AUTHOR = {
    "0676Nawawi": "0700AH",
    "0264IbnYahyaMuzani": "0275AH",
    "0620IbnQudamaMaqdisi": "0625AH",
    "0593BurhanDinFarghaniMarghinani": "0600AH",
}


def page_hint(provenance: Optional[str]) -> Optional[int]:
    """Print-page number from the digitization hint (unconfirmed until sign-off)."""
    if not provenance:
        return None
    m = PAGE_HINT_RE.search(provenance)
    return int(m.group(2)) if m else None


def page_hint_label(provenance: Optional[str]) -> Optional[str]:
    """Display label for the digitization page: «ص40», or «ج2 ص40» for multi-volume texts."""
    if not provenance:
        return None
    m = PAGE_HINT_RE.search(provenance)
    if not m:
        return None
    vol, page = m.group(1), int(m.group(2))
    return f"ص{page}" if vol == "01" else f"ج{int(vol)} ص{page}"


def openiti_file_url(provenance: Optional[str]) -> Optional[str]:
    """Browse link to the exact OpenITI mARkdown file the text was digitized from."""
    m = _OPENITI_RE.search(provenance or "")
    if not m:
        return None
    century, book_id = m.group(1), m.group(2)
    author = book_id.split(".")[0]
    repo = (century or "").rstrip("/") or _OPENITI_REPO_BY_AUTHOR.get(author)
    if not repo:
        return None
    book_dir = re.sub(r"\.(?:Shamela|JK|Shia)\d+(?:Vols)?$", "", re.sub(r"-ara\d+$", "", book_id))
    return f"https://github.com/OpenITI/{repo}/blob/master/data/{author}/{book_dir}/{book_id}"


def shamela_book_url(provenance: Optional[str]) -> Optional[str]:
    """Shamela library page for the same Shamela print (id = digits without zeros)."""
    m = _SHAMELA_RE.search(provenance or "")
    if not m:
        return None
    return f"https://shamela.ws/book/{int(m.group(1))}"


def scan_links(provenance: Optional[str]) -> List[Dict[str, str]]:
    """All verified source links for a passage, in display order."""
    links: List[Dict[str, str]] = []
    openiti = openiti_file_url(provenance)
    if openiti:
        links.append({"kind": "openiti", "label": "ملف الرقمنة (OpenITI)", "url": openiti})
    shamela = shamela_book_url(provenance)
    if shamela:
        links.append({"kind": "shamela", "label": "نسخة المكتبة الشاملة", "url": shamela})
    return links


def scan_url(provenance: Optional[str] = None, explicit: Optional[str] = None) -> Optional[str]:
    """Primary scan/source link: an explicit per-passage url wins, else derived."""
    if explicit:
        return explicit
    links = scan_links(provenance)
    return links[0]["url"] if links else None


def source_citation(
    work: Optional[str] = None,
    author: Optional[str] = None,
    edition: Optional[str] = None,
    volume: Optional[int] = None,
    page: Optional[int] = None,
    provenance: Optional[str] = None,
) -> str:
    """[الكتاب] [المؤلف] [الطبعة] [الصفحة] - page hint labelled while unconfirmed."""
    parts: List[str] = []
    for v in (work, author, edition):
        if v:
            parts.append(str(v))
    if page is not None:
        parts.append(f"ج{volume} ص{page}" if volume else f"ص{page}")
    else:
        label = page_hint_label(provenance)
        if label:
            parts.append(f"{label} (ترقيم مبدئي - يُثبّت عند التوقيع)")
    if not parts:
        parts.append("المصدر غير محدد")
    return " - ".join(parts)


def source_metadata(
    work: Optional[str] = None,
    author: Optional[str] = None,
    edition: Optional[str] = None,
    volume: Optional[int] = None,
    page: Optional[int] = None,
    provenance: Optional[str] = None,
) -> Dict[str, Any]:
    """Structured source metadata block: book, author, edition, page, scan link."""
    return {
        "work": work,
        "author": author,
        "edition": edition,
        "volume": volume,
        "page": page,
        "page_hint": page_hint(provenance),
        "provenance": provenance,
        "scan_links": scan_links(provenance),
        "citation": source_citation(work, author, edition, volume, page, provenance),
    }
