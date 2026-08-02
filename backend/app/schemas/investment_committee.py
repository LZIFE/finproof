"""投资委员会 API Schema（Phase 9）。"""

from pydantic import BaseModel, Field


class CommitteeRunRequest(BaseModel):
    """运行投资委员会审核请求。"""

    document_id: int = Field(ge=1)
    audit_id: int | None = Field(default=None, ge=1)
    intelligence_report_id: int | None = Field(default=None, ge=1)


class ReviewUpdateRequest(BaseModel):
    item_id: str
    review_status: str = Field(pattern="^(NEED_REVIEW|APPROVED|REJECTED)$")
    note: str = ""
    reviewer: str = ""
