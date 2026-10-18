"""Dossier analytics: log every query that hits unsigned passages and rank the
scholar sign-off queue by what users actually ask (most-asked Hajj/Umrah first).

Two local sources feed the ranking:

  - data/analytics/unsigned_hits.jsonl: one append-only record per /ask query
    whose faqih citations included at least one unsigned passage (passage ids +
    normalized query terms). This is the "prioritize sign-off" log.
  - data/dossiers/*.json: the query text of every dossier filed so far, used as
    baseline analytics from day one (262+ dossiers exist before the first hit).

Nothing here changes corpus state or signing: it only orders the review queue
and reports progress. Raw query text stays local, exactly like dossiers; the
hash-chained audit log keeps digests only (rule 12).
"""

import json
import pathlib
import statistics
import threading
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from rafiq.core.audit import append_audit

ANALYTICS_DIR = pathlib.Path("data/analytics")
HITS_PATH = ANALYTICS_DIR / "unsigned_hits.jsonl"
DOSSIER_DIR = pathlib.Path("data/dossiers")

# Fallback per-page review time when no usable sign-off durations exist yet.
DEFAULT_SECONDS_PER_PAGE = 240.0
MIN_MEASURED_SECONDS = 30.0
MAX_MEASURED_SECONDS = 3600.0

# Normalized Hajj/Umrah terms that boost queue priority (the use case is Hajj).
PRIORITY_TERMS = {
    "حج",
    "عمره",
    "احرام",
    "عرفه",
    "مزدلفه",
    "مني",
    "طواف",
    "سعي",
    "هدي",
    "وقوف",
    "مبيت",
    "رمي",
    "جمرات",
    "تحلل",
    "افاضه",
    "وداع",
    "مواقيت",
    "ميقات",
    "حلق",
    "تقصير",
    "صيد",
    "فديه",
    "كفاره",
    "جزاء",
    "دم",
}

# A direct unsigned hit is worth a lot more than topic-term frequency, so the
# passages users already hit are always reviewed first.
_DIRECT_HIT_WEIGHT = 1_000_000
_TERM_WEIGHT = 1
_PRIORITY_TERM_WEIGHT = 3

_lock = threading.Lock()


def _query_terms(query: str) -> List[str]:
    from rafiq.rag.arabic import normalize_for_search
    from rafiq.rag.madhhab_stores import _query_cores

    return _query_cores(normalize_for_search(query))


