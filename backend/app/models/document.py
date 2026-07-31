"""文档接入层数据模型：documents / document_pages / document_blocks。

页码规范（Phase 2 统一约定，见 docs/finproof_execution_plan.md）：
- page_index：PDF 内部 0 基索引（PyMuPDF 下标），供程序调用
- page_number：PDF 阅读器物理页码，从 1 开始（金标准/API/前端默认体系）
- printed_page_label：财报正文印刷页码，无法可靠识别时为 null
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255))
    # pdf | markdown
    document_type: Mapped[str] = mapped_column(String(20))
    # SOURCE_DOCUMENT | REPORT_TO_VERIFY | REFERENCE_REPORT
    document_role: Mapped[str] = mapped_column(String(30), default="SOURCE_DOCUMENT")
    company_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    publication_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    # PENDING | PARSING | COMPLETED | FAILED | UNSUPPORTED
    parse_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pymupdf | markdown_parser
    extraction_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_document_page_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_index: Mapped[int] = mapped_column(Integer)  # 0 基
    page_number: Mapped[int] = mapped_column(Integer)  # 1 基物理页码
    printed_page_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    character_count: Mapped[int] = mapped_column(Integer, default=0)
    text_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped[Document] = relationship(back_populates="pages")
    blocks: Mapped[list["DocumentBlock"]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class DocumentBlock(Base):
    __tablename__ = "document_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_id: Mapped[int] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True
    )
    block_index: Mapped[int] = mapped_column(Integer)
    # text | image | heading | paragraph
    block_type: Mapped[str] = mapped_column(String(20), default="text")
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    x0: Mapped[float | None] = mapped_column(Float, nullable=True)
    y0: Mapped[float | None] = mapped_column(Float, nullable=True)
    x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    reading_order: Mapped[int] = mapped_column(Integer, default=0)
    # Markdown 定位：标题层级与行号范围（PDF 为 null）
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    page: Mapped[DocumentPage] = relationship(back_populates="blocks")
