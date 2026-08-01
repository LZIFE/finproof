"""FinProof Governance Center API Schemas（Phase 20）。"""

from pydantic import BaseModel, Field


class DashboardRequest(BaseModel):
    """治理仪表板请求（可选 company 过滤；默认全聚合）。"""

    company: str | None = Field(default=None, max_length=120)
