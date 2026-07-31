"""风险评分数据模型（Phase 6）。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RiskAssessmentRow(Base):
    """单条主张的风险评估（对应一次审计核验结果）。"""

    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audit_reports.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[str] = mapped_column(String(64), index=True)
    verification_status: Mapped[str] = mapped_column(String(40))
    verification_type: Mapped[str] = mapped_column(String(40))
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(10))
    risk_type: Mapped[str] = mapped_column(String(30))
    risk_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
