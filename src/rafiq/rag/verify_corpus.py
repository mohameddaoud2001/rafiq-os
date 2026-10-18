"""Scholar sign-off for corpus passages.

A passage may only become verified:true through sign_off(): an authenticated
scholar (identity passed in from the session) confirms the exact text against
a licensed source. The sign-off is recorded append-only in
data/verifications.jsonl and binds:

  - scholar identity + timestamp
  - sha256 of the exact reviewed text (any later text change invalidates it;
    if the scholar corrected the digitization, the reviewed text itself is
    kept in the record so a store rebuild stays hash-bound)
  - source fields: work, edition, volume, page, provenance, license
  - edition_sha256: sha256 of that exact source-metadata path
  - note

reject() and edit_edition() record the other two review outcomes without ever
signing: verified stays false until sign_off() runs.

verify_check() revalidates every verified passage in every store against
these records (used by `rafiq corpus verify-check` and CI).
"""

import datetime
import hashlib
import json
import pathlib
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from rafiq.core.audit import append_audit
from rafiq.rag.madhhab_stores import MADHHABS, Passage, get_passage, insert_passage, list_passages

VERIFICATIONS_PATH = pathlib.Path("data/verifications.jsonl")
_lock = threading.Lock()

SIGNOFF_REQUIRED_FIELDS = ["work", "edition", "provenance", "license"]
SIGNOFF_FIELDS = ["work", "edition", "volume", "page", "provenance", "license"]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def edition_sha256(fields: Dict[str, Any]) -> str:
    """Bind a record to the exact edition path: work/edition/volume/page/provenance/license."""
    canonical = {f: fields.get(f) for f in SIGNOFF_FIELDS}
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_signoff_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for f in SIGNOFF_REQUIRED_FIELDS:
        v = fields.get(f)
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"sign-off requires a non-empty {f}")
        clean[f] = v.strip()
    for f in ["volume", "page"]:
        v = fields.get(f)
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValueError(f"sign-off requires numeric {f}")
        if iv < 1:
            raise ValueError(f"sign-off requires {f} >= 1")
        clean[f] = iv
    return clean


def _reviewed_text(passage: Passage, text: Optional[str]) -> str:
    if text is None:
        return passage.text
    if not isinstance(text, str) or not text.strip():
        raise ValueError("reviewed text cannot be empty")
    return text.strip()


def _append_record(record: Dict[str, Any]) -> None:
    with _lock:
        VERIFICATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFICATIONS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def sign_off(
    madhhab: str,
    passage_id: str,
    scholar: str,
    fields: Dict[str, Any],
    note: str = "",
    text: Optional[str] = None,
) -> Passage:
    """Promote a passage to verified:true after a scholar confirms it against the source.

    text: the exact text the scholar reviewed (may carry their OCR corrections);
    when omitted the stored text is signed. This is the ONLY path that sets
    verified:true, and it stores sheikh id, timestamp and edition_sha256.
    """
    if not scholar or not scholar.strip():
        raise ValueError("scholar identity required")
    passage = get_passage(madhhab, passage_id)
    if passage is None:
        raise ValueError(f"passage not found: {madhhab}/{passage_id}")
    clean = _validate_signoff_fields(fields)
    reviewed_text = _reviewed_text(passage, text)
    verified_at = datetime.datetime.now(datetime.UTC).isoformat()
    record = {
        "action": "signoff",
        "passage_id": passage_id,
        "madhhab": madhhab,
        "text_sha256": text_sha256(reviewed_text),
        **clean,
        "edition_sha256": edition_sha256(clean),
        "verified_by": scholar.strip(),
        "verified_at": verified_at,
        "note": note or "",
    }
    if reviewed_text != passage.text:
        record["reviewed_text"] = reviewed_text
    _append_record(record)

    updated = passage.model_copy(
        update={
            "verified": True,
            "text": reviewed_text,
            "work": clean["work"],
            "edition": clean["edition"],
            "volume": clean["volume"],
            "page": clean["page"],
            "provenance": clean["provenance"],
            "license": clean["license"],
            "verified_by": record["verified_by"],
            "verified_at": verified_at,
        }
    )
    insert_passage(madhhab, updated)
    append_audit(
        "corpus_signoff",
        record["verified_by"],
        {
            "madhhab": madhhab,
            "passage_id": passage_id,
            "work": clean["work"],
            "volume": clean["volume"],
            "page": clean["page"],
            "edition_sha256": record["edition_sha256"],
        },
    )
    return updated


