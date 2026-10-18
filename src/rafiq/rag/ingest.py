import json
import pathlib
from typing import Any, Dict

from rafiq.rag.madhhab_stores import Passage, insert_passage

VERIFIED_REQUIRED_FIELDS = [
    "work",
    "edition",
    "volume",
    "page",
    "provenance",
    "license",
    "verified_by",
    "verified_at",
]


def validate_passage(data: Dict[str, Any]) -> Passage:
    # Schema validation per spec
    required = ["id", "madhhab", "text"]
    for r in required:
        if r not in data:
            raise ValueError(f"Missing required field: {r}")
    verified = data.get("verified", False)
    if verified:
        # verified:true must carry full provenance incl. license and verifier identity
        for f in VERIFIED_REQUIRED_FIELDS:
            if (
                f not in data
                or data[f] is None
                or (isinstance(data[f], str) and not data[f].strip())
            ):
                raise ValueError(f"verified:true requires field {f}")
    else:
        # verified:false must have volume null, page null
        if data.get("volume") is not None or data.get("page") is not None:
            raise ValueError("verified:false must have volume:null and page:null")
    return Passage(**data)


def ingest_file(path: pathlib.Path):
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            passage = validate_passage(data)
            insert_passage(passage.madhhab, passage)
            count += 1
    return count


def check_corpus_file(path: pathlib.Path) -> Dict[str, Any]:
    """Dry-run validation report for a corpus jsonl file (used by `rafiq corpus check`)."""
    report: Dict[str, Any] = {
        "file": str(path),
        "total": 0,
        "verified": 0,
        "unverified": 0,
        "errors": [],
    }
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            report["total"] += 1
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                report["errors"].append({"line": lineno, "error": f"invalid json: {e}"})
                continue
            try:
                passage = validate_passage(data)
            except Exception as e:
                report["errors"].append({"line": lineno, "id": data.get("id"), "error": str(e)})
                continue
            if passage.verified:
                report["verified"] += 1
            else:
                report["unverified"] += 1
    report["ok"] = not report["errors"]
    return report
