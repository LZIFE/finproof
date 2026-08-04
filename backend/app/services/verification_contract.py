"""Phase 23.11.3 Canonical Verification Contract (Task 1).

Unified data structures for the Evidence → Claim verdict pipeline:
- EvidenceVerificationResult: per-evidence verdict + rule_id + calculated_value
- ClaimAggregationResult: aggregation of evidence verdicts → internal/external verdict

Root causes fixed here (§1):
- Phase 23.11.2 reported 33 AGGREGATION_WRONG but never逐层对账; no structured
  intermediate state between Selector output and final verdict.
- Gold Selection Rate=0.814 had no explanation of how evidence-level verdict
  becomes final claim verdict.
- selective_accuracy=1.0 on 13.95% coverage cannot prove core_verify整体正确.

These dataclasses make every intermediate state inspectable, so first_
divergence_stage can be定位 to CANONICAL_ADAPTER / GATE / SELECTOR /
CORE_VERIFY / AGGREGATION / VERDICT_NORMALIZATION / EVALUATION_JOIN / NONE.

Forbidden: 聚合过程中只传递字符串摘要; 无结构化中间状态.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ===========================================================================
# EvidenceVerificationResult (§1)
# ===========================================================================

@dataclass
class EvidenceVerificationResult:
    """Per-evidence verification outcome (§1).

    All中间状态结构化保存 — 不只传字符串摘要。
    """

    claim_id: str
    evidence_id: str
    evidence_text: str = ""
    evidence_type: str = ""
    # Gate-level
    gate_quality_score: float = 0.0
    gate_status: str = ""  # ACCEPTED / REJECTED / UNKNOWN
    # Selector-level
    selector_rank: int = 0  # 0 = not selected
    # Three-state match (from Gate)
    entity_match: str = "UNKNOWN"  # MATCH / MISMATCH / UNKNOWN
    metric_match: str = "UNKNOWN"
    period_match: str = "UNKNOWN"
    unit_match: str = "UNKNOWN"
    scope_match: str = "UNKNOWN"
    numeric_match: str = "UNKNOWN"
    # Evidence-level verdict (from core_verify on this single evidence)
    evidence_verdict: str = ""  # SUPPORTED / REFUTED / PARTIALLY_SUPPORTED / INSUFFICIENT / UNABLE
    evidence_confidence: float = 0.0
    rule_id: str = ""
    calculated_value: float | None = None
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id, "evidence_id": self.evidence_id,
            "evidence_text": self.evidence_text[:200],
            "evidence_type": self.evidence_type,
            "gate_quality_score": round(self.gate_quality_score, 4),
            "gate_status": self.gate_status, "selector_rank": self.selector_rank,
            "entity_match": self.entity_match, "metric_match": self.metric_match,
            "period_match": self.period_match, "unit_match": self.unit_match,
            "scope_match": self.scope_match, "numeric_match": self.numeric_match,
            "evidence_verdict": self.evidence_verdict,
            "evidence_confidence": round(self.evidence_confidence, 4),
            "rule_id": self.rule_id, "calculated_value": self.calculated_value,
            "rejection_reason": self.rejection_reason,
        }


# ===========================================================================
# ClaimAggregationResult (§1)
# ===========================================================================

@dataclass
class ClaimAggregationResult:
    """Aggregation of evidence-level verdicts → claim verdict (§1).

    §4 真值表:
    - 明确反驳优先 (high-quality REFUTED with metric/period/scope MATCH)
      不得被低质量 SUPPORTED 覆盖
    - 所有高质量 SUPPORTED 一致 → SUPPORTED
    - 部分 SUPPORTED + 缺失 + 无冲突 → PARTIALLY_SUPPORTED
    - 高质量 SUPPORTED + REFUTED 同时 → conflict_detected=True, 不得多数投票
    - Gate接受但与核心metric/period/scope无关 → accepted_but_non_decisive, 不参与聚合
    """

    claim_id: str
    selected_evidence_ids: list = field(default_factory=list)
    evidence_results: list = field(default_factory=list)  # list[EvidenceVerificationResult]
    # Counts
    supported_count: int = 0
    refuted_count: int = 0
    partial_count: int = 0
    insufficient_count: int = 0
    high_confidence_supported_count: int = 0
    high_confidence_refuted_count: int = 0
    # Conflict
    conflict_detected: bool = False
    aggregation_rule: str = ""  # which rule fired
    # Verdicts
    internal_verdict: str = ""  # raw verdict from aggregation
    external_verdict: str = ""  # normalized for evaluation
    confidence: float = 0.0
    abstention_reason: str = ""
    # Non-decisive noise tracking
    accepted_but_non_decisive: list = field(default_factory=list)
    # §8 explicit ID sets (output required by phase23_11_3)
    decisive_evidence_ids: list = field(default_factory=list)
    non_decisive_evidence_ids: list = field(default_factory=list)
    conflict_evidence_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "selected_evidence_ids": self.selected_evidence_ids,
            "evidence_results": [r.to_dict() for r in self.evidence_results],
            "supported_count": self.supported_count,
            "refuted_count": self.refuted_count,
            "partial_count": self.partial_count,
            "insufficient_count": self.insufficient_count,
            "high_confidence_supported_count": self.high_confidence_supported_count,
            "high_confidence_refuted_count": self.high_confidence_refuted_count,
            "conflict_detected": self.conflict_detected,
            "aggregation_rule": self.aggregation_rule,
            "internal_verdict": self.internal_verdict,
            "external_verdict": self.external_verdict,
            "confidence": round(self.confidence, 4),
            "abstention_reason": self.abstention_reason,
            "accepted_but_non_decisive": self.accepted_but_non_decisive,
            "decisive_evidence_ids": self.decisive_evidence_ids,
            "non_decisive_evidence_ids": self.non_decisive_evidence_ids,
            "conflict_evidence_ids": self.conflict_evidence_ids,
        }


# ===========================================================================
# First divergence stage taxonomy (§2)
# ===========================================================================

STAGE_CANONICAL_ADAPTER = "CANONICAL_ADAPTER"
STAGE_GATE = "GATE"
STAGE_SELECTOR = "SELECTOR"
STAGE_CORE_VERIFY = "CORE_VERIFY"
STAGE_AGGREGATION = "AGGREGATION"
STAGE_VERDICT_NORMALIZATION = "VERDICT_NORMALIZATION"
STAGE_EVALUATION_JOIN = "EVALUATION_JOIN"
STAGE_NONE = "NONE"

FIRST_DIVG_STAGES: tuple[str, ...] = (
    STAGE_CANONICAL_ADAPTER, STAGE_GATE, STAGE_SELECTOR,
    STAGE_CORE_VERIFY, STAGE_AGGREGATION,
    STAGE_VERDICT_NORMALIZATION, STAGE_EVALUATION_JOIN, STAGE_NONE,
)


__all__ = [
    "EvidenceVerificationResult", "ClaimAggregationResult",
    "FIRST_DIVG_STAGES", "STAGE_CANONICAL_ADAPTER", "STAGE_GATE",
    "STAGE_SELECTOR", "STAGE_CORE_VERIFY", "STAGE_AGGREGATION",
    "STAGE_VERDICT_NORMALIZATION", "STAGE_EVALUATION_JOIN", "STAGE_NONE",
]
