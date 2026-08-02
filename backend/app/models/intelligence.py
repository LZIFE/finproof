"""投资情报数据模型（Phase 8）。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IntelligenceReportRow(Base):
    """Investment Intelligence Report：投资情报报告。

    含 Company Profile / Verified Facts / Conflicts /
        Risk Findings / Evidence Chain（JSON 序列化）。
    """

    __tablename__ = "intelligence_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    company: Mapped[str] = mapped_column(String(120), default="")
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_period: Mapped[str | None] = mapped_column(String(40), nullable=True)
    overall_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    overall_risk_level: Mapped[str] = mapped_column(String(10), default="LOW")
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    support_count: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 完整报告
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
