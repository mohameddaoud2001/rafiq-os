import hashlib
import json
import pathlib
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from rafiq.config import settings
from rafiq.core.messages import BANNERS

DECISIONS = {"APPROVED", "REJECTED", "EDITED"}

# What kind of dossier: a masala (ruling question) or a knowledge gap logged by
# the KICKOFF fail-safe (no signed or unsigned source found).
DOSSIER_KINDS = {"masala", "gap"}


class Dossier(BaseModel):
    id: str
    query: str
    masala: str
    kind: str = "masala"
    per_madhhab: Dict[str, Any] = {}
    hadith: Dict[str, Any] = {}
    waqi: Dict[str, Any] = {}
    warnings: List[str] = []
    banners: List[str] = []
    status: str = "PENDING"  # PENDING, APPROVED, EDITED, REJECTED
    created_at: float
    reviewers: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []
    unsigned_hits: List[str] = []
    seal: Optional[str] = None
    previous_audit_hash: Optional[str] = None


DOSSIER_DIR = pathlib.Path("data/dossiers")
DOSSIER_DIR.mkdir(parents=True, exist_ok=True)


def create_dossier(
    query: str,
    per_madhhab: Dict,
    hadith: Dict,
    waqi: Dict,
    warnings: List[str],
    previous_audit_hash: str = None,
    kind: str = "masala",
    unsigned_hits: List[str] = None,
) -> Dossier:
    if kind not in DOSSIER_KINDS:
        raise ValueError(f"dossier kind must be one of {sorted(DOSSIER_KINDS)}")
    did = str(uuid.uuid4())[:8]
    banners = [BANNERS["pending_review"]]
    if unsigned_hits:
        banners.append(BANNERS["unsigned_citations"])
    dossier = Dossier(
        id=did,
        query=query,
        masala=query,
        kind=kind,
        per_madhhab=per_madhhab,
        hadith=hadith,
        waqi=waqi,
        warnings=warnings,
        banners=banners,
        status="PENDING",
        created_at=time.time(),
        unsigned_hits=sorted(set(unsigned_hits or [])),
        previous_audit_hash=previous_audit_hash,
    )
    save_dossier(dossier)
    return dossier


def save_dossier(dossier: Dossier):
    path = DOSSIER_DIR / f"{dossier.id}.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(dossier.model_dump_json(ensure_ascii=False, indent=2))


def load_dossier(dossier_id: str) -> Optional[Dossier]:
    path = DOSSIER_DIR / f"{dossier_id}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return Dossier.model_validate_json(f.read())


def seal_dossier(dossier: Dossier) -> str:
    canonical = {
        "dossier": dossier.model_dump(exclude={"seal"}),
        "reviewers": dossier.reviewers,
        "decisions": dossier.decisions,
        "timestamp": time.time(),
        "previous_audit_hash": dossier.previous_audit_hash,
    }
    j = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(j.encode("utf-8")).hexdigest()
    dossier.seal = h
    save_dossier(dossier)
    return h


def add_decision(
    dossier_id: str,
    reviewer: str,
    decision: str,
    note: str = "",
    edited_version: Dict = None,
    auto: bool = False,
) -> Dossier:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
    if not reviewer or not str(reviewer).strip():
        raise ValueError("reviewer identity required")
    dossier = load_dossier(dossier_id)
    if not dossier:
        raise ValueError("Dossier not found")
    if dossier.status in ("APPROVED", "REJECTED"):
        raise ValueError(f"Dossier already decided: {dossier.status}")
    entry = {
        "reviewer": reviewer,
        "decision": decision,
        "note": note,
        "ts": time.time(),
        "auto": auto,
        "edited_version": edited_version,
    }
    dossier.decisions.append(entry)
    if reviewer not in [r["name"] for r in dossier.reviewers]:
        dossier.reviewers.append({"name": reviewer, "ts": time.time()})

    quorum = max(1, settings.RAFIQ_QUORUM)
    approving = {
        d["reviewer"] for d in dossier.decisions if d["decision"] in ("APPROVED", "EDITED")
    }
    if decision == "REJECTED":
        dossier.status = "REJECTED"
    elif len(approving) >= quorum:
        # quorum reached: EDITED wins over APPROVED if any reviewer amended
        dossier.status = (
            "EDITED" if any(d["decision"] == "EDITED" for d in dossier.decisions) else "APPROVED"
        )
    else:
        dossier.status = "AWAITING_QUORUM"
    if decision == "EDITED" and edited_version:
        dossier.per_madhhab["edited"] = edited_version

    # seal after decision
    seal_dossier(dossier)
    return dossier
