"""审计 API Schema（Phase 5）。"""

from pydantic import BaseModel, Field


class AuditCreateRequest(BaseModel):
    document_id: int = Field(ge=1)


class AuditRunOut(BaseModel):
    audit_id: int
    status: str


class AuditSummaryOut(BaseModel):
    total_claims: int = 0
    supported_count: int = 0
    refuted_count: int = 0
    partially_supported_count: int = 0
    insufficient_count: int = 0
    unknown_count: int = 0


class AuditReportOut(BaseModel):
    audit_id: int
    document_id: int
    summary: AuditSummaryOut
    findings: list = []
    evidence_chain: list = []
    verification_results: list = []
    plan: dict | None = None
    risk: dict | None = None  # Phase 6：Overall Risk（score/level/distribution）
