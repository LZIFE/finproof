"""Financial Knowledge Graph 数据模型（Phase 10）。

数据库表：
- kg_entities          图谱节点（公司/业务/产品/地区/竞争对手/指标/高管）
- kg_relationships     图谱边（OWNS/HAS_BUSINESS/COMPETES_WITH/LOCATED_IN/HAS_METRIC/SUPPORTED_BY）
- kg_facts             图谱事实（Evidence First：source/evidence/confidence/timestamp 必填）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KGEntityRow(Base):
    """图谱节点：金融实体。"""

    __tablename__ = "kg_entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # ENT-XXXXX
    entity_type: Mapped[str] = mapped_column(String(20), index=True)  # ENTITY_TYPES
    name: Mapped[str] = mapped_column(String(200))
    aliases_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON dict
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KGRelationshipRow(Base):
    """图谱边：实体间关系。"""

    __tablename__ = "kg_relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    relationship_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # REL-XXXXX
    source_entity_id: Mapped[str] = mapped_column(String(40), index=True)
    target_entity_id: Mapped[str] = mapped_column(String(40), index=True)
    relationship_type: Mapped[str] = mapped_column(String(30), index=True)  # RELATIONSHIP_TYPES
    fact_id: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 关联事实（Evidence First）
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KGFactsRow(Base):
    """图谱事实：可追溯的金融事实。

    Evidence First：source / evidence / confidence / timestamp 必填。
    """

    __tablename__ = "kg_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # FACT-XXXXX
    subject_entity_id: Mapped[str] = mapped_column(String(40), index=True)
    predicate: Mapped[str] = mapped_column(String(200))  # 谓词
    object_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # 客体值（JSON 序列化）
    unit: Mapped[str] = mapped_column(String(20), default="")
    period: Mapped[str] = mapped_column(String(40), default="")

    # Evidence First 字段
    source: Mapped[str] = mapped_column(String(40), default="")  # FINANCIAL_REPORT/ANNOUNCEMENT/NEWS/OFFICIAL_SITE/CLAIM/EVIDENCE
    source_label: Mapped[str] = mapped_column(String(200), default="")
    evidence: Mapped[str] = mapped_column(Text, default="")  # 原始证据文本/摘要
    timestamp: Mapped[str] = mapped_column(String(40), default="")  # ISO8601
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1

    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
