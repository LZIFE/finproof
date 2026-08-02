"""Autonomous Investigation Agent Schemas（Phase 13）。"""

from pydantic import BaseModel, Field


class InvestigationRequest(BaseModel):
    """启动自主调查请求。"""

    claim_text: str = Field(min_length=1, max_length=500)
    claim_type: str = Field(default="", max_length=40)  # 若空则自动分类
    risk_type: str = Field(default="", max_length=40)
    company: str = Field(default="", max_length=120)
    stock_code: str = Field(default="", max_length=20)
    claim: dict = Field(default_factory=dict)  # 原始 claim dict（供工具调用）
    verification_result: dict = Field(default_factory=dict)  # 已有核验结果（可选）
    use_memory: bool = Field(default=True)  # 是否查询/更新 Agent Memory
