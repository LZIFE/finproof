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
        # Reconstructed business evidence may span several source blocks.  It
        # is the canonical text for verification and must not be replaced by
        # the anchor block loaded from the database.
        text = c.get("evidence_text") or ""
        if not text and c.get("block_id"):
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
                "source_level": c.get("source_level", "NO_SOURCE"),
                "source_level_reason": c.get("source_level_reason"),
                "doc_role": doc.document_role if doc else "SOURCE_DOCUMENT",
                "doc_publication_date": doc.publication_date if doc else None,
                # Phase 23.23 Task 2：FinancialEvidenceObject 传入验证链（不删 raw block 字段）
                "financial_fact": c.get("financial_fact"),
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
                source_risk_tags=json.dumps(d.get("source_risk_tags", []), ensure_ascii=False)
                if d.get("source_risk_tags")
                else None,
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
                "source_risk_tags": json.loads(r.source_risk_tags) if r.source_risk_tags else [],
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


# ===========================================================================
# Phase 23.11: Canonical verify_evidence_set entry (shared by all 3 modes)
# ===========================================================================

from app.services.claim_router import route_claim as _route_claim, ClaimRoutingResult  # noqa: E402
from app.services.evidence_gate import evaluate_all as _gate_evaluate_all  # noqa: E402
from app.services.evidence_selector import select as _selector_select  # noqa: E402
from app.services.verification.core_pipeline import (  # noqa: E402
    IntegrationTrace,
    core_verify,
)


def verify_evidence_set(
    claim: dict,
    evidence_candidates: list[dict],
    routing_result: "ClaimRoutingResult",
    verification_context,
    session: Session | None = None,
) -> VerificationResult:
    """Canonical verification entry (Phase 23.11).

    Runs: Evidence Gate -> Evidence Selector -> core_verify.
    Shared by CORE_ORACLE, NOISY_ORACLE, REAL_E2E.
    Gold Evidence must pass through Gate and Selector; if Gold is rejected,
    result is INSUFFICIENT_EVIDENCE (GATE_REJECTED_GOLD), do NOT bypass.
    """
    # Initialize trace if not provided
    if verification_context.trace is None:
        verification_context.trace = IntegrationTrace(
            claim_id=str(claim.get("claim_id") or claim.get("claim_uid") or "?")
        )
    trace = verification_context.trace

    # Phase 23.24 Task 2/3：Fact verification path——含 financial_fact 的证据附加事实验证诊断。
    # 只附加 fact_verification 字段（补充信息），不删除/替换 raw block 候选，
    # 不改变 Gate 决策规则（Gate 仍按原字段判定）。
    from app.services.verification.fact_verification_path import attach_fact_verifications

    evidence_candidates = attach_fact_verifications(claim, evidence_candidates)

    # Record candidates before gate
    verification_context.candidates_before_gate = len(evidence_candidates)

    # Step 1: Evidence Gate (pure)
    gate_results = _gate_evaluate_all(
        claim, evidence_candidates, routing_result,
        verification_context.gate_config,
    )
    verification_context.candidates_after_gate = sum(
        1 for r in gate_results if r.accepted
    )

    # Record gate step in trace
    trace.detail["phase23_11_gate"] = {
        "evidence_source": verification_context.evidence_source,
        "candidates_before_gate": verification_context.candidates_before_gate,
        "candidates_after_gate": verification_context.candidates_after_gate,
        "gate_results": [r.to_dict() for r in gate_results],
    }

    # Step 2: Evidence Selector (pure)
    evidence_bundle, selection_meta = _selector_select(
        gate_results, routing_result, verification_context.selector_config,
    )
    trace.detail["phase23_11_selector"] = selection_meta.to_dict()

    # Step 3: core_verify (UNCHANGED) with gated evidence
    final = core_verify(claim, evidence_bundle, trace)

    # Step 4: 来源风险检测（不改变核验判定，只附加风险标签）
    # 从 Gate 前候选建立 evidence_id → 完整信息映射，补回 source_level
    cand_by_id = {}
    for c in evidence_candidates:
        cid = c.get("evidence_id") or c.get("block_id")
        if cid is not None:
            cand_by_id[cid] = c
    # 给 Selector 选出的证据补上 source_level 等字段
    enriched_bundle = []
    for e in evidence_bundle:
        eid = e.get("evidence_id")
        merged = dict(e)
        if eid in cand_by_id:
            src = cand_by_id[eid]
            merged.setdefault("source_level", src.get("source_level", "NO_SOURCE"))
            merged.setdefault("source_level_reason", src.get("source_level_reason"))
            merged.setdefault("doc_period", src.get("doc_period"))
            merged.setdefault("final_score", src.get("final_score", 0.0))
        enriched_bundle.append(merged)

    from app.services.verification.source_risk_detector import detect_source_risks

    final.source_risk_tags = detect_source_risks(
        claim,
        candidates=enriched_bundle + [
            c for c in evidence_candidates
            if (c.get("evidence_id") or c.get("block_id"))
            not in set(selection_meta.selected_evidence_ids)
        ],
        selected_ids=selection_meta.selected_evidence_ids,
        session=session,
    )

    # Attach routing + selection metadata to trace
    trace.detail["phase23_11_routing"] = routing_result.to_dict()
    trace.detail["phase23_11_final"] = {
        "verification_status": final.verification_status,
        "confidence": final.confidence,
    }

    return final


def verify_core_oracle(
    claim: dict,
    gold_evidence: dict,
    routing: "ClaimRoutingResult",
    ctx,
) -> VerificationResult:
    """CORE_ORACLE: Gold Evidence -> Gate -> Selector -> core_verify.

    If Gold is rejected by Gate, result is INSUFFICIENT_EVIDENCE
    (GATE_REJECTED_GOLD), do NOT bypass to protect Oracle 1.0.
    """
    return verify_evidence_set(claim, [gold_evidence], routing, ctx)


def verify_noisy_oracle(
    claim: dict,
    gold_plus_negatives: list[dict],
    routing: "ClaimRoutingResult",
    ctx,
) -> VerificationResult:
    """NOISY_ORACLE: Gold + Hard Negatives -> Gate -> Selector -> core_verify."""
    return verify_evidence_set(claim, gold_plus_negatives, routing, ctx)


def verify_real_e2e(
    claim: dict,
    routing: "ClaimRoutingResult",
    ctx,
    session: Session,
    top_k: int = 5,
) -> VerificationResult:
    """REAL_E2E: Claim Router -> Retrieval -> Gate -> Selector -> core_verify."""
    # Phase 23.35: adapt retrieval candidates to Gate-expected schema.
    # retrieve_for_claim returns {block_id, block_text, financial_fact, ...} —
    # Gate reads candidate["text"], which was empty → all rejected → no_evidence.
    # fetch_evidence maps block_text→text and passes financial_fact through.
    candidates = fetch_evidence(session, claim, top_k=top_k)
    return verify_evidence_set(claim, candidates, routing, ctx, session=session)


def verify_claim_production(
    claim: dict,
    session: Session,
    top_k: int = 5,
) -> VerificationResult:
    """Production main chain (Phase 23.11).

    Used by real API, Demo, and Real E2E. Unified entry.
    """
    from app.services.verification_context import VerificationContext

    routing = _route_claim(claim)
    ctx = VerificationContext(evidence_source="real_e2e")
    return verify_real_e2e(claim, routing, ctx, session, top_k=top_k)
