"""Printable scholar review worksheet for real-text candidates.

Lists unverified passages that come from real sources (provenance not
'seed_...') with their page hints, so a scholar can check them against a
print edition offline. Sign-off itself still happens at /dashboard/corpus
under the scholar's own account - this sheet only speeds up the review.
"""

import datetime
import html
import pathlib
import re
from typing import Optional

from rafiq.rag.madhhab_stores import list_passages

PAGE_HINT_RE = re.compile(r"PageV(\d+)P(\d+)")

INSTRUCTIONS_AR = """
<p>راجع كل نص في هذا الجدول مقابل النسخة المطبوعة المذكورة، ثم وقّع النصوص المطابقة
في لوحة التوثيق <code>/dashboard/corpus</code> بحسابك الخاص. النصوص غير المطابقة:
لا توقّعها وأبلغ مدير النظام.</p>
"""


def build_review_sheet(
    madhhab: str = "maliki", out_path: Optional[pathlib.Path] = None
) -> pathlib.Path:
    out_path = out_path or pathlib.Path(f"data/review_sheet_{madhhab}.html")
    rows = []
    for p in list_passages(madhhab, verified=False, limit=10000):
        prov = p.provenance or ""
        if prov.startswith("seed"):
            continue
        m = PAGE_HINT_RE.search(prov)
        hint = f"ج{p.volume or '?'} ص{int(m.group(2))}" if m else "—"
        rows.append(
            {
                "id": p.id,
                "work": p.work or "",
                "edition": p.edition or "",
                "hint": hint,
                "text": p.text,
                "provenance": prov,
            }
        )

    parts = [
        "<!DOCTYPE html>",
        '<html dir="rtl" lang="ar">',
        "<head><meta charset='utf-8'>",
        f"<title>ورقة مراجعة النصوص - {html.escape(madhhab)}</title>",
        "<style>",
        "body{font-family:serif;margin:2em;color:#111}",
        "table{border-collapse:collapse;width:100%}",
        "th,td{border:1px solid #777;padding:8px;vertical-align:top;font-size:14px}",
        "th{background:#eee}",
        ".meta{font-size:12px;color:#555}",
        ".box{width:14px;height:14px;border:1px solid #000;display:inline-block}",
        "@media print{body{margin:0.5em}}",
        "</style></head><body>",
        f"<h1>ورقة مراجعة النصوص — مذهب {html.escape(madhhab)}</h1>",
        f"<p class='meta'>أُنشئت: {datetime.date.today().isoformat()} — "
        f"عدد النصوص: {len(rows)} (النصوص قيد التوثيق من مصادر حقيقية فقط)</p>",
        INSTRUCTIONS_AR,
        "<table><thead><tr>",
        "<th>#</th><th>الكتاب والطبعة</th><th>الصفحة (تلميح)</th>"
        "<th>النص</th><th>مطابق؟</th><th>ملاحظة</th>",
        "</tr></thead><tbody>",
    ]
    for i, r in enumerate(rows, start=1):
        parts.append("<tr>")
        parts.append(f"<td>{i}<div class='meta'>{html.escape(r['id'])}</div></td>")
        parts.append(
            f"<td>{html.escape(r['work'])}<div class='meta'>{html.escape(r['edition'])}</div></td>"
        )
        parts.append(f"<td>{html.escape(r['hint'])}</td>")
        parts.append(
            f"<td>{html.escape(r['text']).replace(chr(10), '<br>')}"
            f"<div class='meta'>{html.escape(r['provenance'][:140])}</div></td>"
        )
        parts.append("<td><span class='box'></span> نعم<br><span class='box'></span> لا</td>")
        parts.append("<td></td>")
        parts.append("</tr>")
    parts += ["</tbody></table>", "</body></html>"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return out_path
