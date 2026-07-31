"""证据检索 API Schema（Phase 4A Oracle 模式）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RetrievalRunCreateRequest(BaseModel):
    input_mode: str = Field(default="ORACLE_GOLD", pattern="^(ORACLE_GOLD|SYSTEM_EXTRACTED)$")
    dataset: str = Field(default="demo", pattern="^(demo|holdout)$")
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset: str
    input_mode: str
    status: str
    top_k: int
    retrieval_version: str
    claim_count: int
    duration_ms: int
    created_at: datetime


class EvidenceCandidateOut(BaseModel):
    rank: int
    document_id: int
    page_number: int
    block_id: int | None = None
    final_score: float
    metric_score: float
    value_score: float
    period_score: float
    entity_score: float
    text_score: float
    matched_terms: list[str] = []
    retrieval_method: str = "structured"
    block_text: str | None = None
    evidence_type: str = "UNKNOWN"
    evidence_quality_score: float = 0.3
    evidence_rank_reason: str | None = None
    evidence_tier: str = "secondary"


class ClaimCandidatesOut(BaseModel):
    claim_id: str
    candidates: list[EvidenceCandidateOut] = []


class RetrievalClaimsOut(BaseModel):
    retrieval_run_id: int
    claim_count: int
    claims: list[ClaimCandidatesOut] = []
