"""审计报告数据模型（Phase 5）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditReport(Base):
    """一次审计任务的报告（Summary + Risk Findings + Evidence Chain）。"""

    __tablename__ = "audit_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    total_claims: Mapped[int] = mapped_column(Integer, default=0)
    supported_count: Mapped[int] = mapped_column(Integer, default=0)
    refuted_count: Mapped[int] = mapped_column(Integer, default=0)
    partially_supported_count: Mapped[int] = mapped_column(Integer, default=0)
    insufficient_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON findings
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 完整审计报告
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 执行日志
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
