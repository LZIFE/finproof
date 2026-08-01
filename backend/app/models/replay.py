"""FinProof Replay 数据模型（Phase 21，任务书 §数据库）。

audit_replay_events 表：将已有审计流程转化为可视化回放事件。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditReplayEventRow(Base):
    """审计回放事件（任务书 §数据库字段）。"""

    __tablename__ = "audit_replay_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[str] = mapped_column(String(80), index=True)  # 关联既有 audit/run id
    event_type: Mapped[str] = mapped_column(String(30), index=True)  # claim_event / evidence_event / verification_event / risk_event / agent_event / conclusion_event
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(60), default="")  # 来源（AI / Evidence Retrieval / Verification / Risk Engine / Analyst / Skeptic / Auditor / Judge）
    content: Mapped[str] = mapped_column(Text, default="")  # 结果
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)  # 证据引用（JSON 或纯文本）
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 来源模块
    evidence_summary: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
