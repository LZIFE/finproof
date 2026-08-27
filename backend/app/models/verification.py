"""核验结果数据模型（Phase 4B.1）。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class VerificationRun(Base):
    """一次核验任务（批量 claim_ids）。"""

    __tablename__ = "verification_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="RULE_BASED")
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    results: Mapped[list["VerificationResultRow"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class VerificationResultRow(Base):
    """单条主张的核验结果。"""

    __tablename__ = "verification_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    verification_run_id: Mapped[int] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[str] = mapped_column(String(64), index=True)
    verification_status: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    verification_type: Mapped[str] = mapped_column(String(40))
    matched_evidence_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组
    calculation_detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 对象
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 来源风险标签 JSON 数组（FORECAST_AS_FACT/SINGLE_SOURCE/OUTDATED_DATA/SELECTIVE_CITATION）
    source_risk_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["VerificationRun"] = relationship(back_populates="results")
