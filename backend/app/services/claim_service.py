"""主张提取服务层（Phase 3）：提取运行编排、Schema 校验、去重、入库、人工审核。

流程（run_claim_extraction）：
1. 校验文档存在且 document_role == REPORT_TO_VERIFY（默认只处理待核验报告）
2. 非 force 且已有运行 → 返回既有运行（不重复提取）
3. 创建 ExtractionRun（PENDING → RUNNING）→ 读取文本块 → 按模式选择 Provider
4. 每条候选经 ClaimCreate Schema 校验（无效计为 schema 失败）→ 去重 → 入库
5. 运行状态 COMPLETED/FAILED，记录各计数与耗时；失败回滚主张但保留运行记录
"""

import json
import logging
import re
import time

from sqlalchemy.orm import Session

from app.core.enums import ExtractionMode, ExtractionRunStatus, ReviewStatus
from app.core.exceptions import AppError
from app.models import Claim, Document, DocumentBlock, DocumentPage, ExtractionRun
from app.schemas.claim import ClaimCreate
from app.services.claims.dedup import deduplicate
from app.services.claims.providers import (
    ClaimExtractionResult,
    DocumentContext,
    get_claim_provider,
)
from app.services.document_service import get_document_or_404

logger = logging.getLogger(__name__)


def _report_year_of(doc: Document) -> int | None:
    if doc.report_period:
        m = re.match(r"(20\d{2})", doc.report_period)
        if m:
            return int(m.group(1))
    return None


