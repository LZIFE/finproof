"""投资尽调数据模型（Phase 7）。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestmentMemoRow(Base):
    """Investment Risk Memo：公司尽调风险备忘录。"""

    __tablename__ = "investment_memos"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audit_reports.id", ondelete="CASCADE"), index=True)
    company: Mapped[str] = mapped_column(String(120), default="")
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_period: Mapped[str | None] = mapped_column(String(40), nullable=True)
    overall_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    overall_risk_level: Mapped[str] = mapped_column(String(10), default="LOW")
    key_risks_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 风险分类摘要
    memo_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 完整 memo
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InvestmentReviewRow(Base):
    """单条主张的人工审核记录（NEED_REVIEW / APPROVED / REJECTED）。"""

    __tablename__ = "investment_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    memo_id: Mapped[int] = mapped_column(
        ForeignKey("investment_memos.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[str] = mapped_column(String(64))
    review_status: Mapped[str] = mapped_column(String(20), default="NEED_REVIEW")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
