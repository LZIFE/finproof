"""Governance / Audit Trail API Schema（Phase 12）。"""

from pydantic import BaseModel, Field


class AuditLogCreate(BaseModel):
    user: str = Field(default="system", max_length=80)
    action: str = Field(min_length=1, max_length=80)
    target_type: str | None = Field(default=None, max_length=60)
    target_id: int | None = Field(default=None, ge=1)
    model_version: str = Field(default="", max_length=40)
    rule_version: str = Field(default="", max_length=40)
    evidence_used: list[dict] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)
