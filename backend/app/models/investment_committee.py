"""投资委员会报告数据模型（Phase 9）。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CommitteeReportRow(Base):
    """Investment Committee Report：多 Agent 投资审核报告。

    含 Executive Summary / Research Findings / Risk Findings /
        Compliance Findings / Evidence Chain / Human Review Items
        （JSON 序列化），并保留 agent_flow_json 用于前端流程展示。
    """

    __tablename__ = "committee_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[int | None] = mapped_column(
        ForeignKey("audit_reports.id", ondelete="CASCADE"), nullable=True, index=True
    )
    intelligence_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("intelligence_reports.id", ondelete="CASCADE"), nullable=True, index=True
    )
    company: Mapped[str] = mapped_column(String(120), default="")
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_period: Mapped[str | None] = mapped_column(String(40), nullable=True)
    overall_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    overall_risk_level: Mapped[str] = mapped_column(String(10), default="LOW")
    overall_compliance_score: Mapped[float] = mapped_column(Float, default=0.0)
    agent_flow_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Agent 执行流程
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 完整报告
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
