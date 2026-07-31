"""文档服务层：上传校验、哈希去重、存储、解析、入库，供 API 与导入脚本共用。

流程（register_document）：
1. 安全校验（扩展名/空/大小/类型内容）→ 计算 SHA-256
2. 去重：已存在 COMPLETED 文档则直接返回（duplicate=True）；已存在 FAILED/UNSUPPORTED
   文档则删除旧记录与存储，重新解析
3. 元数据行先提交（保证可预期失败后仍保留 FAILED/UNSUPPORTED 记录）
4. 保存原始文件 → 解析 → 写 pages/blocks（同一事务，失败整体回滚）
5. 解析成功：COMPLETED；可预期失败（加密/无文本）：UNSUPPORTED；其他异常：FAILED，
   并记录 parse_error；失败时不残留任何页面记录
"""

import logging
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models import Document, DocumentBlock, DocumentPage
from app.services import storage
from app.services.parser.markdown_parser import parse_markdown
from app.services.parser.pdf_parser import parse_pdf
from app.services.security import compute_sha256, sanitize_filename, validate_upload

logger = logging.getLogger(__name__)

# 可预期的"不支持"类错误码（映射到 UNSUPPORTED 状态）
UNSUPPORTED_CODES = {"UNSUPPORTED_DOCUMENT", "ENCRYPTED_PDF", "NO_EXTRACTABLE_TEXT"}


def _max_upload_bytes() -> int:
    return int(get_settings().max_upload_size_mb) * 1024 * 1024


def _delete_existing(session: Session, doc: Document) -> None:
    """删除既有文档记录与其存储目录（用于重新解析失败的旧文档）。"""
    doc_id = doc.id
    session.delete(doc)
    session.commit()
    storage.remove_document_dir(doc_id)


def register_document(
    session: Session,
    *,
    filename: str,
    data: bytes,
    document_role: str = "SOURCE_DOCUMENT",
    company_name: str | None = None,
    stock_code: str | None = None,
    report_period: str | None = None,
    publication_date: str | None = None,
) -> tuple[Document, bool]:
    """注册并解析一个文档。返回 (Document, duplicate)。

    校验层（validate_upload）失败时直接抛出 AppError，不创建任何记录；
    解析层失败时保留一条 FAILED/UNSUPPORTED 元数据记录（不残留页面）。
    """
    max_bytes = _max_upload_bytes()
    document_type = validate_upload(filename, data, max_bytes)

    sha256 = compute_sha256(data)
    existing = session.query(Document).filter(Document.sha256 == sha256).first()
    if existing is not None and existing.parse_status == "COMPLETED":
        logger.info("duplicate document sha256=%s doc_id=%s", sha256, existing.id)
        return existing, True
    if existing is not None:  # 历史失败/未支持记录：删除后重新解析
        _delete_existing(session, existing)

    safe_name = sanitize_filename(filename)
    ext = "pdf" if document_type == "pdf" else "md"
    doc = Document(
        original_filename=safe_name,
        stored_filename=f"original.{ext}",
        document_type=document_type,
        document_role=document_role,
        company_name=company_name,
        stock_code=stock_code,
        report_period=report_period,
        publication_date=publication_date,
        mime_type="application/pdf" if document_type == "pdf" else "text/markdown",
        file_size=len(data),
        sha256=sha256,
        page_count=0,
        parse_status="PENDING",
    )
    session.add(doc)
    # 元数据先行提交：解析失败回滚页面事务时，本行依然存在，可标记 FAILED/UNSUPPORTED
    session.commit()
    doc_id = doc.id

    try:
        storage.save_original(doc_id, data, ext)
        start = time.monotonic()
        if document_type == "pdf":
            parsed = parse_pdf(data)
        else:
            parsed = parse_markdown(data.decode("utf-8"))
        duration_ms = int((time.monotonic() - start) * 1000)

        for page in parsed.pages:
            page_row = DocumentPage(
                document_id=doc_id,
                page_index=page.page_index,
                page_number=page.page_number,
                printed_page_label=page.printed_page_label,
                text=page.text,
                character_count=page.character_count,
                text_sha256=page.text_sha256,
            )
            session.add(page_row)
            session.flush()  # 获得 page_row.id
            for block in page.blocks:
                session.add(
                    DocumentBlock(
                        document_id=doc_id,
                        page_id=page_row.id,
                        block_index=block.block_index,
                        block_type=block.block_type,
                        text=block.text,
                        x0=block.x0,
                        y0=block.y0,
                        x1=block.x1,
                        y1=block.y1,
                        reading_order=block.reading_order,
                        heading_level=block.heading_level,
                        start_line=block.start_line,
                        end_line=block.end_line,
                    )
                )

        doc.page_count = parsed.page_count
        doc.parse_status = "COMPLETED"
        doc.parse_error = None
        doc.parse_duration_ms = duration_ms
        doc.extraction_method = "pymupdf" if document_type == "pdf" else "markdown_parser"
        session.commit()

        _write_extraction_artifact(doc_id, parsed)
        _log_parse(doc, parsed, duration_ms, "COMPLETED", None)
        return doc, False
    except AppError as exc:
        # 可预期的不支持（加密/无文本）：UNSUPPORTED；INVALID_FILE（损坏）：FAILED
        status = "UNSUPPORTED" if exc.code in UNSUPPORTED_CODES else "FAILED"
        session.rollback()
        doc = session.get(Document, doc_id)
        doc.parse_status = status
        doc.parse_error = exc.message
        session.commit()
        _log_parse(doc, None, 0, status, exc.code)
        raise
    except Exception as exc:  # noqa: BLE001 —— 未知解析异常
        session.rollback()
        doc = session.get(Document, doc_id)
        doc.parse_status = "FAILED"
        doc.parse_error = f"{type(exc).__name__}: {exc}"
        session.commit()
        _log_parse(doc, None, 0, "FAILED", type(exc).__name__)
        raise AppError(
            f"文档解析失败: {doc.parse_error}", status_code=422, code="PARSE_FAILED"
        ) from exc