def record_unsigned_hit(
    query: str,
    madhhab: Optional[str],
    hits: List[Dict[str, Any]],
    intent: str = "general",
    dossier_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one analytics record: this query returned unsigned passages.

    hits: [{"madhhab": ..., "passage_id": ...}] - the unsigned pages served.
    """
    record = {
        "ts": time.time(),
        "query": query,
        "madhhab": madhhab,
        "intent": intent,
        "dossier_id": dossier_id,
        "hits": hits,
        "terms": _query_terms(query),
    }
    with _lock:
        HITS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HITS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    append_audit("unsigned_hit", "system", {"hits": hits, "intent": intent})
    return record


def load_unsigned_hits() -> List[Dict[str, Any]]:
    if not HITS_PATH.exists():
        return []
    records = []
    with open(HITS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def unsigned_hit_counts() -> Counter:
    """(madhhab, passage_id) -> number of queries that hit it unsigned."""
    counts: Counter = Counter()
    for rec in load_unsigned_hits():
        for h in rec.get("hits") or []:
            pid, mh = h.get("passage_id"), h.get("madhhab")
            if pid:
                counts[(mh, pid)] += 1
    return counts


def _dossier_queries() -> List[str]:
    queries = []
    if not DOSSIER_DIR.exists():
        return queries
    for path in DOSSIER_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
            q = data.get("query")
            if q:
                queries.append(q)
        except Exception:
            continue
    return queries


def term_frequencies() -> Counter:
    """How many distinct queries (hits log + dossiers) contained each term."""
    freq: Counter = Counter()
    for rec in load_unsigned_hits():
        for t in set(rec.get("terms") or []):
            freq[t] += 1
    for q in _dossier_queries():
        for t in set(_query_terms(q)):
            freq[t] += 1
    return freq


def _passage_terms(text: str, topic_tags: List[str]) -> List[str]:

    return _query_terms(text + " " + " ".join(topic_tags or []))


def score_passage(p, freq: Counter, direct: Counter) -> Dict[str, Any]:
    cores = set(_passage_terms(p.text, p.topic_tags))
    term_score = sum(freq.get(c, 0) for c in cores)
    priority_score = sum(_PRIORITY_TERM_WEIGHT for c in cores if c in PRIORITY_TERMS)
    direct_hits = direct.get((p.madhhab, p.id), 0)
    return {
        "score": _DIRECT_HIT_WEIGHT * direct_hits + _TERM_WEIGHT * term_score + priority_score,
        "direct_hits": direct_hits,
        "term_score": term_score,
    }


def _reviewable_pending() -> List[Any]:
    """Unsigned real-source pages (seed placeholders can never be signed)."""
    from rafiq.rag.madhhab_stores import MADHHABS, list_passages
    from rafiq.rag.verify_corpus import rejected_passages

    rejected = rejected_passages()
    pending = []
    for madhhab in MADHHABS:
        for p in list_passages(madhhab, verified=False, limit=100000):
            if (p.provenance or "").startswith("seed"):
                continue
            if (p.madhhab, p.id) in rejected:
                continue
            pending.append(p)
    return pending


def prioritized_pending() -> List[Dict[str, Any]]:
    """Sign-off queue ordered by dossier analytics (most asked first)."""
    freq = term_frequencies()
    direct = unsigned_hit_counts()
    scored = []
    for p in _reviewable_pending():
        s = score_passage(p, freq, direct)
        scored.append((s, p))
    # highest score first; direct hits next; then stable by id
    scored.sort(key=lambda t: (-t[0]["score"], -t[0]["direct_hits"], t[1].id))
    return [
        {
            "passage": p.model_dump(),
            "priority_score": s["score"],
            "direct_hits": s["direct_hits"],
            "term_score": s["term_score"],
        }
        for s, p in scored
    ]


def average_signoff_seconds() -> float:
    """Median time between recorded sign-offs; fallback when none usable."""
    from rafiq.rag.verify_corpus import load_verifications

    stamps = []
    for r in load_verifications():
        if r.get("action", "signoff") != "signoff":
            continue
        ts = r.get("verified_at")
        if not ts:
            continue
        try:
            import datetime

            stamps.append(datetime.datetime.fromisoformat(ts).timestamp())
        except ValueError:
            continue
    stamps.sort()
    diffs = [
        b - a
        for a, b in zip(stamps, stamps[1:])
        if MIN_MEASURED_SECONDS <= b - a <= MAX_MEASURED_SECONDS
    ]
    if diffs:
        return float(statistics.median(diffs))
    return DEFAULT_SECONDS_PER_PAGE


def review_progress() -> Dict[str, Any]:
    """signed / reviewable totals + estimated remaining review time.

    Rejected pages leave the backlog (they can never be signed), so pending
    always matches the length of prioritized_pending().
    """
    from rafiq.rag.madhhab_stores import MADHHABS, list_passages
    from rafiq.rag.verify_corpus import rejected_passages

    rejected = rejected_passages()
    signed = total = pending = 0
    for madhhab in MADHHABS:
        for p in list_passages(madhhab, limit=100000):
            if (p.provenance or "").startswith("seed"):
                continue
            if not p.verified and (p.madhhab, p.id) in rejected:
                continue
            total += 1
            if p.verified:
                signed += 1
            else:
                pending += 1
    avg = average_signoff_seconds()
    return {
        "signed": signed,
        "total": total,
        "pending": pending,
        "percent": round(100.0 * signed / total, 1) if total else 0.0,
        "seconds_per_page": int(avg),
        "est_seconds": int(pending * avg),
    }


def queue_with_links(max_items: int = 300) -> List[Dict[str, Any]]:
    """Top of the prioritized queue, enriched with verified scan links and hints.

    Capped so the review page payload stays small; the UI shows real pending
    totals from review_progress() next to the page of items it received.
    """
    from rafiq.rag.source_links import page_hint, scan_links

    items = []
    for item in prioritized_pending()[:max_items]:
        p = item["passage"]
        items.append(
            {
                **p,
                "page_hint": page_hint(p.get("provenance")),
                "scan_links": scan_links(p.get("provenance")),
                "priority_score": item["priority_score"],
                "direct_hits": item["direct_hits"],
            }
        )
    return items
