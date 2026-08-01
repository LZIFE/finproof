"""FinProof Financial Reasoning API Schemas（Phase 16）。"""

from pydantic import BaseModel, Field


class ReasoningRunRequest(BaseModel):
    """推理请求：claim / verification / evidence / KG facts / risk。"""

    claim_text: str = Field(min_length=1, max_length=500)
    claim: dict = Field(default_factory=dict)
    verification_result: dict = Field(default_factory=dict)
    evidence_candidates: list[dict] = Field(default_factory=list)
    knowledge_graph_facts: list[dict] = Field(default_factory=list)
    risk_assessment: dict = Field(default_factory=dict)
    company: str = Field(default="", max_length=120)
    period: str = Field(default="", max_length=20)
