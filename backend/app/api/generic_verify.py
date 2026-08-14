"""通用 PDF 内容核验 API（Phase 24）。

POST /api/v1/generic-verify
- file: 待核验 PDF（必填）
- evidence_files: 证据 PDF/文本（可选，多文件）
- mode: auto | internal | cross_doc | external（默认 auto）
- user_materials: 用户提供的参考资料文本（可选）
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db import get_session
from app.services import document_service
from app.services.generic_verification.service import verify_pdf

router = APIRouter(prefix="/api/v1/generic-verify", tags=["generic-verify"])

VALID_MODES = {"auto", "internal", "cross_doc", "external"}


@router.post("")
def generic_verify(
    file: UploadFile = File(...),
    evidence_files: list[UploadFile] = File(default_factory=list),
    mode: str = Form("auto"),
    user_materials: list[str] = Form(default_factory=list),
    session: Session = Depends(get_session),
) -> dict:
    if mode not in VALID_MODES:
        raise AppError(
            f"非法的核验方式: {mode}（可选: {sorted(VALID_MODES)}）",
            status_code=422, code="INVALID_MODE",
        )
    data = file.file.read()
    # 注册待核验文档（DB 路径，用于回填 document_id 与留痕）
    doc, _ = document_service.register_document(
        session, filename=file.filename or "upload", data=data,
        document_role="REPORT_TO_VERIFY",
    )
    if doc.parse_status != "COMPLETED":
        raise AppError(
            f"待核验文档解析失败: {doc.parse_error or doc.parse_status}",
            status_code=422, code="PARSE_FAILED",
        )
    evidence = []
    for ef in evidence_files:
        edata = ef.file.read()
        try:
            edoc, _ = document_service.register_document(
                session, filename=ef.filename or "evidence", data=edata,
                document_role="SOURCE_DOCUMENT",
            )
        except AppError:
            continue
        if edoc.parse_status == "COMPLETED":
            evidence.append((ef.filename or "evidence", edata))

    result = verify_pdf(
        session, data, file.filename or "upload",
        evidence_files=evidence or None, mode=mode, user_materials=user_materials,
    )
    result["document_id"] = doc.id
    return result
