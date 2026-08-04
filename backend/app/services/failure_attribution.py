"""Phase 23.11.2 Failure Attribution (Task 7).

Mutually-exclusive primary outcome classification per claim (§7):
- RETRIEVAL_NO_CANDIDATE
- GATE_REJECTED_ALL
- GATE_REJECTED_GOLD
- GATE_ACCEPTED_NOISE
- SELECTOR_EMPTY
- SELECTOR_CHOSE_NOISE
- VERIFICATION_WRONG
- AGGREGATION_WRONG
- CORRECT_ABSTENTION
- SUCCESS

Each claim has exactly ONE primary_outcome. Sum over 43 claims MUST = 43.
Secondary causes may be recorded but do not affect the sum.

This fixes the Phase 23.11.1 bug where REAL_E2E reported gate_failure=0
despite 21 claims having all candidates rejected by gate — the legacy
counter only incremented when candidates existed AND none were accepted,
which contradicted the abstention diagnosis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Mutually-exclusive primary outcome categories (§7)
OUTCOME_RETRIEVAL_NO_CANDIDATE = "RETRIEVAL_NO_CANDIDATE"
OUTCOME_GATE_REJECTED_ALL = "GATE_REJECTED_ALL"
OUTCOME_GATE_REJECTED_GOLD = "GATE_REJECTED_GOLD"
OUTCOME_GATE_ACCEPTED_NOISE = "GATE_ACCEPTED_NOISE"
OUTCOME_SELECTOR_EMPTY = "SELECTOR_EMPTY"
OUTCOME_SELECTOR_CHOSE_NOISE = "SELECTOR_CHOSE_NOISE"
OUTCOME_VERIFICATION_WRONG = "VERIFICATION_WRONG"
OUTCOME_AGGREGATION_WRONG = "AGGREGATION_WRONG"
OUTCOME_CORRECT_ABSTENTION = "CORRECT_ABSTENTION"
OUTCOME_SUCCESS = "SUCCESS"

PRIMARY_OUTCOMES: tuple[str, ...] = (
    OUTCOME_RETRIEVAL_NO_CANDIDATE,
    OUTCOME_GATE_REJECTED_ALL,
    OUTCOME_GATE_REJECTED_GOLD,
    OUTCOME_GATE_ACCEPTED_NOISE,
    OUTCOME_SELECTOR_EMPTY,
    OUTCOME_SELECTOR_CHOSE_NOISE,
    OUTCOME_VERIFICATION_WRONG,
    OUTCOME_AGGREGATION_WRONG,
    OUTCOME_CORRECT_ABSTENTION,
    OUTCOME_SUCCESS,
)


@dataclass
class ClaimOutcome:
    """Per-claim mutually-exclusive primary outcome + secondary causes."""

    claim_id: str
    primary_outcome: str
    secondary_causes: list = None
    pred: str = ""
    gold: str = ""
    correct: bool = False

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "primary_outcome": self.primary_outcome,
            "secondary_causes": self.secondary_causes or [],
            "pred": self.pred, "gold": self.gold, "correct": self.correct,
        }


def classify_outcome(
    claim_id: str,
    pred: str,
    gold: str,
    candidates_before_gate: int,
    candidates_after_gate: int,
    selector_input_count: int,
    selector_output_count: int,
    selector_empty_reason: str,
    gold_evidence_count: int = 0,
    gold_accepted: bool = False,
    noise_accepted: bool = False,
    selected_ids: list = None,
    gold_evidence_ids: list = None,
) -> ClaimOutcome:
    """Classify one claim into exactly ONE primary_outcome (§7).

    Decision order (mutually-exclusive):
    1. pred == gold → SUCCESS (or CORRECT_ABSTENTION if pred is abstain)
    2. candidates_before_gate == 0 → RETRIEVAL_NO_CANDIDATE
    3. candidates_after_gate == 0 → GATE_REJECTED_ALL
    4. selector_input > 0 but selector_output == 0 → SELECTOR_EMPTY
    5. Verification pred != gold (non-abstain) → VERIFICATION_WRONG
    6. Abstain pred != gold (gold is non-abstain) → classify gate/selector blame
    """
    selected_ids = selected_ids or []
    gold_evidence_ids = set(str(x) for x in (gold_evidence_ids or []))
    secondaries = []

    # 1. Correct
    if pred == gold:
        if pred in ("INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE"):
            outcome = OUTCOME_CORRECT_ABSTENTION
        else:
            outcome = OUTCOME_SUCCESS
        return ClaimOutcome(claim_id, outcome, secondaries, pred, gold, True)

    # 2. Retrieval no candidate
    if candidates_before_gate == 0:
        return ClaimOutcome(
            claim_id, OUTCOME_RETRIEVAL_NO_CANDIDATE,
            ["retrieval returned 0 candidates"], pred, gold, False,
        )

    # 3. Gate rejected all
    if candidates_after_gate == 0:
        # If gold evidence existed and was rejected, distinguish GATE_REJECTED_GOLD
        if gold_evidence_count > 0 and not gold_accepted:
            return ClaimOutcome(
                claim_id, OUTCOME_GATE_REJECTED_GOLD,
                [f"gate rejected {gold_evidence_count} gold evidence"], pred, gold, False,
            )
        return ClaimOutcome(
            claim_id, OUTCOME_GATE_REJECTED_ALL,
            [f"gate rejected all {candidates_before_gate} candidates"], pred, gold, False,
        )

    # 4. Selector empty (gate admitted but selector returned empty)
    if selector_input_count > 0 and selector_output_count == 0:
        return ClaimOutcome(
            claim_id, OUTCOME_SELECTOR_EMPTY,
            [f"selector empty: {selector_empty_reason}"], pred, gold, False,
        )

    # 5. Selector chose noise (gold was available but rejected; non-gold selected)
    if gold_evidence_ids and not any(
        str(x) in gold_evidence_ids for x in selected_ids
    ) and gold_evidence_count > 0:
        return ClaimOutcome(
            claim_id, OUTCOME_SELECTOR_CHOSE_NOISE,
            [f"selector chose non-gold: {selected_ids}"], pred, gold, False,
        )

    # 6. Gate accepted noise (no gold available but noise accepted → wrong verdict)
    if noise_accepted and gold_evidence_count == 0:
        return ClaimOutcome(
            claim_id, OUTCOME_GATE_ACCEPTED_NOISE,
            ["gate accepted noise, no gold available"], pred, gold, False,
        )

    # 7. Verification wrong (gate+selector produced evidence but core_verify wrong)
    if pred not in ("INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE"):
        return ClaimOutcome(
            claim_id, OUTCOME_VERIFICATION_WRONG,
            ["core_verify produced wrong verdict with admitted evidence"],
            pred, gold, False,
        )

    # 8. Aggregation wrong (multi-evidence aggregation conflict)
    return ClaimOutcome(
        claim_id, OUTCOME_AGGREGATION_WRONG,
        ["multi-evidence aggregation produced wrong verdict"], pred, gold, False,
    )


def summarize_outcomes(outcomes: list[ClaimOutcome]) -> dict:
    """Summarize primary_outcome counts; verify sum == total (§7)."""
    from collections import Counter
    c = Counter(o.primary_outcome for o in outcomes)
    total = len(outcomes)
    outcome_sum = sum(c.values())
    return {
        "total_claims": total,
        "outcome_counts": dict(c),
        "outcome_sum": outcome_sum,
        "sum_equals_total": outcome_sum == total,
        "mutually_exclusive": True,
        "primary_outcomes": list(PRIMARY_OUTCOMES),
    }


__all__ = [
    "PRIMARY_OUTCOMES",
    "ClaimOutcome",
    "classify_outcome",
    "summarize_outcomes",
    "OUTCOME_RETRIEVAL_NO_CANDIDATE", "OUTCOME_GATE_REJECTED_ALL",
    "OUTCOME_GATE_REJECTED_GOLD", "OUTCOME_GATE_ACCEPTED_NOISE",
    "OUTCOME_SELECTOR_EMPTY", "OUTCOME_SELECTOR_CHOSE_NOISE",
    "OUTCOME_VERIFICATION_WRONG", "OUTCOME_AGGREGATION_WRONG",
    "OUTCOME_CORRECT_ABSTENTION", "OUTCOME_SUCCESS",
]
