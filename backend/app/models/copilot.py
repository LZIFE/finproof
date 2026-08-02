"""FinProof Copilot 数据模型（Phase 15）。

数据库表（任务书 §5）：
- copilot_sessions   会话（session_id / user_id / created_at / updated_at）
- copilot_messages   会话消息（user / assistant / tools_called / evidence / risk_score）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotSessionRow(Base):
    """Copilot 会话：支持连续追问。"""

    __tablename__ = "copilot_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # CS-XXXX
    user_id: Mapped[str] = mapped_column(String(80), default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CopilotMessageRow(Base):
    """会话消息：保存用户问题与助手回答 + 调用工具 + 结果 + 证据。"""

    __tablename__ = "copilot_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("copilot_sessions.session_id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)  # user / assistant
    content: Mapped[str] = mapped_column(Text)  # 用户问题或助手回答
    intent_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    tools_called_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    verification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
