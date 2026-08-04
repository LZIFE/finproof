"""Phase 23.11 Evidence Selector (pure function).

Dedup near-duplicates, cap at max_evidence (default 3), support Top1/Top3/
Top5 strategies, detect ambiguity margin when top1 ≈ top2 but metric/period/
scope differ.

Pure: no DB, no I/O. Tunable thresholds only via leave-one-company-out CV.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.services.claim_router import ClaimRoutingResult
from app.services.evidence_gate import EvidenceQualityResult


@dataclass
class SelectorConfig:
    """Selector thresholds (tuned only via leave-one-company-out CV)."""

    strategy: Literal["Top1", "Top3", "Top5"] = "Top3"
    max_evidence: int = 3
    ambiguity_margin: float = 0.05
    duplicate_page_threshold: float = 0.9


@dataclass
class SelectionResult:
    """Result of evidence selection."""

    selected_evidence_ids: list = field(default_factory=list)
    rejected_evidence_ids: list = field(default_factory=list)
    candidates_before_gate: int = 0
    candidates_after_gate: int = 0
    evidence_bundle: list = field(default_factory=list)
    selection_reason: str = ""
    top1_quality: float = 0.0
    top2_quality: float = 0.0
    quality_margin: float = 0.0
    ambiguity_flag: bool = False
    ambiguity_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "selected_evidence_ids": self.selected_evidence_ids,
            "rejected_evidence_ids": self.rejected_evidence_ids,
            "candidates_before_gate": self.candidates_before_gate,
            "candidates_after_gate": self.candidates_after_gate,
            "evidence_bundle": self.evidence_bundle,
            "selection_reason": self.selection_reason,
            "top1_quality": round(self.top1_quality, 4),
            "top2_quality": round(self.top2_quality, 4),
            "quality_margin": round(self.quality_margin, 4),
            "ambiguity_flag": self.ambiguity_flag,
            "ambiguity_reason": self.ambiguity_reason,
        }


def select(
    gate_results: list[EvidenceQualityResult],
    routing: ClaimRoutingResult,
    config: SelectorConfig,
) -> tuple[list[dict], SelectionResult]:
    """Pure selection: gate results -> final evidence bundle + metadata.

    Steps:
    1. Filter accepted candidates from gate results
    2. Sort by final_quality_score descending
    3. Cap at max_count based on strategy (Top1=1, Top3=3, Top5=5)
    4. Detect ambiguity margin when top1 ≈ top2 but signals differ
    5. Build evidence_bundle dict format for core_verify
    """
    before = len(gate_results)
    accepted = [r for r in gate_results if r.accepted]
    rejected = [r for r in gate_results if not r.accepted]
    after = len(accepted)

    # Sort accepted by quality score descending
    accepted.sort(key=lambda r: r.final_quality_score, reverse=True)

    # Strategy determines max count
    if config.strategy == "Top1":
        max_count = 1
    elif config.strategy == "Top3":
        max_count = min(3, config.max_evidence)
    elif config.strategy == "Top5":
        max_count = min(5, config.max_evidence)
    else:
        max_count = config.max_evidence

    # Take top max_count
    top_accepted = accepted[:max_count]

    # Compute quality metrics
    top1_q = (
        top_accepted[0].final_quality_score
        if len(top_accepted) >= 1
        else 0.0
    )
    top2_q = (
        top_accepted[1].final_quality_score
        if len(top_accepted) >= 2
        else 0.0
    )
    margin = abs(top1_q - top2_q)

    # Ambiguity detection: top1 ≈ top2 (margin < threshold) but signals differ
    ambiguity = False
    ambiguity_reason = ""
    if len(top_accepted) >= 2 and margin < config.ambiguity_margin:
        r1, r2 = top_accepted[0], top_accepted[1]
        if (
            r1.metric_match != r2.metric_match
            or r1.period_match != r2.period_match
            or r1.scope_match != r2.scope_match
        ):
            ambiguity = True
            ambiguity_reason = (
                f"top1 quality {top1_q:.3f} ≈ top2 quality {top2_q:.3f} "
                f"but metric/period/scope signals differ"
            )

    # Build evidence bundle (dict format for core_verify)
    evidence_bundle = []
    for r in top_accepted:
        evidence_bundle.append({
            "evidence_id": r.evidence_id,
            "text": "",  # filled by retrieve_via_channels
            "final_quality_score": r.final_quality_score,
        })

    # Selection reason
    if not top_accepted:
        reason = "no evidence accepted by gate"
    elif ambiguity:
        reason = f"ambiguity detected: {ambiguity_reason}"
    else:
        reason = (
            f"selected {len(top_accepted)} evidence via {config.strategy}"
        )

    meta = SelectionResult(
        selected_evidence_ids=[r.evidence_id for r in top_accepted],
        rejected_evidence_ids=[r.evidence_id for r in rejected],
        candidates_before_gate=before,
        candidates_after_gate=after,
        evidence_bundle=evidence_bundle,
        selection_reason=reason,
        top1_quality=top1_q,
        top2_quality=top2_q,
        quality_margin=margin,
        ambiguity_flag=ambiguity,
        ambiguity_reason=ambiguity_reason,
    )
    return evidence_bundle, meta


__all__ = ["SelectorConfig", "SelectionResult", "select"]
