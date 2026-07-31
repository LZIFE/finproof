"""文档接入 API（Phase 2）。

统一错误结构：{"error": {"code": "...", "message": "...", "details": {...}}}
页面编号：一律使用 PDF 物理页码 page_number（1 基）。
"""

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db import get_session
from app.schemas.document import (
    BlockOut,
    DocumentListResponse,
    DocumentOut,
    PageDetailOut,
    PageListResponse,
    PageListItem,
    UploadResponse,
)
from app.services import document_service

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

DOCUMENT_ROLES = {"SOURCE_DOCUMENT", "REPORT_TO_VERIFY", "REFERENCE_REPORT"}
PARSE_STATUSES = {"PENDING", "PARSING", "COMPLETED", "FAILED", "UNSUPPORTED"}
TEXT_PREVIEW_LEN = 200


@router.post("")
def upload_document(
    file: UploadFile = File(...),
    document_role: str = Form("SOURCE_DOCUMENT"),
    company_name: str | None = Form(None),
    stock_code: str | None = Form(None),
    report_period: str | None = Form(None),
    publication_date: str | None = Form(None),
    response: Response = None,
    session: Session = Depends(get_session),
) -> UploadResponse:
    """上传文档（PDF / Markdown）。重复文件返回既有文档与 duplicate=true。"""
    if document_role not in DOCUMENT_ROLES:
        raise AppError(
            f"非法的文档角色: {document_role}（可选: {sorted(DOCUMENT_ROLES)}）",
            status_code=422,
            code="INVALID_DOCUMENT_ROLE",
        )
    data = file.file.read()
    doc, duplicate = document_service.register_document(
        session,
        filename=file.filename or "upload",
        data=data,
        document_role=document_role,
        company_name=company_name,
        stock_code=stock_code,
        report_period=report_period,
        publication_date=publication_date,
    )
    response.status_code = 200 if duplicate else 201
    return UploadResponse(document=DocumentOut.model_validate(doc), duplicate=duplicate)


@router.get("")
def list_documents(
    role: str | None = Query(None, description="按文档角色过滤"),
    status: str | None = Query(None, description="按解析状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> DocumentListResponse:
    if role is not None and role not in DOCUMENT_ROLES:
        raise AppError(f"非法的文档角色: {role}", status_code=422, code="INVALID_DOCUMENT_ROLE")
    if status is not None and status not in PARSE_STATUSES:
        raise AppError(f"非法的解析状态: {status}", status_code=422, code="INVALID_PARSE_STATUS")
    total, docs = document_service.list_documents(
        session, role=role, status=status, page=page, page_size=page_size
    )
    return DocumentListResponse(
        total=total,
        page=page,
        page_size=page_size,
        documents=[DocumentOut.model_validate(d) for d in docs],
    )


@router.get("/{document_id}")
def get_document(
    document_id: int, session: Session = Depends(get_session)
) -> DocumentOut:
    doc = document_service.get_document_or_404(session, document_id)
    return DocumentOut.model_validate(doc)


@router.get("/{document_id}/pages")
def list_pages(
    document_id: int, session: Session = Depends(get_session)
) -> PageListResponse:
    doc = document_service.get_document_or_404(session, document_id)
    pages = document_service.get_document_pages(session, document_id)
    return PageListResponse(
        document_id=document_id,
        total_pages=doc.page_count,
        pages=[
            PageListItem(
                page_number=p.page_number,
                character_count=p.character_count,
                is_empty=p.character_count == 0,
                text_preview=p.text[:TEXT_PREVIEW_LEN],
            )
            for p in pages
        ],
    )


@router.get("/{document_id}/pages/{page_number}")
def get_page_detail(
    document_id: int, page_number: int, session: Session = Depends(get_session)
) -> PageDetailOut:
    page = document_service.get_document_page(session, document_id, page_number)
    blocks = document_service.get_page_blocks(session, page.id)
    return PageDetailOut(
        page_index=page.page_index,
        page_number=page.page_number,
        printed_page_label=page.printed_page_label,
        character_count=page.character_count,
        text=page.text,
        blocks=[BlockOut.model_validate(b) for b in blocks],
    )
