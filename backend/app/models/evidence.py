"""证据检索数据模型（Phase 4A Oracle 模式）。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class EvidenceRetrievalRun(Base):
    """一次证据检索任务。"""

    __tablename__ = "evidence_retrieval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset: Mapped[str] = mapped_column(String(40), default="demo")  # demo | holdout
    input_mode: Mapped[str] = mapped_column(String(40))  # ORACLE_GOLD | SYSTEM_EXTRACTED
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    retrieval_version: Mapped[str] = mapped_column(String(20), default="v1")
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    candidates: Mapped[list["EvidenceCandidate"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvidenceCandidate(Base):
    """单条主张的 Top-K 证据候选。"""

    __tablename__ = "evidence_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    retrieval_run_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_retrieval_runs.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer)
    block_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank: Mapped[int] = mapped_column(Integer)
    final_score: Mapped[float] = mapped_column(Float)
    metric_score: Mapped[float] = mapped_column(Float, default=0.0)
    value_score: Mapped[float] = mapped_column(Float, default=0.0)
    period_score: Mapped[float] = mapped_column(Float, default=0.0)
    entity_score: Mapped[float] = mapped_column(Float, default=0.0)
    text_score: Mapped[float] = mapped_column(Float, default=0.0)
    matched_terms: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组
    retrieval_method: Mapped[str] = mapped_column(String(40), default="structured")
    # Phase 4A.6：证据类型分级与多证据排序
    evidence_type: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    evidence_quality_score: Mapped[float] = mapped_column(Float, default=0.3)
    evidence_rank_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 来源等级：OFFICIAL_DISCLOSURE / REGULATORY_DATA / THIRD_PARTY_REPORT /
    #          MEDIA_REPORT / CHANNEL_CHECK / FORECAST / NO_SOURCE
    source_level: Mapped[str] = mapped_column(String(40), default="NO_SOURCE")
    source_level_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["EvidenceRetrievalRun"] = relationship(back_populates="candidates")


class EvidenceRetrievalConfig(Base):
    """检索权重配置（可配置/可解释/持久化）。"""

    __tablename__ = "evidence_retrieval_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(20), unique=True, default="v1")
    weights_json: Mapped[str] = mapped_column(Text)  # {"metric":0.30,...}
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
