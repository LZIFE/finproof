"""核验 API Schema（Phase 4B.1）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VerificationCreateRequest(BaseModel):
    claim_ids: list[str] = Field(min_length=1)
    mode: str = Field(default="RULE_BASED", pattern="^(RULE_BASED)$")


class VerificationResultOut(BaseModel):
    claim_id: str
    verification_status: str
    confidence: float
    verification_type: str
    matched_evidence_ids: list = []
    calculation_detail: dict | None = None
    reason: str = ""
    source_risk_tags: list = []


class VerificationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mode: str
    claim_count: int
    status: str
    created_at: datetime


class VerificationDetailOut(BaseModel):
    run: VerificationRunOut
    results: list[VerificationResultOut] = []
