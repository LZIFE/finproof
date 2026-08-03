"""核验编排服务（Phase 4B.1）：claim → 证据检索 → 验证器选择 → VerificationResult。

架构：Deterministic Verification Engine（规则/计算核验，不依赖 LLM 自由判断）。
输入主张：claims 表（id/claim_uid）或金标准主张（CLM-xxx，Oracle 演示）。
证据：复用证据检索引擎（retrieve_for_claim），取完整块文本。
"""

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.models import DocumentBlock
from app.services.evidence_retrieval.service import retrieve_for_claim
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    TYPE_EXACT_VALUE,
    TYPE_GROWTH_RATE,
    TYPE_MULTI_EVIDENCE,
    TYPE_PERIOD,
    TYPE_SEMANTIC,
    VerificationResult,
    claim_text_of,
    claim_value_of,
)
from app.services.verification.evidence_checker import verify_multi_evidence, verify_semantic
from app.services.verification.growth_verifier import verify_growth_rate
from app.services.verification.numeric_verifier import verify_exact_value
from app.services.verification.period_verifier import verify_period_quarter

GOLD_PATHS = {
    "demo": BASE_DIR / "data" / "demo" / "annotations" / "gold_claims.json",
    "holdout": BASE_DIR / "data" / "holdout" / "annotations" / "gold_claims.json",
}
_GOLD_CACHE: dict[str, dict] = {}


def _load_gold_claims() -> dict[str, dict]:
    if _GOLD_CACHE:
        return _GOLD_CACHE
    for path in GOLD_PATHS.values():
        if not path.exists():
            continue
        for c in json.loads(path.read_text(encoding="utf-8"))["claims"]:
            _GOLD_CACHE[c["claim_id"]] = c
    return _GOLD_CACHE