def _write_extraction_artifact(doc_id: int, parsed) -> None:
    """写入 extraction.json（页码与文本块坐标元数据，不含全文）。"""
    payload = {
        "document_type": parsed.document_type,
        "page_count": parsed.page_count,
        "total_characters": parsed.total_characters,
        "pages": [
            {
                "page_index": p.page_index,
                "page_number": p.page_number,
                "printed_page_label": p.printed_page_label,
                "character_count": p.character_count,
                "text_sha256": p.text_sha256,
                "blocks": [
                    {
                        "block_index": b.block_index,
                        "block_type": b.block_type,
                        "x0": b.x0,
                        "y0": b.y0,
                        "x1": b.x1,
                        "y1": b.y1,
                        "reading_order": b.reading_order,
                        "heading_level": b.heading_level,
                        "start_line": b.start_line,
                        "end_line": b.end_line,
                    }
                    for b in p.blocks
                ],
            }
            for p in parsed.pages
        ],
    }
    try:
        storage.write_extraction_json(doc_id, payload)
    except Exception:  # noqa: BLE001 —— 产物文件写入失败不影响主流程
        logger.warning("extraction.json 写入失败 document_id=%s", doc_id)


def _log_parse(doc: Document, parsed, duration_ms: int, status: str, error_type: str | None) -> None:
    """解析日志（不含文件内容）。"""
    logger.info(
        "parse document_id=%s filename=%s size=%s sha256=%s pages=%s chars=%s "
        "duration_ms=%s status=%s error_type=%s",
        doc.id,
        doc.original_filename,
        doc.file_size,
        doc.sha256,
        parsed.page_count if parsed else 0,
        parsed.total_characters if parsed else 0,
        duration_ms,
        status,
        error_type,
    )


# ---------- 查询 ----------

def get_document_or_404(session: Session, document_id: int) -> Document:
    doc = session.get(Document, document_id)
    if doc is None:
        raise AppError(f"文档不存在: {document_id}", status_code=404, code="DOCUMENT_NOT_FOUND")
    return doc


def list_documents(
    session: Session,
    role: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[Document]]:
    query = session.query(Document)
    if role:
        query = query.filter(Document.document_role == role)
    if status:
        query = query.filter(Document.parse_status == status)
    total = query.count()
    items = (
        query.order_by(Document.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def get_document_pages(session: Session, document_id: int) -> list[DocumentPage]:
    get_document_or_404(session, document_id)
    return (
        session.query(DocumentPage)
        .filter(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
        .all()
    )


def get_document_page(session: Session, document_id: int, page_number: int) -> DocumentPage:
    get_document_or_404(session, document_id)
    page_row = (
        session.query(DocumentPage)
        .filter(DocumentPage.document_id == document_id, DocumentPage.page_number == page_number)
        .first()
    )
    if page_row is None:
        raise AppError(
            f"文档 {document_id} 不存在第 {page_number} 页", status_code=404, code="PAGE_NOT_FOUND"
        )
    return page_row


def get_page_blocks(session: Session, page_id: int) -> list[DocumentBlock]:
    return (
        session.query(DocumentBlock)
        .filter(DocumentBlock.page_id == page_id)
        .order_by(DocumentBlock.reading_order)
        .all()
    )
