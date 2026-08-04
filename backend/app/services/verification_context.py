"""Phase 23.11 VerificationContext.

Carries gate_config, selector_config, evidence_source, and trace.
Shared by CORE_ORACLE, NOISY_ORACLE, REAL_E2E.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.services.evidence_gate import GateConfig
from app.services.evidence_selector import SelectorConfig


@dataclass
class VerificationContext:
    """Context shared by all three verification modes.

    evidence_source: "core_oracle" | "noisy_oracle" | "real_e2e"
    gate_config: Gate thresholds (tuned via leave-one-company-out CV)
    selector_config: Selector thresholds (Top1/Top3/Top5, ambiguity_margin)
    trace: IntegrationTrace, set by verify_evidence_set if None
    candidates_before_gate: count of evidence candidates fed to gate
    candidates_after_gate: count of evidence candidates accepted by gate
    """

    evidence_source: Literal["core_oracle", "noisy_oracle", "real_e2e"]
    gate_config: GateConfig = field(default_factory=GateConfig)
    selector_config: SelectorConfig = field(default_factory=SelectorConfig)
    trace: object | None = None  # IntegrationTrace, set by verify_evidence_set
    candidates_before_gate: int = 0
    candidates_after_gate: int = 0


__all__ = ["VerificationContext"]
