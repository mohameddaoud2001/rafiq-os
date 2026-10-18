from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Finding(BaseModel):
    source_id: str
    excerpt: str
    work: Optional[str] = None
    author: Optional[str] = None
    edition: Optional[str] = None
    volume: Optional[int] = None
    page: Optional[int] = None
    mutamad: Optional[bool] = None
    verified: bool = False
    madhhab: Optional[str] = None
    topic_tags: List[str] = []
    provenance: Optional[str] = None
    scan_url: Optional[str] = None


class AgentOutput(BaseModel):
    agent: str
    status: str  # ok, not_found, insufficient_data, blocked
    findings: List[Finding] = []
    informational_only: bool = False
    disclaimers: List[str] = []
    data_source: str = "sim"
    extra: Dict[str, Any] = {}


class RoutePlan(BaseModel):
    agents: List[str]
    reasons: Dict[str, str] = {}
    intent: str = "general"
    risk_flags: List[str] = []
    skipped: List[str] = []


class RafiqState(BaseModel):
    query: str
    madhhab: Optional[str] = None
    tariqa: Optional[str] = None
    location: Optional[str] = None
    lang: Optional[str] = "ar"
    route_plan: Optional[RoutePlan] = None
    agent_outputs: List[AgentOutput] = []
    dossier_id: Optional[str] = None
    warnings: List[str] = []
    flags: List[str] = []
    is_ruling_seeking: bool = False
    banners: List[str] = []
