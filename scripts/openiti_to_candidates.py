#!/usr/bin/env python3
"""Convert an OpenITI mARkdown chapter into Rafiq candidate passages.

Candidates are review material for scholars at /dashboard/corpus: real text
from a real digitized print edition. Page references are kept in the
provenance string only - the passage page field stays null until a scholar
signs off (project rule: no unverified page numbers in records).

Usage:
  python scripts/openiti_to_candidates.py \\
    --input mukhtasar.txt \\
    --output data/corpus/maliki/candidates/khalil_hajj.jsonl \\
    --id-prefix maliki_khalil_hajj \\
    --section "باب في أحكام كتاب الحج والعمرة" \\
    --work "مختصر خليل" \\
    --author "خليل بن إسحاق الجندي المالكي (ت 776هـ)" \\
    --edition "دار الحديث، القاهرة، ط1 1426هـ/2005م، تحقيق أحمد جاد" \\
    --license "CC BY-NC-SA 4.0 (OpenITI corpus)" \\
    --provenance "OpenITI:0775AH/<text-uri> sha256:<hash>"

Optional: --end-with "<next كتاب title>" stops the section at that exact
following header (use when the chapter has باب/فصل sub-headers that would
otherwise trigger the default boundary).
"""

import argparse
import json
import pathlib
import re

PAGE_RE = re.compile(r"PageV(\d+)P(\d+)")
MS_RE = re.compile(r"\bms\d+\b")
DOTS_ONLY_RE = re.compile(r"^[.\s\u2026]+$")


def _is_dots_only(text: str) -> bool:
    return bool(text) and bool(DOTS_ONLY_RE.match(text))


def parse_markdown_section(
    text: str, section_title: str, min_chars: int = 20, end_with: str | None = None
) -> list[dict]:
    """Extract page-chunked passages from a `### | <section_title>` chapter.

    Returns dicts: {"page": int, "text": str, "headings": [str]}.
    Page hint comes from PageV01P### markers; text before a marker belongs to
    the page that marker closes (OpenITI convention: marker sits at the page
    break).

    `end_with` (optional): stop at the first following header-shaped line
    whose stripped text starts with this string (e.g. the next كتاب title).
    Needed when sub-sections (باب/فصل) also use header markers and the
    default باب/كتاب boundary would cut the chapter short. Without it, the
    section ends at the next باب/كتاب chapter header.
    """
    lines = text.splitlines()

    def is_chapter_header(line: str) -> bool:
        h = line.lstrip("#| ").strip()
        return h.startswith(("باب", "كتاب", "القسم"))

    def is_subheading(line: str) -> bool:
        h = line.lstrip("#| ").strip()
        return h.startswith(("باب", "فصل", "كتاب", "القسم"))

    start = None
    for i, line in enumerate(lines):
        if line.startswith("###") and section_title in line:
            start = i
            break
    if start is None:
        raise ValueError(f"section not found: {section_title}")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if end_with is not None:
            if line.lstrip().startswith("#") and line.lstrip("#|~ ").strip().startswith(end_with):
                end = i
                break
        elif line.startswith("###") and is_chapter_header(line):
            end = i
            break

    pages: list[dict] = []
    by_page: dict[int, dict] = {}
    current_page: int | None = None
    buffer: list[str] = []
    current_headings: list[str] = []
    carry: str = ""

    def flush(page: int | None):
        nonlocal buffer, carry
        body = "\n".join(x for x in buffer if x.strip()).strip()
        body = MS_RE.sub("", body).strip()
        if _is_dots_only(body):
            body = ""
        if carry:
            body = (carry + "\n" + body).strip() if body else carry
            carry = ""
        if page is not None and len(body) >= min_chars:
            if page in by_page:
                by_page[page]["text"] += "\n" + body
            else:
                entry = {"page": page, "text": body, "headings": list(current_headings)}
                by_page[page] = entry
                pages.append(entry)
        else:
            carry = body  # too short for a page of its own; prepend to next
        buffer = []

    for raw in lines[start:end]:
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip("#~ ").strip()
        if _is_dots_only(stripped):
            continue  # ellipsis-only marker line
        # standalone page marker line, e.g. "# PageV01P066" or "~~PageV01P068"
        m = PAGE_RE.fullmatch(stripped)
        if m:
            # marker announces the page of the text that follows
            flush(current_page)
            current_page = int(m.group(2))
            continue
        # inline page marker at end of a text line: it closes the page of the
        # text preceding it; following text continues on the next page
        inline = PAGE_RE.search(line)
        if inline:
            new_page = int(inline.group(2))
            before = PAGE_RE.sub("", line).lstrip("#~ ").strip()
            if before and not _is_dots_only(before):
                buffer.append(before)
            flush(new_page)
            current_page = new_page + 1
            continue
        if line.startswith("###"):
            heading = line.lstrip("#| ").strip()
            if heading and not heading.startswith("مدخل"):
                current_headings.append(heading)
            continue
        if line.startswith("#"):
            text_line = line.lstrip("# ").rstrip()
            if is_subheading(line):
                tag = MS_RE.sub("", text_line).strip()
                if tag and tag not in ("فصل", "مدخل"):
                    current_headings.append(tag)
            buffer.append(text_line)
            continue
        if line.startswith("~~"):
            buffer.append(line.lstrip("~ ").rstrip())
            continue
        buffer.append(line.strip())
    flush(current_page)
    return pages


def to_candidates(
    pages: list[dict],
    id_prefix: str,
    madhhab: str,
    work: str,
    author: str,
    edition: str,
    license_: str,
    provenance: str,
    extra_tags: list[str],
) -> list[dict]:
    out = []
    for p in pages:
        tags = list(dict.fromkeys(["hajj", "الحج", madhhab, *extra_tags, *p["headings"]]))
        hint = f"PageV01P{p['page']:03d} (page hint from digitization; confirm at sign-off)"
        prov = f"{provenance} {hint}"
        out.append(
            {
                "id": f"{id_prefix}_p{p['page']:03d}",
                "madhhab": madhhab,
                "work": work,
                "author": author,
                "edition": edition,
                "volume": None,
                "page": None,
                "text": p["text"],
                "topic_tags": tags,
                "mutamad": None,
                "verified": False,
                "provenance": prov,
                "license": license_,
                "verified_by": None,
                "verified_at": None,
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--id-prefix", required=True)
    ap.add_argument("--section", required=True)
    ap.add_argument("--madhhab", default="maliki")
    ap.add_argument("--work", required=True)
    ap.add_argument("--author", required=True)
    ap.add_argument("--edition", required=True)
    ap.add_argument("--license", required=True, dest="license_")
    ap.add_argument("--provenance", required=True)
    ap.add_argument("--tag", action="append", default=[], dest="tags")
    ap.add_argument(
        "--end-with",
        default=None,
        dest="end_with",
        help="stop at first following header line starting with this text "
        "(e.g. next كتاب title); default: next باب/كتاب chapter header",
    )
    args = ap.parse_args()

    text = pathlib.Path(args.input).read_text(encoding="utf-8")
    pages = parse_markdown_section(text, args.section, end_with=args.end_with)
    candidates = to_candidates(
        pages,
        args.id_prefix,
        args.madhhab,
        args.work,
        args.author,
        args.edition,
        args.license_,
        args.provenance,
        args.tags,
    )
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {len(candidates)} candidates to {out}")


if __name__ == "__main__":
    main()
