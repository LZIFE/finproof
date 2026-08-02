"""FinProof Copilot API Schemas（Phase 15）。"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Copilot 对话请求。"""

    query: str = Field(min_length=1, max_length=500)
    session_id: str | None = Field(default=None, max_length=40)  # 若空则新建会话
    user_id: str = Field(default="default", max_length=80)