def load_claim(session: Session, claim_id: str) -> dict | None:
    """加载主张：优先 claims 表（数字 id 或 claim_uid），其次金标准（CLM-xxx）。"""
    from app.models.claim import Claim

    if claim_id.isdigit():
        row = session.get(Claim, int(claim_id))
        if row:
            return {
                "claim_id": row.claim_uid,
                "claim_uid": row.claim_uid,
                "original_text": row.source_text,
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
    row = (
        session.query(Claim)
        .filter(Claim.claim_uid == claim_id)
        .order_by(Claim.id.desc())
        .first()
    )
    if row:
        return load_claim(session, str(row.id))
    return _load_gold_claims().get(claim_id)


def fetch_evidence(session: Session, claim: dict, top_k: int = 5) -> list[dict]:
    """检索主张证据：Top-K 候选 + 完整块文本 + 打分元数据。"""
    candidates = retrieve_for_claim(session, claim, top_k=top_k)
    out: list[dict] = []
    for c in candidates:
        text = ""
        if c.get("block_id"):
            block = session.get(DocumentBlock, c["block_id"])
            text = block.text if block else ""
        if not text:
            text = c.get("block_text") or ""
        from app.models import Document

        doc = session.get(Document, c.get("document_id")) if c.get("document_id") else None
        out.append(
            {
                "evidence_id": c.get("block_id"),
                "block_id": c.get("block_id"),
                "page_number": c.get("page_number"),
                "document_id": c.get("document_id"),
                "doc_period": doc.report_period if doc else None,
                "text": text,
                "final_score": c.get("final_score", 0.0),
                "value_score": c.get("value_score", 0.0),
                "metric_score": c.get("metric_score", 0.0),
                "period_score": c.get("period_score", 0.0),
                "evidence_type": c.get("evidence_type", "UNKNOWN"),
                "evidence_rank_reason": c.get("evidence_rank_reason"),
            }
        )
    return out


def _select_verifier(claim: dict, evidence: list[dict]) -> VerificationResult:
    """按主张类型选择验证器（确定性规则，无 LLM 自由判断）。

    Phase 23.9：主链切换到 core_pipeline（PRIMARY 路径）。
    core_verify 整合 FinancialValue / PeriodContext / metric_scope /
    verdict_decision / semantic_verifier，并在 VerificationResult 上附带
    integration_trace（供 43 条 Oracle trace 脚本读取）。
    旧 verify_exact_value 等验证器保留为 LEGACY（仅测试与诊断脚本使用）。
    """
    from app.services.verification.core_pipeline import IntegrationTrace, core_verify

    evidence_list = [
        {
            "evidence_id": e.get("evidence_id") or e.get("block_id"),
            "block_id": e.get("block_id"),
            "text": e.get("text", ""),
            "doc_period": e.get("doc_period"),
            "document_name": e.get("document_name"),
            "page": e.get("page_number"),
        }
        for e in evidence
    ]
    trace = IntegrationTrace(claim_id=claim.get("claim_id") or claim.get("claim_uid") or "?")
    return core_verify(claim, evidence_list, trace)


def verify_claim(session: Session, claim: dict, top_k: int = 8) -> VerificationResult:
    """单条主张核验：检索证据 → 验证器 → 结果。"""
    evidence = fetch_evidence(session, claim, top_k=top_k)
    return _select_verifier(claim, evidence)


def run_verification_batch(
    session: Session,
    claim_ids: list[str],
    mode: str = "RULE_BASED",
    top_k: int = 8,
) -> "VerificationRun":
    """批量核验并持久化：创建 verification_runs + verification_results 行。"""
    from app.models.verification import VerificationResultRow, VerificationRun

    run = VerificationRun(mode=mode, claim_count=len(claim_ids), status="COMPLETED")
    session.add(run)
    session.commit()
    results = run_verification(session, claim_ids, mode=mode, top_k=top_k)
    for r in results:
        d = r.to_dict()
        session.add(
            VerificationResultRow(
                verification_run_id=run.id,
                claim_id=d["claim_id"],
                verification_status=d["verification_status"],
                confidence=d["confidence"],
                verification_type=d["verification_type"],
                matched_evidence_ids=json.dumps(d["matched_evidence_ids"], ensure_ascii=False),
                calculation_detail=json.dumps(d["calculation_detail"], ensure_ascii=False)
                if d["calculation_detail"]
                else None,
                reason=d["reason"],
            )
        )
    session.commit()
    return run


def get_verification_results(session: Session, run_id: int) -> list[dict]:
    """读取一次核验任务的全部结果（含匹配证据与计算明细）。"""
    from app.models.verification import VerificationResultRow

    rows = (
        session.query(VerificationResultRow)
        .filter(VerificationResultRow.verification_run_id == run_id)
        .order_by(VerificationResultRow.id)
        .all()
    )
    out = []
    for r in rows:
        out.append(
            {
                "claim_id": r.claim_id,
                "verification_status": r.verification_status,
                "confidence": r.confidence,
                "verification_type": r.verification_type,
                "matched_evidence_ids": json.loads(r.matched_evidence_ids or "[]"),
                "calculation_detail": json.loads(r.calculation_detail) if r.calculation_detail else None,
                "reason": r.reason,
            }
        )
    return out


def run_verification(
    session: Session,
    claim_ids: list[str],
    mode: str = "RULE_BASED",
    top_k: int = 8,
) -> list[VerificationResult]:
    """批量核验：对每个 claim_id 执行核验并返回结果列表。"""
    results: list[VerificationResult] = []
    for cid in claim_ids:
        claim = load_claim(session, cid)
        if claim is None:
            results.append(
                VerificationResult(
                    cid, STATUS_INSUFFICIENT, confidence=0.2,
                    verification_type=TYPE_EXACT_VALUE, reason="主张不存在",
                )
            )
            continue
        try:
            results.append(verify_claim(session, claim, top_k=top_k))
        except Exception as exc:  # noqa: BLE001
            results.append(
                VerificationResult(
                    cid, STATUS_INSUFFICIENT, confidence=0.2,
                    verification_type=TYPE_EXACT_VALUE, reason=f"核验异常: {exc}",
                )
            )
    return results
