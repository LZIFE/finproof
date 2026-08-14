"""通用 PDF 内容核验 API（Phase 24）。

POST /api/v1/generic-verify
- file: 待核验 PDF（必填）
- evidence_files: 证据 PDF/文本（可选，多文件）
- mode: auto | internal | cross_doc | external（默认 auto）
- user_materials: 用户提供的参考资料文本（可选）

批量与导出：
POST /api/v1/generic-verify/batch                    批量核验（多个 PDF）
GET  /api/v1/generic-verify/runs/{run_id}/export     导出 Markdown 报告

核验结果持久化到 generic_verification_runs：
GET /api/v1/generic-verify/runs              历史列表（分页）
GET /api/v1/generic-verify/runs/{run_id}     单次记录（含完整报告）
"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db import get_session
from app.services import document_service
from app.services.generic_verification.service import (
    export_markdown,
    get_verification_run,
    list_verification_runs,
    save_verification_run,
    verify_pdf,
    verify_pdf_batch,
)

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
    # 持久化核验结果（历史查询/回放）
    run_id = save_verification_run(
        session, doc.id, file.filename or "upload", mode, result,
    )
    result["run_id"] = run_id
    return result


@router.post("/batch")
def generic_verify_batch(
    files: list[UploadFile] = File(...),
    mode: str = Form("auto"),
    user_materials: list[str] = Form(default_factory=list),
    session: Session = Depends(get_session),
) -> dict:
    if mode not in VALID_MODES:
        raise AppError(
            f"非法的核验方式: {mode}（可选: {sorted(VALID_MODES)}）",
            status_code=422, code="INVALID_MODE",
        )
    if not files:
        raise AppError("批量核验至少需要一个 PDF 文件", status_code=422, code="EMPTY_BATCH")
    payload = [(f.filename or f"file{i}", f.file.read()) for i, f in enumerate(files)]
    result = verify_pdf_batch(
        None, payload, evidence_files=None, mode=mode, user_materials=user_materials,
    )
    return result


@router.get("/runs")
def verification_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict:
    total, runs = list_verification_runs(session, page=page, page_size=page_size)
    return {"total": total, "page": page, "page_size": page_size, "runs": runs}


@router.get("/runs/{run_id}")
def verification_run_detail(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = get_verification_run(session, run_id)
    if run is None:
        raise AppError(f"核验记录不存在: {run_id}", status_code=404, code="RUN_NOT_FOUND")
    return run


@router.get("/runs/{run_id}/export", response_class=PlainTextResponse)
def verification_run_export(run_id: int, session: Session = Depends(get_session)) -> str:
    """导出核验记录为 Markdown 报告。"""
    run = get_verification_run(session, run_id)
    if run is None:
        raise AppError(f"核验记录不存在: {run_id}", status_code=404, code="RUN_NOT_FOUND")
    return export_markdown(run.get("result") or {})
