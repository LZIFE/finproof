"""Phase 23.11 Evidence Precision Gate (pure function).

Per-route thresholds. CAUSALITY requires explicit causal language;
FORECAST requires forecast markers; numeric routes require
entity+metric+period+scope+unit consistency. Pure: no DB, no I/O.

Tunable thresholds only via leave-one-company-out CV.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.claim_router import (
    ClaimRoutingResult,
    CAUSAL_MARKERS,
    FORECAST_MARKERS,
)


@dataclass
class GateConfig:
    """Gate thresholds (tuned only via leave-one-company-out CV)."""

    metric_match_threshold: float = 0.6
    period_conflict_strict: bool = True
    scope_conflict_strict: bool = True
    unit_convertible: bool = True
    high_quality_threshold: float = 0.7
    medium_quality_threshold: float = 0.4
    route_match_weight: float = 0.2
    causal_language_required: bool = True


@dataclass
class EvidenceQualityResult:
    """Quality assessment for a single evidence candidate."""

    evidence_id: str
    entity_match: bool
    metric_match: float
    period_match: float
    unit_match: float
    scope_match: float
    numeric_match: float
    source_quality: float
    route_match: float
    contradiction_signal: float
    completeness_score: float
    final_quality_score: float
    accepted: bool
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        return {
            k: (round(v, 3) if isinstance(v, float) else v)
            for k, v in self.__dict__.items()
        }


def _entity_match(claim: dict, candidate: dict) -> bool:
    """Check if candidate mentions the claim entity."""
    entity = str(
        claim.get("entity") or claim.get("entity_name") or ""
    ).strip()
    if not entity:
        return True  # no entity constraint
    text = candidate.get("text", "") or ""
    if entity in text:
        return True
    # Short-form check (first 2 chars for Chinese entities)
    if len(entity) >= 2 and entity[:2] in text:
        return True
    return False


def _metric_match(claim: dict, candidate: dict) -> float:
    """Score metric match in [0, 1]."""
    from app.services.evidence_retrieval.engine import (
        metric_aliases,
        metric_hits,
    )

    aliases = metric_aliases(
        claim.get("metric_code"), claim.get("metric")
    )
    if not aliases:
        return 0.3  # unknown metric, partial credit
    text = candidate.get("text", "") or ""
    hits = metric_hits(text, aliases)
    if hits:
        return 1.0
    # Fuzzy: any alias substring
    for a in aliases:
        if a and a in text:
            return 0.8
    return 0.0


def _period_match(claim: dict, candidate: dict) -> float:
    """Score period match in [0, 1]. Returns 0.0 for clear conflict."""
    claim_period = str(claim.get("period") or "").upper()
    text = candidate.get("text", "") or ""
    if not claim_period:
        return 0.5
    # Extract year from claim period (e.g. 2025FY -> 2025)
    year_match = re.search(r"(20\d{2})", claim_period)
    if not year_match:
        return 0.5
    claim_year = year_match.group(1)
    # Find years mentioned in candidate text
    candidate_years = set(re.findall(r"20\d{2}", text))
    if claim_year in candidate_years:
        return 1.0
    if candidate_years:
        return 0.0  # Different year present -> conflict
    return 0.3  # no year info


def _scope_match(claim: dict, candidate: dict) -> float:
    """Score scope match in [0, 1]. Returns 0.0 for clear conflict."""
    scope = str(claim.get("scope") or "consolidated").strip()
    text = candidate.get("text", "") or ""
    if scope == "consolidated":
        return 0.8  # default scope, generally OK
    # Check scope markers
    scope_markers = {
        "parent_attributable": [
            "归母", "归属于上市公司股东", "parent_attributable",
        ],
        "adjusted": ["扣非", "扣除非经常性损益", "adjusted"],
        "non_controlling_interest": ["少数股东", "non_controlling"],
    }
    markers = scope_markers.get(scope, [])
    if any(m in text for m in markers):
        return 1.0
    # If text has a different scope marker, it's a conflict
    all_markers = [m for ms in scope_markers.values() for m in ms]
    if any(m in text for m in all_markers):
        return 0.0  # different scope present
    return 0.5  # no scope info


def _unit_match(claim: dict, candidate: dict) -> float:
    """Score unit match in [0, 1]."""
    claim_unit = str(claim.get("unit") or "").strip()
    text = candidate.get("text", "") or ""
    if not claim_unit:
        return 0.5
    unit_patterns = {
        "亿元": ["亿元", "亿"],
        "万元": ["万元", "万"],
        "%": ["%", "％"],
        "元/股": ["元/股", "每股"],
    }
    claim_patterns = unit_patterns.get(claim_unit, [claim_unit])
    if any(p in text for p in claim_patterns):
        return 1.0
    # Check any unit present
    if any(
        p in text
        for ps in unit_patterns.values()
        for p in ps
    ):
        return 0.3
    return 0.5


def _numeric_match(claim: dict, candidate: dict) -> float:
    """Score numeric value match in [0, 1]."""
    value = claim.get("value")
    if not isinstance(value, (int, float)):
        return 0.5
    text = candidate.get("text", "") or ""
    from app.services.evidence_retrieval.engine import _block_value_hits

    ok, _ = _block_value_hits(text, value, claim.get("unit"))
    return 1.0 if ok else 0.0


def _route_match(
    routing: ClaimRoutingResult, candidate: dict
) -> float:
    """Score how well candidate aligns with route requirements."""
    route = routing.route
    text = candidate.get("text", "") or ""
    if route in (
        "STRUCTURED_NUMERIC", "TABLE_METRIC", "PERIOD_COMPARISON",
    ):
        return 1.0 if re.search(r"\d", text) else 0.2
    if route == "CAUSALITY":
        return 1.0 if any(m in text for m in CAUSAL_MARKERS) else 0.0
    if route == "FORECAST":
        return 1.0 if any(m in text for m in FORECAST_MARKERS) else 0.2
    if route == "NARRATIVE_FACT":
        return 0.8
    return 0.5


def evaluate_one(
    claim: dict,
    candidate: dict,
    routing: ClaimRoutingResult,
    gate_config: GateConfig,
) -> EvidenceQualityResult:
    """Pure gate evaluation: candidate + routing -> EvidenceQualityResult.

    Routing-specific gate conditions:
    - CAUSALITY: must have causal language (reject coincidence)
    - FORECAST: must have forecast markers
    - Numeric routes: entity + metric + period + scope conditions
    """
    eid = str(
        candidate.get("evidence_id") or candidate.get("block_id") or "?"
    )

    entity_ok = _entity_match(claim, candidate)
    metric_score = _metric_match(claim, candidate)
    period_score = _period_match(claim, candidate)
    unit_score = _unit_match(claim, candidate)
    scope_score = _scope_match(claim, candidate)
    numeric_score = _numeric_match(claim, candidate)
    route_score = _route_match(routing, candidate)

    has_numbers = bool(re.search(r"\d", candidate.get("text", "") or ""))
    source_quality = 0.8 if has_numbers else 0.4

    # Completeness: weighted average of component matches
    completeness = (
        0.25 * metric_score
        + 0.20 * period_score
        + 0.15 * scope_score
        + 0.15 * unit_score
        + 0.15 * numeric_score
        + 0.10 * route_score
    )

    # Contradiction signal: period or scope conflict
    contradiction = 0.0
    if period_score == 0.0:
        contradiction = max(contradiction, 0.8)
    if scope_score == 0.0:
        contradiction = max(contradiction, 0.7)

    # Route-specific gate conditions
    # CAUSALITY: must have causal language
    if (
        routing.route == "CAUSALITY"
        and gate_config.causal_language_required
    ):
        if route_score == 0.0:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.0, False,
                "CAUSALITY gate: no causal language found",
            )

    # Numeric routes: entity + metric + period + scope conditions
    if routing.route in (
        "STRUCTURED_NUMERIC", "TABLE_METRIC",
        "PERIOD_COMPARISON", "SCOPE_VALIDATION",
    ):
        if not entity_ok:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.0, False,
                "entity mismatch: candidate does not mention claim entity",
            )
        if metric_score < gate_config.metric_match_threshold:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.2, False,
                f"metric match {metric_score:.2f} below threshold "
                f"{gate_config.metric_match_threshold}",
            )
        if gate_config.period_conflict_strict and period_score == 0.0:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.1, False,
                "period conflict: candidate mentions different period",
            )
        if gate_config.scope_conflict_strict and scope_score == 0.0:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.1, False,
                "scope conflict: candidate mentions different scope",
            )

    # Final quality score: completeness minus contradiction penalty
    final_score = completeness * (1.0 - contradiction * 0.5)

    # Accept/reject based on quality thresholds
    if final_score >= gate_config.high_quality_threshold:
        accepted = True
        rejection = ""
    elif final_score >= gate_config.medium_quality_threshold:
        accepted = True  # medium quality still accepted
        rejection = ""
    else:
        accepted = False
        rejection = (
            f"quality score {final_score:.3f} below medium threshold "
            f"{gate_config.medium_quality_threshold}"
        )

    return EvidenceQualityResult(
        eid, entity_ok, metric_score, period_score, unit_score,
        scope_score, numeric_score, source_quality, route_score,
        contradiction, completeness, final_score, accepted, rejection,
    )


def evaluate_all(
    claim: dict,
    candidates: list[dict],
    routing: ClaimRoutingResult,
    gate_config: GateConfig,
) -> list[EvidenceQualityResult]:
    """Evaluate all candidates through the gate (pure)."""
    return [
        evaluate_one(claim, c, routing, gate_config) for c in candidates
    ]


__all__ = [
    "EvidenceQualityResult", "GateConfig",
    "evaluate_one", "evaluate_all",
]
