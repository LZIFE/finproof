"""Structured financial fact store (Phase 23.11 Channel A source).

Stores ONLY structured facts extracted from DocumentBlock + TableContext.
Forbidden fields: gold_page, gold_block_id, expected_verdict,
claim_id-specific weights, is-correct-answer labels, dev-set labels.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FinancialFact(Base):
    """Structured financial fact (one row per table cell / fact record).

    Channel A source for STRUCTURED_NUMERIC / TABLE_METRIC /
    PERIOD_COMPARISON / SCOPE_VALIDATION routes.
    """

    __tablename__ = "financial_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    company: Mapped[str] = mapped_column(String(128), index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    document_type: Mapped[str] = mapped_column(String(32), default="annual_report")
    page: Mapped[int] = mapped_column(Integer, index=True)
    table_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    section_title: Mapped[str] = mapped_column(String(256), default="")
    table_title: Mapped[str] = mapped_column(String(256), default="")
    row_header: Mapped[str] = mapped_column(String(256), index=True, default="")
    parent_row_header: Mapped[str] = mapped_column(String(256), default="")
    column_header: Mapped[str] = mapped_column(String(256), default="")
    period_header: Mapped[str] = mapped_column(String(128), default="")
    metric: Mapped[str] = mapped_column(String(128), index=True, default="")
    metric_canonical: Mapped[str] = mapped_column(String(64), index=True, default="")
    period: Mapped[str] = mapped_column(String(32), index=True, default="")
    period_type: Mapped[str] = mapped_column(String(16), default="")
    unit: Mapped[str] = mapped_column(String(16), index=True, default="")
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    scope: Mapped[str] = mapped_column(String(32), index=True, default="")
    raw_value: Mapped[str] = mapped_column(String(64), default="")
    normalized_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, index=True
    )
    source_block_ids: Mapped[list] = mapped_column(JSON, default=list)
    neighboring_context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


def ensure_financial_fact_table(session) -> None:
    """Create financial_facts table if not exists (idempotent)."""
    from sqlalchemy import inspect

    inspector = inspect(session.bind)
    if "financial_facts" not in inspector.get_table_names():
        FinancialFact.__table__.create(session.bind, checkfirst=True)


__all__ = ["FinancialFact", "ensure_financial_fact_table"]
