"""通用 PDF 核验编排入口（Phase 24）。

verify_pdf(session, pdf_bytes, filename, ...)：
解析（含 OCR 兜底）→ 主张拆解 → 自动路由 → 逐引擎核验 → 五类判定 + error_report 汇总。
session 为 None 时走纯内存路径（不落库），供测试与无 DB 场景使用。
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.generic_verification.claim_extraction import GenericClaimExtractor
from app.services.generic_verification.ocr import parse_with_ocr
from app.services.generic_verification.routing import (
    ROUTE_CROSS_DOC,
    ROUTE_EXTERNAL,
    ROUTE_INTERNAL,
    route_claim,
)
from app.services.generic_verification.schemas import ErrorItem
from app.services.generic_verification.verifiers.cross_document import verify_claim_cross_document
from app.services.generic_verification.verifiers.external_knowledge import verify_claim_external
from app.services.generic_verification.verifiers.internal_consistency import verify_claim_internal
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)

logger = logging.getLogger(__name__)

ERROR_REPORT_VERDICTS = frozenset({STATUS_REFUTED, STATUS_PARTIALLY_SUPPORTED})
_PREFER_VERDICTS = (STATUS_REFUTED, STATUS_SUPPORTED, STATUS_PARTIALLY_SUPPORTED)


def _parsed_to_blocks(parsed) -> list[dict]:
    """把解析结果转成块列表；index 为全局序号（与主张拆解的 block_index 对齐）。

    注意：不能直接用每页内的 b.block_index（每页从 0 重新计数），
    否则「跳过主张自身源块」等按 index 比较的逻辑会失效。
    """
    blocks: list[dict] = []
    for page in parsed.pages:
        for b in page.blocks:
            blocks.append({
                "index": len(blocks),
                "text": b.text or "",
                "page_number": page.page_number,
                "block_type": b.block_type,
            })
    return blocks


def _load_evidence_blocks(session, evidence_files: list[tuple[str, bytes]]) -> list[dict]:
    """证据文件解析为块列表（纯内存路径直接解析；DB 路径由 API 层注册后传入 bytes）。"""
    out: list[dict] = []
    for name, data in evidence_files:
        try:
            parsed = parse_with_ocr(data)
        except AppError:
            logger.warning("evidence file parse failed: %s", name)
            continue
        for b in _parsed_to_blocks(parsed):
            b["document_id"] = None
            out.append(b)
    return out


def _verify_one(claim, routes: list[str], doc_blocks: list[dict], evidence_blocks: list[dict],
                user_materials: list[str] | None) -> dict:
    """按路由顺序核验单条主张；任一 REFUTED 即整体 REFUTED。

    - internal 引擎用待核验文档自身的块（doc_blocks）
    - cross_doc 引擎用证据文档的块（evidence_blocks）
    """
    if not routes:
        return {
            "claim_id": claim.claim_id, "verdict": "NOT_VERIFIABLE", "confidence": 0.0,
            "mode_used": [], "evidence": [], "reason": "观点/预测类主张不强行核验", "error_type": None,
        }
    outcomes = []
    for route in routes:
        if route == ROUTE_INTERNAL:
            outcomes.append(verify_claim_internal(claim, doc_blocks))
        elif route == ROUTE_CROSS_DOC:
            outcomes.append(verify_claim_cross_document(claim, evidence_blocks))
        elif route == ROUTE_EXTERNAL:
            cfg = get_settings()
            outcomes.append(verify_claim_external(
                claim, user_materials=user_materials, enable_web_search=cfg.generic_web_search,
            ))
    refuted = [o for o in outcomes if o.verdict == STATUS_REFUTED]
    if refuted:
        return refuted[0].to_dict()
    for o in outcomes:
        if o.verdict in _PREFER_VERDICTS:
            return o.to_dict()
    return (outcomes[0] if outcomes else _unable(claim)).to_dict()


def _unable(claim):
    from app.services.generic_verification.schemas import VerificationOutcome

    return VerificationOutcome(
        claim_id=claim.claim_id, verdict=STATUS_UNABLE, confidence=0.4,
        mode_used=[], evidence=[], reason="无法判定", error_type=None,
    )


def _has_internal_basis(claim, blocks: list[dict]) -> bool:
    """同一实体/语境的数字是否在文档多处出现（内部自洽核验的依据）。

    对 claim 的每个数字语境，统计其在文档块中命中的数量 ≥ 2 → True。
    性能：复用块预计算缓存（_ensure_block_cache），避免 5000+ 主张 ×
    5000+ 块逐对做 re.sub 子序列匹配（曾耗时 60s）。
    """
    if not claim.numbers:
        return False
    from app.services.generic_verification.verifiers.internal_consistency import (
        _ensure_block_cache,
        _norm_text,
        _ctx_matches_norm,
    )

    _ensure_block_cache(blocks)
    for num in claim.numbers:
        ctx = _norm_text(num.get("context") or "")
        hits = 0
        for b in blocks:
            if _ctx_matches_norm(ctx, b["_norm"], b["_charset"]):
                hits += 1
                if hits >= 2:
                    return True
    return False


def save_verification_run(session, document_id: int | None, filename: str,
                          mode: str, result: dict) -> int:
    """持久化一次通用核验结果，返回 run_id。

    result 为 verify_pdf 的返回结构（含 verdicts/claims/error_report）。
    """
    import json

    from app.models.generic_verification import GenericVerificationRun

    run = GenericVerificationRun(
        document_id=document_id,
        filename=filename,
        mode=mode,
        total_claims=result.get("total_claims", 0),
        is_mock=bool(result.get("is_mock")),
        result_json=json.dumps(result, ensure_ascii=False),
        status="COMPLETED",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.id


def list_verification_runs(session, page: int = 1, page_size: int = 20) -> tuple[int, list[dict]]:
    """分页列出通用核验历史（不含完整 result_json，避免响应过大）。"""
    from sqlalchemy import func

    from app.models.generic_verification import GenericVerificationRun

    total = session.query(func.count(GenericVerificationRun.id)).scalar() or 0
    rows = (
        session.query(GenericVerificationRun)
        .order_by(GenericVerificationRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, [
        {
            "id": r.id,
            "document_id": r.document_id,
            "filename": r.filename,
            "mode": r.mode,
            "total_claims": r.total_claims,
            "is_mock": r.is_mock,
            "status": r.status,
            "error": r.error,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def get_verification_run(session, run_id: int) -> dict | None:
    """查询一次核验记录（含完整 result_json 解析结果）。"""
    import json

    from app.models.generic_verification import GenericVerificationRun

    run = session.get(GenericVerificationRun, run_id)
    if run is None:
        return None
    try:
        result = json.loads(run.result_json)
    except (TypeError, ValueError):
        result = {}
    return {
        "id": run.id,
        "document_id": run.document_id,
        "filename": run.filename,
        "mode": run.mode,
        "total_claims": run.total_claims,
        "is_mock": run.is_mock,
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "result": result,
    }


def verify_pdf(session, pdf_bytes: bytes, filename: str,
               evidence_files: list[tuple[str, bytes]] | None = None,
               mode: str = "auto",
               user_materials: list[str] | None = None) -> dict:
    """执行一次完整通用 PDF 核验，返回设计文档 §6.1 的结构。"""
    cfg = get_settings()

    # 1. 解析（含扫描页 OCR 兜底）
    try:
        parsed = parse_with_ocr(pdf_bytes)
    except AppError:
        raise
    blocks = _parsed_to_blocks(parsed)

    # 2. 证据块
    evidence_blocks = _load_evidence_blocks(session, evidence_files or [])

    # 3. 主张拆解
    extractor = GenericClaimExtractor(settings=cfg)
    result = extractor.extract(blocks, cfg.generic_extraction_prompt_version)

    # 4. 逐条核验
    claim_rows: list[dict] = []
    error_items: list[ErrorItem] = []
    for claim in result.claims:
        force = None if mode == "auto" else mode
        routes = route_claim(
            claim, has_evidence=bool(evidence_blocks), force_mode=force,
            has_internal_basis=_has_internal_basis(claim, blocks),
        )
        outcome = _verify_one(claim, routes, blocks, evidence_blocks, user_materials)
        claim_rows.append({
            "claim_id": claim.claim_id,
            "source_text": claim.source_text,
            "page_number": claim.page_number,
            "claim_kind": claim.claim_kind,
            **outcome,
        })
        if outcome["verdict"] in ERROR_REPORT_VERDICTS:
            error_items.append(ErrorItem(
                page_number=claim.page_number,
                source_text=claim.source_text,
                verdict=outcome["verdict"],
                error_type=outcome["error_type"] or "UNKNOWN",
                detail=outcome["reason"],
            ))

    # 5. 汇总
    verdicts = {STATUS_SUPPORTED: 0, STATUS_REFUTED: 0, STATUS_PARTIALLY_SUPPORTED: 0,
                STATUS_INSUFFICIENT: 0, STATUS_UNABLE: 0, "NOT_VERIFIABLE": 0}
    for r in claim_rows:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1

    return {
        "document_id": None,  # 纯内存路径无 DB 文档；API 层可回填
        "total_claims": len(claim_rows),
        "verdicts": verdicts,
        "claims": claim_rows,
        "error_report": [e.to_dict() for e in sorted(error_items, key=lambda e: e.page_number)],
        "is_mock": result.is_mock,
    }


def verify_pdf_batch(session, files: list[tuple[str, bytes]],
                     evidence_files: list[tuple[str, bytes]] | None = None,
                     mode: str = "auto",
                     user_materials: list[str] | None = None) -> dict:
    """批量核验多个 PDF，逐文件返回结果；单文件失败不影响其余文件。"""
    items: list[dict] = []
    for filename, data in files:
        try:
            result = verify_pdf(
                session, data, filename,
                evidence_files=evidence_files, mode=mode, user_materials=user_materials,
            )
            result["filename"] = filename
            result["status"] = "COMPLETED"
        except AppError as exc:
            result = {
                "filename": filename,
                "status": "FAILED",
                "error": {"code": exc.code, "message": str(exc)},
                "total_claims": 0,
                "verdicts": {},
                "claims": [],
                "error_report": [],
                "is_mock": False,
            }
        items.append(result)
    return {"total_files": len(files), "items": items}


def export_markdown(result: dict) -> str:
    """把一次核验结果渲染为 Markdown 报告（错误清单 + 判定统计）。"""
    lines: list[str] = []
    lines.append("# 通用 PDF 内容核验报告")
    lines.append("")
    lines.append(f"- 待核验文档: {result.get('filename') or result.get('document_id') or '-'}")
    lines.append(f"- 主张总数: {result.get('total_claims', 0)}")
    lines.append(f"- 核验方式: Mock 模式" if result.get("is_mock") else "- 核验方式: 标准模式")
    lines.append("")
    verdicts = result.get("verdicts") or {}
    lines.append("## 判定统计")
    lines.append("")
    lines.append("| 判定 | 数量 |")
    lines.append("|---|---|")
    for k in ("SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE",
              "UNABLE_TO_DETERMINE", "NOT_VERIFIABLE"):
        lines.append(f"| {k} | {verdicts.get(k, 0)} |")
    lines.append("")

    errs = result.get("error_report") or []
    lines.append(f"## 错误清单（{len(errs)} 项）")
    lines.append("")
    if not errs:
        lines.append("未发现 REFUTED / PARTIALLY_SUPPORTED 条目。")
    else:
        lines.append("| 页码 | 错误类型 | 原文 | 详情 |")
        lines.append("|---|---|---|---|")
        for e in errs:
            src = (e.get("source_text") or "").replace("|", "\\|").replace("\n", " ")[:60]
            detail = (e.get("detail") or "").replace("|", "\\|").replace("\n", " ")[:80]
            lines.append(f"| {e.get('page_number')} | {e.get('error_type')} | {src} | {detail} |")
    lines.append("")
    return "\n".join(lines)
