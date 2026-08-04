"""Phase 23.11.3 Evidence Aggregation Truth Table (Task 4).

§4 aggregation真值表 — 不依赖多数投票或字符串判断.

Rules:
- 明确反驳优先: high-quality REFUTED with metric/period/scope MATCH
  不得被多个低质量 SUPPORTED 或 Narrative Evidence 覆盖
- 明确支持: 所有高质量 Evidence 一致 SUPPORTED → SUPPORTED
- 部分支持: Claim 多原子组成部分, 部分 SUPPORTED + 其余缺失 + 无冲突 → PARTIALLY_SUPPORTED
- 证据冲突: 高质量 SUPPORTED + REFUTED 同时 → conflict_detected=True, 不得多数投票,
  根据 source quality/metric/period/scope/document recency 判断, 无法解决 → INSUFFICIENT
- Noise: Gate接受但与核心 metric/period/scope 无关 → accepted_but_non_decisive, 不参与聚合

Pure function: no DB, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.services.verification_contract import (
    EvidenceVerificationResult, ClaimAggregationResult,
)
from app.services.evaluation_claim_schema import normalize_verdict_for_evaluation


# Aggregation rule IDs (§4)
RULE_SINGLE_EVIDENCE = "SINGLE_EVIDENCE"
RULE_REFUTED_PRIORITY = "REFUTED_PRIORITY"
RULE_ALL_SUPPORTED = "ALL_SUPPORTED"
RULE_PARTIAL = "PARTIAL_COMPONENTS"
RULE_CONFLICT = "CONFLICT_DETECTED"
RULE_ALL_INSUFFICIENT = "ALL_INSUFFICIENT"
RULE_EMPTY = "EMPTY_SELECTION"
RULE_NOISE_ONLY = "NOISE_ONLY"

# Evidence types considered narrative / qualitative (low-confidence narrative
# evidence must NOT override structured financial evidence, §8)
NARRATIVE_TYPE_MARKERS = ("narrative", "qualitative", "text", "mention", "commentary")


def _is_high_quality(ev: EvidenceVerificationResult) -> bool:
    """High-quality = high confidence AND metric/period/scope MATCH (not UNKNOWN)."""
    if ev.evidence_confidence < 0.6:
        return False
    # high-quality requires MATCH on core fields (not UNKNOWN, not MISMATCH)
    core_match = (
        ev.metric_match == "MATCH" and ev.period_match == "MATCH"
        and ev.scope_match == "MATCH"
    )
    return core_match


def _is_narrative_low_confidence(ev: EvidenceVerificationResult) -> bool:
    """Low-confidence narrative evidence (§8): must NOT override structured
    financial evidence. Narrative type + confidence below high-quality bar."""
    etype = str(ev.evidence_type or "").lower()
    is_narrative = any(m in etype for m in NARRATIVE_TYPE_MARKERS)
    return is_narrative and ev.evidence_confidence < 0.6


def _is_noise(ev: EvidenceVerificationResult) -> bool:
    """Noise = Gate accepted but与核心 metric/period/scope 无关 (UNKNOWN on core),
    OR low-confidence narrative that must not participate (§8)."""
    unrelated = (
        ev.metric_match == "UNKNOWN" and ev.period_match == "UNKNOWN"
        and ev.scope_match == "UNKNOWN"
    )
    mismatched = (
        ev.metric_match == "MISMATCH" or ev.period_match == "MISMATCH"
        or ev.scope_match == "MISMATCH"
    )
    return unrelated or mismatched or _is_narrative_low_confidence(ev)


def aggregate_evidence(
    claim_id: str,
    evidence_results: list[EvidenceVerificationResult],
) -> ClaimAggregationResult:
    """§4 aggregation真值表 — pure function.

    Returns ClaimAggregationResult with internal_verdict, external_verdict,
    conflict_detected, aggregation_rule, accepted_but_non_decisive list.
    """
    result = ClaimAggregationResult(claim_id=claim_id)
    result.evidence_results = evidence_results
    result.selected_evidence_ids = [r.evidence_id for r in evidence_results]

    if not evidence_results:
        result.aggregation_rule = RULE_EMPTY
        result.internal_verdict = "INSUFFICIENT_EVIDENCE"
        result.external_verdict = "INSUFFICIENT_EVIDENCE"
        result.abstention_reason = "no evidence selected"
        return result

    # Classify evidence: separate noise from decisive
    decisive = []
    non_decisive_noise_ids = []
    for ev in evidence_results:
        if _is_noise(ev):
            non_decisive_noise_ids.append(ev.evidence_id)
        else:
            decisive.append(ev)
    result.accepted_but_non_decisive = non_decisive_noise_ids
    result.decisive_evidence_ids = [ev.evidence_id for ev in decisive]
    result.non_decisive_evidence_ids = list(non_decisive_noise_ids)

    # If only noise → INSUFFICIENT (noise 不参与聚合)
    if not decisive:
        result.aggregation_rule = RULE_NOISE_ONLY
        result.internal_verdict = "INSUFFICIENT_EVIDENCE"
        result.external_verdict = "INSUFFICIENT_EVIDENCE"
        result.abstention_reason = "only noise evidence, no decisive evidence"
        return result

    # Count verdicts among decisive
    supported = [ev for ev in decisive if ev.evidence_verdict == "SUPPORTED"]
    refuted = [ev for ev in decisive if ev.evidence_verdict == "REFUTED"]
    partial = [ev for ev in decisive if ev.evidence_verdict == "PARTIALLY_SUPPORTED"]
    insufficient = [ev for ev in decisive if ev.evidence_verdict in ("INSUFFICIENT_EVIDENCE", "INSUFFICIENT", "")]

    result.supported_count = len(supported)
    result.refuted_count = len(refuted)
    result.partial_count = len(partial)
    result.insufficient_count = len(insufficient)
    result.high_confidence_supported_count = sum(1 for ev in supported if _is_high_quality(ev))
    result.high_confidence_refuted_count = sum(1 for ev in refuted if _is_high_quality(ev))

    def _set(verdict: str, rule: str, reason: str = "", conflict_ids: list | None = None):
        result.aggregation_rule = rule
        result.internal_verdict = verdict
        # 唯一外部评测映射 (§5) — 禁止自行映射
        result.external_verdict = normalize_verdict_for_evaluation(verdict)
        if reason:
            result.abstention_reason = reason
        if conflict_ids:
            result.conflict_evidence_ids = list(conflict_ids)

    # §4 single evidence
    if len(decisive) == 1:
        ev = decisive[0]
        result.aggregation_rule = RULE_SINGLE_EVIDENCE
        result.internal_verdict = ev.evidence_verdict or "INSUFFICIENT_EVIDENCE"
        result.external_verdict = normalize_verdict_for_evaluation(
            ev.evidence_verdict or "INSUFFICIENT_EVIDENCE"
        )
        result.confidence = ev.evidence_confidence
        return result

    # §4 明确反驳优先: high-quality REFUTED exists
    hq_refuted = [ev for ev in refuted if _is_high_quality(ev)]
    if hq_refuted:
        # 不得被多个低质量 SUPPORTED 覆盖
        result.confidence = max(ev.evidence_confidence for ev in hq_refuted)
        # Check if also high-quality SUPPORTED → conflict
        hq_supported = [ev for ev in supported if _is_high_quality(ev)]
        if hq_supported:
            result.conflict_detected = True
            _set(
                "CONFLICTING_EVIDENCE", RULE_CONFLICT,
                "high-quality SUPPORTED + high-quality REFUTED conflict; "
                "cannot resolve by majority vote",
                conflict_ids=[ev.evidence_id for ev in hq_supported + hq_refuted],
            )
        else:
            _set("REFUTED", RULE_REFUTED_PRIORITY)
        return result

    # §4 证据冲突: high-quality SUPPORTED + high-quality REFUTED 同时
    hq_supported = [ev for ev in supported if _is_high_quality(ev)]
    if hq_supported and hq_refuted:
        result.conflict_detected = True
        _set(
            "CONFLICTING_EVIDENCE", RULE_CONFLICT,
            "conflict between high-quality SUPPORTED and REFUTED",
            conflict_ids=[ev.evidence_id for ev in hq_supported + hq_refuted],
        )
        return result

    # §4 明确支持: 所有高质量 Evidence 一致 SUPPORTED (无 REFUTED / PARTIAL /
    # INSUFFICIENT 混合 — 否则属于多组成部分部分支持)
    if hq_supported and not refuted and not partial and not insufficient:
        _set("SUPPORTED", RULE_ALL_SUPPORTED)
        result.confidence = max(ev.evidence_confidence for ev in hq_supported)
        return result

    # §4 部分支持: 部分 SUPPORTED + 其余缺失 + 无冲突 → PARTIALLY_SUPPORTED
    if (supported or partial) and not refuted:
        if partial or (insufficient and supported):
            _set("PARTIALLY_SUPPORTED", RULE_PARTIAL)
            result.confidence = max((ev.evidence_confidence for ev in supported + partial), default=0.5)
        else:
            # all decisive are SUPPORTED (no partial, no insufficient)
            _set("SUPPORTED", RULE_ALL_SUPPORTED)
            result.confidence = max((ev.evidence_confidence for ev in supported), default=0.5)
        return result

    # §4 全弃权或冲突（Phase 23.11.4 §11: 混合REFUTED+SUPPORTED非high-quality也应标记冲突）
    if insufficient and not supported and not refuted and not partial:
        _set("INSUFFICIENT_EVIDENCE", RULE_ALL_INSUFFICIENT, "all evidence INSUFFICIENT")
        return result
    if supported and refuted:
        # Mixed REFUTED+SUPPORTED evidence (any quality) → conflict
        result.conflict_detected = True
        _set(
            "CONFLICTING_EVIDENCE", RULE_CONFLICT,
            "mixed SUPPORTED and REFUTED evidence; conflict cannot be resolved by majority vote",
            conflict_ids=[ev.evidence_id for ev in supported + refuted],
        )
        return result

    # Fallback
    _set("INSUFFICIENT_EVIDENCE", RULE_ALL_INSUFFICIENT, "unhandled aggregation case")
    return result


__all__ = [
    "aggregate_evidence",
    "RULE_SINGLE_EVIDENCE", "RULE_REFUTED_PRIORITY", "RULE_ALL_SUPPORTED",
    "RULE_PARTIAL", "RULE_CONFLICT", "RULE_ALL_INSUFFICIENT",
    "RULE_EMPTY", "RULE_NOISE_ONLY",
]
