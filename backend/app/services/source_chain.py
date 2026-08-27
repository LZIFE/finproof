"""来源链服务：组装"主张 → 证据 → 原始来源"的完整溯源链路。

给定 claim_id，一次性返回：
- 主张结构化信息
- 核验结论 + 来源风险标签
- 证据链（每条证据的来源等级、文档、页码、原文、是否被采用）
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.enums import SOURCE_LEVEL_LABELS
from app.models import Document
from app.services.verification.verification_service import (
    fetch_evidence,
    load_claim,
    verify_claim_production,
)


def build_source_chain(session: Session, claim_id: str, top_k: int = 5) -> dict:
    """构建单条主张的来源链。

    返回结构：
    {
        claim: {claim_id, text, metric, value, unit, period, entity},
        verdict: {status, confidence, reason, source_risk_tags},
        evidence_chain: [
            {rank, source_level, source_level_label, source_level_reason,
             document_name, company, report_period, page_number,
             evidence_type, text, score, selected}
        ],
        summary: {total, selected, strongest_level, weakest_level}
    }
    """
    claim = load_claim(session, claim_id)
    if claim is None:
        raise LookupError(f"主张不存在: {claim_id}")

    # 检索证据（含来源等级）
    evidence = fetch_evidence(session, claim, top_k=top_k)

    # 执行核验（含风险标签）
    result = verify_claim_production(claim, session, top_k=top_k)
    matched_ids = set(result.matched_evidence_ids or [])

    # 批量查文档信息
    doc_ids = {e.get("document_id") for e in evidence if e.get("document_id")}
    docs: dict[int, Document] = {}
    if doc_ids:
        rows = session.query(Document).filter(Document.id.in_(doc_ids)).all()
        docs = {d.id: d for d in rows}

    # 组装证据链
    chain = []
    for i, e in enumerate(evidence, start=1):
        doc = docs.get(e.get("document_id"))
        level = e.get("source_level", "NO_SOURCE")
        eid = e.get("evidence_id") or e.get("block_id")
        chain.append({
            "rank": i,
            "evidence_id": eid,
            "source_level": level,
            "source_level_label": SOURCE_LEVEL_LABELS.get(level, "未知"),
            "source_level_reason": e.get("source_level_reason"),
            "document_name": doc.original_filename if doc else None,
            "document_role": doc.document_role if doc else None,
            "company": doc.company_name if doc else claim.get("entity_name"),
            "report_period": e.get("doc_period") or (doc.report_period if doc else None),
            "page_number": e.get("page_number"),
            "evidence_type": e.get("evidence_type", "UNKNOWN"),
            "text": (e.get("text") or "")[:300],
            "score": round(float(e.get("final_score", 0.0)), 3),
            "selected": eid in matched_ids if matched_ids else i <= 3,
        })

    # 来源可信度汇总
    levels = [c["source_level"] for c in chain]
    level_order = [
        "OFFICIAL_DISCLOSURE", "REGULATORY_DATA", "THIRD_PARTY_REPORT",
        "MEDIA_REPORT", "CHANNEL_CHECK", "FORECAST", "NO_SOURCE",
    ]
    strongest = next((l for l in level_order if l in levels), "NO_SOURCE")
    weakest = next((l for l in reversed(level_order) if l in levels), "NO_SOURCE")

    return {
        "claim": {
            "claim_id": result.claim_id,
            "text": claim.get("original_text") or claim.get("claim_text") or "",
            "metric": claim.get("metric"),
            "metric_code": claim.get("metric_code"),
            "value": claim.get("reported_value") if claim.get("reported_value") is not None else claim.get("value"),
            "unit": claim.get("unit"),
            "period": claim.get("period"),
            "entity": claim.get("entity_name") or claim.get("entity"),
            "claim_type": claim.get("claim_type"),
        },
        "verdict": {
            "status": result.verification_status,
            "confidence": round(result.confidence, 4),
            "verification_type": result.verification_type,
            "reason": result.reason,
            "source_risk_tags": result.source_risk_tags or [],
        },
        "evidence_chain": chain,
        "summary": {
            "total_evidence": len(chain),
            "selected_count": sum(1 for c in chain if c["selected"]),
            "strongest_level": strongest,
            "strongest_label": SOURCE_LEVEL_LABELS.get(strongest, "未知"),
            "weakest_level": weakest,
            "weakest_label": SOURCE_LEVEL_LABELS.get(weakest, "未知"),
            "risk_count": len(result.source_risk_tags or []),
        },
    }
