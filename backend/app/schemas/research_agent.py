"""FinProof Autonomous Research Agent API Schemas（Phase 17）。"""

from pydantic import BaseModel, Field


class ResearchRunRequest(BaseModel):
    """研究启动请求：company / stock_code。"""

    company: str = Field(min_length=1, max_length=120)
    stock_code: str = Field(default="", max_length=20)