def _get_document_blocks(session: Session, document_id: int) -> list[DocumentBlock]:
    """按页码/阅读顺序返回文档全部文本块，并附带 page_number。"""
    pages = (
        session.query(DocumentPage)
        .filter(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
        .all()
    )
    blocks: list[DocumentBlock] = []
    for page in pages:
        page_blocks = (
            session.query(DocumentBlock)
            .filter(DocumentBlock.page_id == page.id)
            .order_by(DocumentBlock.reading_order)
            .all()
        )
        for b in page_blocks:
            b.page_number = page.page_number  # type: ignore[attr-defined]
        blocks.extend(page_blocks)
    return blocks


def _mode_label(mode: str) -> str:
    return ExtractionMode(mode).value if mode in {m.value for m in ExtractionMode} else "mock"


def _finalize_run(
    session: Session,
    run: ExtractionRun,
    document_id: int,
    result: ClaimExtractionResult,
    mode: str,
    duration_ms: int = 0,
) -> tuple[ExtractionRun, bool]:
    """schema 校验 → 去重 → 入库 → 收尾（mock/rules/llm/hybrid/ai 各模式共用）。"""
    run_id = run.id
    schema_valid = 0
    duplicates = 0
    saved: list[Claim] = []
    dedup_targets: list = []

    for i, raw in enumerate(result.claim_dicts, start=1):
        try:
            claim = ClaimCreate(
                claim_uid=f"CLM-RUN{run_id}-{i:03d}",
                extraction_run_id=run_id,
                document_id=document_id,
                **raw,
            )
        except Exception:  # noqa: BLE001 —— Schema 校验失败计为无效，跳过
            continue
        schema_valid += 1
        dedup_targets.append(claim)

    dedup_result = deduplicate(dedup_targets)
    duplicates = dedup_result.removed_count

    # 去重分析产物（kept/removed/reason/score）
    dedup_records = [
        {
            "kept_claim": dedup_targets[r.kept_index].source_text,
            "removed_claim": dedup_targets[r.removed_index].source_text,
            "dedup_reason": r.dedup_reason,
            "dedup_score": r.dedup_score,
        }
        for r in dedup_result.records
    ]
    run.dedup_analysis_json = json.dumps(dedup_records, ensure_ascii=False)

    for claim in dedup_result.unique:
        row = Claim(
            claim_uid=claim.claim_uid,
            extraction_run_id=claim.extraction_run_id,
            document_id=claim.document_id,
            source_block_id=claim.source_block_id,
            source_page_number=claim.source_page_number,
            source_text=claim.source_text,
            claim_group_id=claim.claim_group_id,
            parent_block_id=claim.parent_block_id,
            parent_sentence_text=claim.parent_sentence_text,
            clause_index=claim.clause_index,
            source_span_start=claim.source_span_start,
            source_span_end=claim.source_span_end,
            normalized_claim=claim.normalized_claim,
            claim_type=claim.claim_type.value,
            entity_name=claim.entity_name,
            stock_code=claim.stock_code,
            metric=claim.metric,
            metric_code=claim.metric_code,
            reported_value=claim.reported_value,
            reported_value_text=claim.reported_value_text,
            value_operator=claim.value_operator.value,
            range_min=claim.range_min,
            range_max=claim.range_max,
            unit=claim.unit,
            currency=claim.currency,
            period=claim.period,
            period_type=claim.period_type.value,
            comparison_period=claim.comparison_period,
            comparison_type=claim.comparison_type.value,
            scope=claim.scope,
            business_segment=claim.business_segment,
            geography=claim.geography,
            claim_nature=claim.claim_nature.value,
            risk_level=claim.risk_level.value,
            risk_reason=claim.risk_reason,
            requires_calculation=claim.requires_calculation,
            requires_external_evidence=claim.requires_external_evidence,
            extraction_method=claim.extraction_method,
            confidence=claim.confidence,
            review_status=claim.review_status.value,
        )
        session.add(row)
        saved.append(row)

    run.status = "COMPLETED"
    run.provider = result.provider
    run.model_name = result.model_name
    run.prompt_version = result.prompt_version
    run.input_block_count = result.input_block_count
    run.candidate_sentence_count = result.candidate_sentence_count
    run.candidate_claim_count = len(result.claim_dicts)
    run.extracted_claim_count = len(saved)
    run.schema_valid_count = schema_valid
    run.duplicate_removed_count = duplicates
    run.duration_ms = duration_ms
    run.completed_at = _now()
    session.commit()

    logger.info(
        "claim extraction run_id=%s doc_id=%s mode=%s provider=%s status=COMPLETED "
        "candidates=%s schema_valid=%s duplicates=%s saved=%s duration_ms=%s",
        run_id, document_id, mode, result.provider,
        len(result.claim_dicts), schema_valid, duplicates, len(saved), duration_ms,
    )
    return run, True


def run_claim_extraction(
    session: Session,
    document_id: int,
    mode: str = "mock",
    force: bool = False,
) -> tuple[ExtractionRun, bool]:
    """对待核验报告执行一次主张提取。返回 (run, created)。"""
    doc = get_document_or_404(session, document_id)
    if doc.document_role != "REPORT_TO_VERIFY":
        raise AppError(
            f"仅支持对 REPORT_TO_VERIFY 文档提取主张（当前角色: {doc.document_role}）",
            status_code=422,
            code="INVALID_DOCUMENT_ROLE",
        )

    mode = _mode_label(mode)
    existing = (
        session.query(ExtractionRun)
        .filter(ExtractionRun.document_id == document_id)
        .order_by(ExtractionRun.id.desc())
        .first()
    )
    if existing and not force and existing.status in ("RUNNING", "COMPLETED"):
        return existing, False

    run = ExtractionRun(document_id=document_id, status="RUNNING", mode=mode)
    session.add(run)
    session.commit()  # 元数据先行提交，失败时保留 FAILED 记录
    run_id = run.id

    try:
        blocks = _get_document_blocks(session, document_id)
        from app.core.config import get_settings

        ctx = DocumentContext(
            document_id=document_id,
            company_name=doc.company_name,
            stock_code=doc.stock_code,
            report_year=_report_year_of(doc),
            prompt_version=get_settings().claim_extraction_prompt_version,
        )
        provider = get_claim_provider(mode)
        # 金标准泄漏防护：提取链路不得读取 gold/holdout/artifacts（违规立即失败）
        from app.services.claims.guard import assert_extraction_isolated

        assert_extraction_isolated()
        start = time.monotonic()
        result: ClaimExtractionResult = provider.extract_claims(ctx, blocks)
        duration_ms = int((time.monotonic() - start) * 1000)

        return _finalize_run(session, run, document_id, result, mode, duration_ms=duration_ms)
    except AppError as exc:
        session.rollback()
        run = session.get(ExtractionRun, run_id)
        run.status = "FAILED"
        run.error_code = exc.code
        run.error_message = exc.message
        run.completed_at = _now()
        session.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        run = session.get(ExtractionRun, run_id)
        run.status = "FAILED"
        run.error_code = type(exc).__name__
        run.error_message = str(exc)
        run.completed_at = _now()
        session.commit()
        raise AppError(
            f"主张提取失败: {exc}", status_code=422, code="EXTRACTION_FAILED"
        ) from exc


def run_ai_extraction(
    session: Session,
    document_id: int,
    claim_dicts: list[dict],
    model_name: str,
    prompt_version: str = "v2",
    force: bool = False,
) -> tuple[ExtractionRun, bool]:
    """AI 辅助模式：由外部模型（当前 AI agent）生成的主张直接入库为一次真实运行。

    - mode="ai"、provider="assisted"、model_name 记录实际模型（真实模型输出，非 Mock）；
    - 与 mock/rules/llm/hybrid 共用 schema 校验 / 去重 / 风险分级 / 入库流程；
    - 不调用外部 API；输入为模型生成的 claim dicts。
    """
    doc = get_document_or_404(session, document_id)
    if doc.document_role != "REPORT_TO_VERIFY":
        raise AppError(
            f"仅支持对 REPORT_TO_VERIFY 文档提取主张（当前角色: {doc.document_role}）",
            status_code=422,
            code="INVALID_DOCUMENT_ROLE",
        )

    existing = (
        session.query(ExtractionRun)
        .filter(ExtractionRun.document_id == document_id)
        .order_by(ExtractionRun.id.desc())
        .first()
    )
    if existing and not force and existing.status in ("RUNNING", "COMPLETED"):
        return existing, False

    run = ExtractionRun(document_id=document_id, status="RUNNING", mode="ai")
    session.add(run)
    session.commit()  # 元数据先行提交，失败时保留 FAILED 记录
    run_id = run.id

    try:
        result = ClaimExtractionResult(
            claim_dicts=claim_dicts,
            provider="assisted",
            model_name=model_name,
            prompt_version=prompt_version,
            is_mock=False,
            candidate_sentence_count=len(claim_dicts),
            input_block_count=0,
        )
        return _finalize_run(session, run, document_id, result, "ai")
    except AppError as exc:
        session.rollback()
        run = session.get(ExtractionRun, run_id)
        run.status = "FAILED"
        run.error_code = exc.code
        run.error_message = exc.message
        run.completed_at = _now()
        session.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        run = session.get(ExtractionRun, run_id)
        run.status = "FAILED"
        run.error_code = type(exc).__name__
        run.error_message = str(exc)
        run.completed_at = _now()
        session.commit()
        raise AppError(
            f"AI 主张导入失败: {exc}", status_code=422, code="AI_IMPORT_FAILED"
        ) from exc


def _now():
    from datetime import datetime

    return datetime.utcnow()


# ---------- 查询与审核 ----------

def get_run_or_404(session: Session, run_id: int) -> ExtractionRun:
    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise AppError(f"提取运行不存在: {run_id}", status_code=404, code="RUN_NOT_FOUND")
    return run


def get_claim_or_404(session: Session, claim_id: int) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise AppError(f"主张不存在: {claim_id}", status_code=404, code="CLAIM_NOT_FOUND")
    return claim


def list_claims(
    session: Session,
    document_id: int,
    claim_type: str | None = None,
    risk_level: str | None = None,
    claim_nature: str | None = None,
    review_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str = "id_desc",
) -> tuple[int, list[Claim]]:
    get_document_or_404(session, document_id)
    query = session.query(Claim).filter(Claim.document_id == document_id)
    if claim_type:
        query = query.filter(Claim.claim_type == claim_type)
    if risk_level:
        query = query.filter(Claim.risk_level == risk_level)
    if claim_nature:
        query = query.filter(Claim.claim_nature == claim_nature)
    if review_status:
        query = query.filter(Claim.review_status == review_status)
    if sort == "risk_desc":
        order = [
            Claim.risk_level == "CRITICAL", Claim.risk_level == "HIGH",
            Claim.risk_level == "MEDIUM", Claim.risk_level == "LOW",
        ]
        query = query.order_by(*[c.desc() for c in order], Claim.id)
    elif sort == "value_desc":
        query = query.order_by(Claim.reported_value.desc().nullslast(), Claim.id)
    else:
        query = query.order_by(Claim.id.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return total, items


def review_claim(
    session: Session,
    claim_id: int,
    review_status: str,
    comment: str | None = None,
    changes: dict | None = None,
) -> Claim:
    """人工审核：保留原始系统输出，EDITED 时把修改内容存入 review_changes。"""
    claim = get_claim_or_404(session, claim_id)
    ReviewStatus(review_status)  # 枚举校验，非法抛 ValidationError
    claim.review_status = review_status
    if comment is not None:
        claim.review_comment = comment
    if changes is not None:
        claim.review_changes = json.dumps(changes, ensure_ascii=False)
    claim.reviewed_at = _now()
    session.commit()
    return claim
