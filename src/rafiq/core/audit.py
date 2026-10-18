import hashlib
import json
import pathlib
import threading
import time
from typing import Any, Dict

AUDIT_PATH = pathlib.Path("data/audit.jsonl")
_lock = threading.Lock()


def _hash_record(prev_hash: str, record: Dict[str, Any]) -> str:
    # canonical JSON without hash field
    payload = json.dumps(record, sort_keys=True, ensure_ascii=False)
    to_hash = f"{prev_hash}|{payload}"
    return hashlib.sha256(to_hash.encode("utf-8")).hexdigest()


def get_last_hash() -> str:
    if not AUDIT_PATH.exists():
        return "0" * 64
    try:
        with open(AUDIT_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines:
                return "0" * 64
            last = json.loads(lines[-1])
            return last.get("hash", "0" * 64)
    except Exception:
        return "0" * 64


def append_audit(event: str, actor: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        prev_hash = get_last_hash()
        ts = time.time()
        # store digest, not raw user text per rule 12
        payload_digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        record = {
            "ts": ts,
            "event": event,
            "actor": actor,
            "payload_digest": payload_digest,
            "prev_hash": prev_hash,
        }
        h = _hash_record(prev_hash, record)
        record["hash"] = h
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record


def verify_chain() -> Dict[str, Any]:
    if not AUDIT_PATH.exists():
        return {"ok": True, "records": 0, "first_bad_index": None}
    with open(AUDIT_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    prev = "0" * 64
    for idx, line in enumerate(lines):
        try:
            rec = json.loads(line)
            h = rec.get("hash")
            # reconstruct hash
            rec_copy = {k: v for k, v in rec.items() if k != "hash"}
            expected = _hash_record(prev, rec_copy)
            if h != expected:
                return {"ok": False, "records": len(lines), "first_bad_index": idx}
            prev = h
        except Exception:
            return {"ok": False, "records": len(lines), "first_bad_index": idx}
    return {"ok": True, "records": len(lines), "first_bad_index": None}
