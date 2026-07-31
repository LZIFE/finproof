"""Phase 3 主张提取数据模型：extraction_runs / claims。

可追溯性：每条主张可追溯到 文档(document_id) + 文本块(source_block_id) + 页码。
删除文档时：extraction_runs 与 claims 随文档级联删除；source_block_id 置空。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # PENDING | RUNNING | COMPLETED | FAILED
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    # mock | rules | llm
    mode: Mapped[str] = mapped_column(String(20), default="mock")
    provider: Mapped[str] = mapped_column(String(50), default="")
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_block_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_sentence_count: Mapped[int] = mapped_column(Integer, default=0)
    # Provider 输出的候选主张总数（Schema 校验前）
    candidate_claim_count: Mapped[int] = mapped_column(Integer, default=0)
    extracted_claim_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_valid_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_removed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 去重分析产物（kept/removed/reason/score 记录 JSON）
    dedup_analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    claims: Mapped[list["Claim"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "claim_uid", name="uq_run_claim_uid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_uid: Mapped[str] = mapped_column(String(64))
    extraction_run_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    source_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_blocks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_page_number: Mapped[int] = mapped_column(Integer, default=1)
    source_text: Mapped[str] = mapped_column(Text)
    # 主张组：同一父句拆分出的兄弟主张共享 claim_group_id（绝对值+增长率等），
    # 前端可按组折叠展示；数据库/评测/核验仍保留独立主张
    claim_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 父句上下文（子句归属）：拆分后的子主张保留父句信息用于评测与证据定位
    parent_block_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_sentence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    clause_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_claim: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(40))
    entity_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    metric: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metric_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reported_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_value_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value_operator: Mapped[str] = mapped_column(String(20), default="EQUAL")
    range_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    range_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    period: Mapped[str | None] = mapped_column(String(30), nullable=True)
    period_type: Mapped[str] = mapped_column(String(20), default="UNSPECIFIED")
    comparison_period: Mapped[str | None] = mapped_column(String(30), nullable=True)
    comparison_type: Mapped[str] = mapped_column(String(30), default="NONE")
    scope: Mapped[str | None] = mapped_column(String(30), nullable=True)
    business_segment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geography: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claim_nature: Mapped[str] = mapped_column(String(30), default="FACT")
    risk_level: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    risk_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_calculation: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_external_evidence: Mapped[bool] = mapped_column(Boolean, default=True)
    extraction_method: Mapped[str] = mapped_column(String(30), default="RULE_BASED")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    # PENDING | APPROVED | REJECTED | EDITED
    review_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # EDITED 时保存修改后的字段 JSON；原始系统输出保留在原列不覆盖
    review_changes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    run: Mapped[ExtractionRun] = relationship(back_populates="claims")
