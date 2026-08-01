"""FinProof Agent Arena API Schemas（Phase 19）。"""

from pydantic import BaseModel, Field


class ArenaRunRequest(BaseModel):
    """竞技启动请求：company + research_question。"""

    company: str = Field(min_length=1, max_length=120)
    research_question: str = Field(min_length=1, max_length=300)
