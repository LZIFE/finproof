"""Agent Tools（Phase 5）：封装已有能力为审计工具。

- extract_claims：调用已有 Claim Extraction（claim_service / 已有运行）；
- retrieve_evidence：调用 Evidence Retrieval（verification_service.fetch_evidence）；
- verify_claim：调用 Verification Engine（verification_service.verify_claim）；
- generate_report：调用报告生成器（report_generator）。
"""

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.claim import Claim, ExtractionRun
from app.services.verification import verification_service


def _claim_to_dict(row: Claim) -> dict:
    return {
        "claim_id": row.claim_uid,
        "claim_uid": row.claim_uid,
        "original_text": row.source_text,
        "source_text": row.source_text,
        "claim_type": row.claim_type,
        "entity_name": row.entity_name,
        "entity": row.entity_name,
        "stock_code": row.stock_code,
        "metric": row.metric,
        "metric_code": row.metric_code,
        "reported_value": row.reported_value,
        "value": row.reported_value,
        "unit": row.unit,
        "period": row.period,
        "comparison_period": row.comparison_period,
        "claim_nature": row.claim_nature,
    }


def extract_claims(session: Session, document_id: int, mode: str = "ai") -> list[dict]:
    """提取/读取文档主张（复用已有 Claim Extraction 能力）。

    优先使用该文档最近一次 COMPLETED 运行的主张；无则新建一次提取。
    """
    latest = (
        session.query(ExtractionRun)
        .filter(ExtractionRun.document_id == document_id)
        .order_by(ExtractionRun.id.desc())
        .first()
    )
    run_id = None
    if latest and latest.status == "COMPLETED":
        run_id = latest.id
    else:
        from app.services import claim_service

        run, _created = claim_service.run_claim_extraction(session, document_id, mode=mode, force=False)
        run_id = run.id
    rows = (
        session.query(Claim)
        .filter(Claim.extraction_run_id == run_id)
        .order_by(Claim.id)
        .all()
    )
    return [_claim_to_dict(r) for r in rows]


def retrieve_evidence(session: Session, claim: dict, top_k: int = 8) -> list[dict]:
    """检索主张证据（Top-K 候选 + 完整块文本 + 证据类型/打分）。"""
    return verification_service.fetch_evidence(session, claim, top_k=top_k)


def verify_claim(session: Session, claim: dict) -> dict:
    """调用 Verification Engine 核验单条主张。"""
    result = verification_service.verify_claim(session, claim)
    return result.to_dict()


def require_report_to_verify(session: Session, document_id: int) -> None:
    """校验文档为待核验研报（REPORT_TO_VERIFY），否则拒绝审计。"""
    from app.models import Document

    doc = session.get(Document, document_id)
    if doc is None:
        raise AppError(f"文档不存在: {document_id}", status_code=404, code="DOCUMENT_NOT_FOUND")
    if doc.document_role != "REPORT_TO_VERIFY":
        raise AppError(
            f"仅支持审计 REPORT_TO_VERIFY 研报（当前角色: {doc.document_role}）",
            status_code=422,
            code="INVALID_DOCUMENT_ROLE",
        )
    return doc
