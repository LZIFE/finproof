"""投资尽调 API Schema（Phase 7）。"""

from pydantic import BaseModel, Field


class InvestmentMemoCreateRequest(BaseModel):
    audit_id: int = Field(ge=1)


class ReviewUpdateRequest(BaseModel):
    claim_id: str
    review_status: str = Field(pattern="^(NEED_REVIEW|APPROVED|REJECTED)$")
    note: str = ""
    reviewer: str = ""