def reject(madhhab: str, passage_id: str, reviewer: str, reason: str = "") -> Passage:
    """Record a reviewer rejection (bad digitization / not the printed text).

    The passage stays verified:false and is excluded from the review queue.
    Signed passages must be revoked, never rejected.
    """
    if not reviewer or not reviewer.strip():
        raise ValueError("reviewer identity required")
    if not reason or not reason.strip():
        raise ValueError("rejection requires a reason")
    passage = get_passage(madhhab, passage_id)
    if passage is None:
        raise ValueError(f"passage not found: {madhhab}/{passage_id}")
    if passage.verified:
        raise ValueError("passage is signed; use revoke instead of reject")
    record = {
        "action": "reject",
        "passage_id": passage_id,
        "madhhab": madhhab,
        "rejected_by": reviewer.strip(),
        "rejected_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "reason": reason.strip(),
    }
    _append_record(record)
    append_audit(
        "corpus_reject",
        record["rejected_by"],
        {"madhhab": madhhab, "passage_id": passage_id},
    )
    return passage


def edit_edition(
    madhhab: str,
    passage_id: str,
    reviewer: str,
    fields: Dict[str, Any],
    text: Optional[str] = None,
    note: str = "",
) -> Passage:
    """Save a reviewer's edition/text corrections WITHOUT signing.

    work/edition/provenance/license (and the corrected text, if any) are stored
    so the next reviewer starts from the fix; volume/page stay null in the store
    until sign_off() confirms them (no unverified page numbers), but the proposed
    values are kept in the append-only record. verified stays false.
    """
    if not reviewer or not reviewer.strip():
        raise ValueError("reviewer identity required")
    passage = get_passage(madhhab, passage_id)
    if passage is None:
        raise ValueError(f"passage not found: {madhhab}/{passage_id}")
    if passage.verified:
        raise ValueError("passage is signed; revoke before editing its source fields")
    clean = _validate_signoff_fields(fields)
    reviewed_text = _reviewed_text(passage, text)
    record = {
        "action": "edit_edition",
        "passage_id": passage_id,
        "madhhab": madhhab,
        **clean,
        "text_sha256": text_sha256(reviewed_text),
        "edition_sha256": edition_sha256(clean),
        "edited_by": reviewer.strip(),
        "edited_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "note": note or "",
    }
    if reviewed_text != passage.text:
        record["reviewed_text"] = reviewed_text
    _append_record(record)

    updated = passage.model_copy(
        update={
            "text": reviewed_text,
            "work": clean["work"],
            "edition": clean["edition"],
            "provenance": clean["provenance"],
            "license": clean["license"],
        }
    )
    insert_passage(madhhab, updated)
    append_audit(
        "corpus_edit_edition",
        record["edited_by"],
        {"madhhab": madhhab, "passage_id": passage_id, "work": clean["work"]},
    )
    return updated


def rejected_passages() -> Set[Tuple[str, str]]:
    """(madhhab, passage_id) of passages whose latest record is a rejection."""
    latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in load_verifications():
        pid, mh = r.get("passage_id"), r.get("madhhab")
        if pid and mh:
            latest[(mh, pid)] = r
    return {(mh, pid) for (mh, pid), r in latest.items() if r.get("action") == "reject"}


def revoke(madhhab: str, passage_id: str, revoked_by: str, reason: str = "") -> Passage:
    """Revoke a sign-off (false attestation or later concern); passage returns to unverified."""
    if not revoked_by or not revoked_by.strip():
        raise ValueError("revoking identity required")
    if not reason or not reason.strip():
        raise ValueError("revocation requires a reason")
    passage = get_passage(madhhab, passage_id)
    if passage is None:
        raise ValueError(f"passage not found: {madhhab}/{passage_id}")
    record = {
        "action": "revoke",
        "passage_id": passage_id,
        "madhhab": madhhab,
        "revoked_by": revoked_by.strip(),
        "revoked_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "reason": reason.strip(),
    }
    with _lock:
        VERIFICATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFICATIONS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    updated = passage.model_copy(
        update={
            "verified": False,
            "verified_by": None,
            "verified_at": None,
            "volume": None,
            "page": None,
        }
    )
    insert_passage(madhhab, updated)
    append_audit(
        "corpus_revoke",
        record["revoked_by"],
        {"madhhab": madhhab, "passage_id": passage_id, "reason": record["reason"]},
    )
    return updated


