"""投资情报 API Schema（Phase 8）。"""

from pydantic import BaseModel, Field


class IntelligenceRunRequest(BaseModel):
    """运行投资调查请求：投资观点 + 可选外部事实。"""

    document_id: int = Field(ge=1)
    claims: list[dict] = Field(default_factory=list)  # [{claim_id, claim, dimension?, value?, unit?, period?}]
    external_facts: list[dict] = Field(default_factory=list)  # [{dimension, statement, source, evidence, timestamp, confidence, ...}]


class IntelligenceGetRequest(BaseModel):
    report_id: int = Field(ge=1)
