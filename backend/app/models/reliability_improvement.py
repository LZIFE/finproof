"""FinProof Reliability Improvement 数据模型（Phase 23，任务书 §数据库）。

reliability_reports 表：持久化 Reliability Improvement Report。
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReliabilityReportRow(Base):
    """AI 可靠性改进报告持久化。"""

    __tablename__ = "reliability_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # REL-IMPROVE-XXXX
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    total_failures: Mapped[int] = mapped_column(Integer, default=0)
    overall_failure_rate: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    patterns_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # list[FailurePattern]
    trend_json: Mapped[str | None] = mapped_column(Text, nullable=True)    # ReliabilityTrend
    sources_analyzed_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_improvements_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