def load_verifications() -> List[Dict[str, Any]]:
    if not VERIFICATIONS_PATH.exists():
        return []
    records = []
    with open(VERIFICATIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def latest_record(passage_id: str, madhhab: str) -> Optional[Dict[str, Any]]:
    found = None
    for r in load_verifications():
        if r.get("passage_id") == passage_id and r.get("madhhab") == madhhab:
            found = r
    return found


def latest_verification(passage_id: str, madhhab: str) -> Optional[Dict[str, Any]]:
    rec = latest_record(passage_id, madhhab)
    if rec is None or rec.get("action", "signoff") != "signoff":
        return None
    return rec


def _record_text(p: Passage, r: Dict[str, Any]) -> Optional[str]:
    """Text this record binds: the stored reviewed text, or None if unverifiable."""
    reviewed = r.get("reviewed_text")
    if reviewed is not None:
        if text_sha256(reviewed) != r.get("text_sha256"):
            return None
        return reviewed
    if text_sha256(p.text) != r.get("text_sha256"):
        return None
    return p.text


def apply_verifications() -> int:
    """Re-apply the latest record per passage to the stores.

    Keeps DB state consistent with the append-only record file after a store
    rebuild (seed reload, re-index). Text hash must still match (or the record
    carries the reviewed text); revoked and rejected passages are reverted,
    never restored; edit_edition records restore corrections without signing.
    """
    latest: Dict[tuple, Dict[str, Any]] = {}
    for r in load_verifications():
        pid, mh = r.get("passage_id"), r.get("madhhab")
        if pid and mh:
            latest[(mh, pid)] = r
    applied = 0
    for (mh, pid), r in latest.items():
        p = get_passage(mh, pid)
        if p is None:
            continue
        action = r.get("action", "signoff")
        if action == "reject":
            continue
        if action == "edit_edition":
            new_text = _record_text(p, r)
            if new_text is None:
                continue
            safe_fields = ["work", "edition", "provenance", "license"]
            updates = {f: r.get(f) for f in safe_fields}
            if (
                not p.verified
                and p.text == new_text
                and all(getattr(p, f) == updates[f] for f in safe_fields)
            ):
                continue
            updated = p.model_copy(
                update={
                    **updates,
                    "text": new_text,
                    "verified": False,
                    "verified_by": None,
                    "verified_at": None,
                    "volume": None,
                    "page": None,
                }
            )
            insert_passage(mh, updated)
            applied += 1
            continue
        if action != "signoff":
            if p.verified:
                insert_passage(
                    mh,
                    p.model_copy(
                        update={
                            "verified": False,
                            "verified_by": None,
                            "verified_at": None,
                            "volume": None,
                            "page": None,
                        }
                    ),
                )
                applied += 1
            continue
        new_text = _record_text(p, r)
        if new_text is None:
            continue
        fields = SIGNOFF_FIELDS
        if (
            p.verified
            and p.text == new_text
            and p.verified_by == r.get("verified_by")
            and p.verified_at == r.get("verified_at")
            and all(getattr(p, f) == r.get(f) for f in fields)
        ):
            continue
        updated = p.model_copy(
            update={
                "verified": True,
                "text": new_text,
                "verified_by": r.get("verified_by"),
                "verified_at": r.get("verified_at"),
                **{f: r.get(f) for f in fields},
            }
        )
        insert_passage(mh, updated)
        applied += 1
    return applied


def verify_check() -> Dict[str, Any]:
    """Every verified passage must have a sign-off record matching its current text and source."""
    mismatches: List[Dict[str, Any]] = []
    checked = 0
    for madhhab in MADHHABS:
        for p in list_passages(madhhab, verified=True):
            checked += 1
            rec = latest_verification(p.id, madhhab)
            if not rec:
                raw = latest_record(p.id, madhhab)
                if raw is not None and raw.get("action") == "revoke":
                    reason = f"revoked but still verified: {raw.get('reason', '')}"
                else:
                    reason = "no sign-off record"
                mismatches.append({"madhhab": madhhab, "passage_id": p.id, "reason": reason})
                continue
            if rec.get("text_sha256") != text_sha256(p.text):
                mismatches.append(
                    {
                        "madhhab": madhhab,
                        "passage_id": p.id,
                        "reason": "text changed since sign-off",
                    }
                )
                continue
            rec_edition = rec.get("edition_sha256")
            if rec_edition and rec_edition != edition_sha256(
                {f: rec.get(f) for f in SIGNOFF_FIELDS}
            ):
                mismatches.append(
                    {
                        "madhhab": madhhab,
                        "passage_id": p.id,
                        "reason": "edition record hash invalid",
                    }
                )
                continue
            for f in SIGNOFF_FIELDS:
                if rec.get(f) != getattr(p, f):
                    mismatches.append(
                        {
                            "madhhab": madhhab,
                            "passage_id": p.id,
                            "reason": f"field changed since sign-off: {f}",
                        }
                    )
                    break
    return {"ok": not mismatches, "checked": checked, "mismatches": mismatches}
