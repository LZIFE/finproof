"""FinProof Autonomous Research Agent 数据模型（Phase 17，任务书 §4）。

数据库表：
- research_sessions   研究会话（company / plan / phase / memo_json）
- research_tasks      研究任务（task_type / status / evidence_json / findings_json）

保存（任务书 §4）：company / plan / tool_calls / evidence / results。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ResearchSessionRow(Base):
    """研究会话：company + plan + phase + memo。"""

    __tablename__ = "research_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # RESEARCH-XXXX
    company: Mapped[str] = mapped_column(String(120), index=True)
    stock_code: Mapped[str] = mapped_column(String(20), default="", index=True)
    phase: Mapped[str] = mapped_column(String(30), default="Planning", index=True)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # ResearchPlan
    tool_calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    memo_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # ResearchMemo
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    tasks_count: Mapped[int] = mapped_column(Integer, default=0)
    tasks_done: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ResearchTaskRow(Base):
    """研究任务：task_type / status / evidence / findings。

    每条记录对应 ResearchPlan.tasks 中的一项任务规格及其执行结果。
    """

    __tablename__ = "research_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(30), index=True)
    category: Mapped[str] = mapped_column(String(20), default="")
    metric: Mapped[str] = mapped_column(String(30), default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="PENDING", index=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # list[EvidenceRef]
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # list[ResearchFinding]
    tool_calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
