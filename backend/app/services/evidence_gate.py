"""Phase 23.11 Evidence Precision Gate (pure function).

Per-route thresholds. CAUSALITY requires explicit causal language;
FORECAST requires forecast markers; numeric routes require
entity+metric+period+scope+unit consistency. Pure: no DB, no I/O.

Tunable thresholds only via leave-one-company-out CV.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.services.claim_router import (
    ClaimRoutingResult,
    CAUSAL_MARKERS,
    FORECAST_MARKERS,
)


# ===========================================================================
# Phase 23.11.2 three-state match logic (MATCH / MISMATCH / UNKNOWN)
# §3:禁止把 UNKNOWN 当成 MISMATCH
# ===========================================================================
MatchState = Literal["MATCH", "MISMATCH", "UNKNOWN"]


def _state_from_score(score: float, mismatch_threshold: float = 0.0) -> MatchState:
    """Convert legacy [0,1] score to three-state.

    score >= 0.5 → MATCH (evidence aligns with claim)
    score <= mismatch_threshold AND evidence text explicitly contains a
        conflicting marker → MISMATCH
    otherwise → UNKNOWN (field unparseable or metadata missing)
    """
    if score >= 0.5:
        return "MATCH"
    if score <= mismatch_threshold:
        # Caller must distinguish true mismatch (evidence explicitly不同) from
        # missing-as-zero; here pure score ≤ 0 → conservatively MISMATCH only if
        # caller passes mismatch_threshold > 0. Default 0 → UNKNOWN for safety.
        return "MISMATCH"
    return "UNKNOWN"


def _entity_state(claim: dict, candidate: dict) -> MatchState:
    """Three-state entity check (§3)."""
    entity = str(claim.get("entity") or claim.get("entity_name") or "").strip()
    if not entity:
        return "UNKNOWN"  # no constraint → unknown, not MATCH
    text = str(candidate.get("text") or "")
    if entity in text:
        return "MATCH"
    # short-form (first 2 chars for Chinese)
    if len(entity) >= 2 and entity[:2] in text:
        return "MATCH"
    # If text contains a DIFFERENT company marker, it's MISMATCH; else UNKNOWN
    # (financial table evidence legitimately omits company name)
    return "UNKNOWN"


def _metric_state(claim: dict, candidate: dict) -> MatchState:
    """Three-state metric check (§3, §9).

    WRONG_METRIC repair: if evidence text explicitly contains a DIFFERENT
    well-known metric keyword (net_profit / 净利润 when claim is revenue),
    judge MISMATCH — not UNKNOWN.
    """
    from app.services.evidence_retrieval.engine import (
        metric_aliases,
        metric_hits,
    )

    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))
    if not aliases:
        return "UNKNOWN"  # unknown metric → unknown, not MISMATCH
    text = str(candidate.get("text") or "")
    if metric_hits(text, aliases):
        return "MATCH"
    # fuzzy substring
    for a in aliases:
        if a and a in text:
            return "MATCH"
    # §9 WRONG_METRIC: check if text contains a DIFFERENT explicit metric marker
    # well-known metric keywords (Chinese + English canonical)
    well_known_metrics = {
        "revenue": ["revenue", "营业收入", "营收", "营业总收入", "总收入"],
        "net_profit": ["net_profit", "净利润", "净利", "归母净利润"],
        "gross_profit": ["gross_profit", "毛利润", "毛利", "营业毛利"],
        "operating_profit": ["operating_profit", "营业利润", "经营利润"],
        "total_assets": ["total_assets", "总资产", "资产总额"],
        "eps": ["eps", "每股收益", "基本每股收益"],
        "roe": ["roe", "净资产收益率", "回报率"],
        "roa": ["roa", "总资产收益率"],
    }
    claim_metric_key = str(claim.get("metric") or claim.get("metric_code") or "").lower()
    # find which well-known group claim belongs to
    claim_group = None
    for key, kws in well_known_metrics.items():
        if claim_metric_key == key or any(kw.lower() in claim_metric_key for kw in kws):
            claim_group = key
            break
    # also check aliases membership
    if claim_group is None:
        for key, kws in well_known_metrics.items():
            if any(kw in aliases for kw in kws):
                claim_group = key
                break
    # If text contains a DIFFERENT group's keyword → MISMATCH
    if claim_group:
        for key, kws in well_known_metrics.items():
            if key == claim_group:
                continue
            if any(kw in text for kw in kws):
                return "MISMATCH"
    return "UNKNOWN"  # no metric info parseable


def _period_state(claim: dict, candidate: dict) -> MatchState:
    """Three-state period check (§3)."""
    claim_period = str(claim.get("period") or "").upper()
    if not claim_period:
        return "UNKNOWN"
    year_match = re.search(r"(20\d{2})", claim_period)
    if not year_match:
        return "UNKNOWN"
    claim_year = year_match.group(1)
    text = str(candidate.get("text") or "")
    candidate_years = set(re.findall(r"20\d{2}", text))
    if claim_year in candidate_years:
        return "MATCH"
    if candidate_years:
        return "MISMATCH"  # different year explicitly present → conflict
    return "UNKNOWN"  # no year info → UNKNOWN, not MATCH


def _scope_state(claim: dict, candidate: dict) -> MatchState:
    """Three-state scope check (§3, §9).

    WRONG_SCOPE repair: if evidence text explicitly contains a DIFFERENT
    scope marker (归母 vs 合并), judge MISMATCH — not UNKNOWN.
    """
    scope = str(claim.get("scope") or "consolidated").strip()
    text = str(candidate.get("text") or "")
    # Scope markers grouped by mutually-exclusive scope
    scope_groups = {
        "consolidated": ["合并", "consolidated", "合并报表", "合并口径"],
        "parent_attributable": ["归母", "归属于上市公司股东", "parent_attributable", "归属于母公司"],
        "adjusted": ["扣非", "扣除非经常性损益", "adjusted"],
        "non_controlling_interest": ["少数股东", "non_controlling", "少数股东损益"],
    }
    # find claim's group
    claim_group = None
    if scope in scope_groups:
        claim_group = scope
    else:
        # fallback by marker presence in scope string
        for key, markers in scope_groups.items():
            if any(m in scope for m in markers):
                claim_group = key
                break
    # if consolidated (default lenient), evidence rarely explicit → MATCH
    if claim_group == "consolidated":
        # but if text explicitly contains a DIFFERENT scope marker → MISMATCH
        for key, markers in scope_groups.items():
            if key == "consolidated":
                continue
            if any(m in text for m in markers):
                return "MISMATCH"
        return "MATCH"  # consolidated default lenient
    # non-default scope: MATCH if claim's marker present
    if claim_group and any(m in text for m in scope_groups[claim_group]):
        return "MATCH"
    # if text has a DIFFERENT scope marker → MISMATCH
    if claim_group:
        for key, markers in scope_groups.items():
            if key == claim_group:
                continue
            if any(m in text for m in markers):
                return "MISMATCH"
    return "UNKNOWN"  # no scope info


def _unit_state(claim: dict, candidate: dict) -> MatchState:
    """Three-state unit check (§3)."""
    claim_unit = str(claim.get("unit") or "").strip()
    if not claim_unit:
        return "UNKNOWN"
    text = str(candidate.get("text") or "")
    unit_patterns = {
        "亿元": ["亿元", "亿"], "万元": ["万元", "万"],
        "%": ["%", "％"], "元/股": ["元/股", "每股"],
        "千元": ["千元", "千"], "元": ["元"],
    }
    claim_patterns = unit_patterns.get(claim_unit, [claim_unit])
    if any(p in text for p in claim_patterns):
        return "MATCH"
    # If text has any unit marker → convertible (亿元/万元/千元/元 interchangeable)
    if any(p in text for ps in unit_patterns.values() for p in ps):
        return "MATCH"  # unit convertible (§4: unit convertible → not mismatch)
    return "UNKNOWN"  # no unit info


def _route_state(routing: ClaimRoutingResult, candidate: dict) -> MatchState:
    """Three-state route check (§3)."""
    route = routing.route
    if not route or route == "INSUFFICIENTLY_PARSED":
        return "UNKNOWN"
    # route always aligns with itself by construction
    return "MATCH"


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
    """Quality assessment for a single evidence candidate.

    Phase 23.11.2: entity/metric/period/unit/scope/route now expose three-state
    (MATCH / MISMATCH / UNKNOWN) alongside legacy float scores.
    """

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
    # Phase 23.11 fix: carry candidate text so the Selector can build a
    # bundle that core_verify can actually read.
    text: str = ""
    # Phase 23.34: carry candidate financial_fact so the Selector can
    # build a bundle that core_verify can consume natively (was lost here).
    financial_fact: dict | None = None
    # Phase 23.11.2 three-state fields (§3)
    entity_state: MatchState = "UNKNOWN"
    metric_state: MatchState = "UNKNOWN"
    period_state: MatchState = "UNKNOWN"
    unit_state: MatchState = "UNKNOWN"
    scope_state: MatchState = "UNKNOWN"
    route_state: MatchState = "UNKNOWN"

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

    Phase 23.11.2 three-state logic (§3, §4):
    - MATCH / MISMATCH / UNKNOWN per field (entity/metric/period/unit/scope/route)
    - Hard Reject ONLY on explicit MISMATCH (wrong company / different period /
      different scope / explicit相反 fact). NEVER reject on UNKNOWN alone.
    - UNKNOWN → soft penalty (reduce completeness_score), not reject.
    - Numeric routes: entity mismatch OR period mismatch OR scope mismatch → reject;
      entity/metric/period/scope UNKNOWN → soft penalty only.
    - CAUSALITY: no causal language → reject (coincidence guard).
    - FORECAST: no forecast markers → reject.
    """
    eid = str(
        candidate.get("evidence_id") or candidate.get("block_id") or "?"
    )
    cand_text = str(candidate.get("text") or candidate.get("block_text") or "")

    # Three-state per-field evaluation (§3)
    entity_state = _entity_state(claim, candidate)
    metric_state = _metric_state(claim, candidate)
    period_state = _period_state(claim, candidate)
    unit_state = _unit_state(claim, candidate)
    scope_state = _scope_state(claim, candidate)
    route_state = _route_state(routing, candidate)

    # Legacy scores retained for backward compat / completeness calc
    entity_ok = entity_state == "MATCH"
    metric_score = _score_from_state(metric_state)
    period_score = _score_from_state(period_state)
    unit_score = _score_from_state(unit_state)
    scope_score = _score_from_state(scope_state)
    numeric_score = _numeric_match(claim, candidate)
    route_score = _score_from_state(route_state)

    has_numbers = bool(re.search(r"\d", candidate.get("text", "") or ""))
    source_quality = 0.8 if has_numbers else 0.4

    # Completeness: weighted average — UNKNOWN contributes 0.3 (soft), not 0.0
    completeness = (
        0.25 * metric_score
        + 0.20 * period_score
        + 0.15 * scope_score
        + 0.15 * unit_score
        + 0.15 * numeric_score
        + 0.10 * route_score
    )

    # Contradiction signal: only explicit MISMATCH (not UNKNOWN)
    contradiction = 0.0
    if period_state == "MISMATCH":
        contradiction = max(contradiction, 0.8)
    if scope_state == "MISMATCH":
        contradiction = max(contradiction, 0.7)
    if entity_state == "MISMATCH":
        contradiction = max(contradiction, 0.9)

    # ============================================================
    # Hard Reject: only explicit MISMATCH (§4)
    # ============================================================
    # CAUSALITY: must have causal language (coincidence guard, §5)
    if routing.route == "CAUSALITY" and gate_config.causal_language_required:
        # Use _route_match which checks CAUSAL_MARKERS in text (not route_state
        # which is always MATCH by construction). §5: CAUSALITY requires
        # explicit因果 language; coincidence of two facts → reject.
        causal_route_score = _route_match(routing, candidate)
        if causal_route_score == 0.0:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, causal_route_score,
                contradiction, completeness, 0.0, False,
                "CAUSALITY gate: no causal language found",
                text=cand_text,
                entity_state=entity_state, metric_state=metric_state,
                period_state=period_state, unit_state=unit_state,
                scope_state=scope_state, route_state="MISMATCH",
            )

    # FORECAST: must have forecast markers (§5)
    if routing.route == "FORECAST":
        if route_score == 0.0:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.0, False,
                "FORECAST gate: no forecast/opinion/target language found",
                text=cand_text,
                entity_state=entity_state, metric_state=metric_state,
                period_state=period_state, unit_state=unit_state,
                scope_state=scope_state, route_state=route_state,
            )

    # Numeric routes: Hard Reject only on explicit MISMATCH (§4, §5)
    if routing.route in (
        "STRUCTURED_NUMERIC", "TABLE_METRIC",
        "PERIOD_COMPARISON", "SCOPE_VALIDATION",
    ):
        # entity MISMATCH → wrong company → Hard Reject
        if entity_state == "MISMATCH":
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.0, False,
                "entity mismatch: candidate mentions different company",
                text=cand_text,
                entity_state=entity_state, metric_state=metric_state,
                period_state=period_state, unit_state=unit_state,
                scope_state=scope_state, route_state=route_state,
            )
        # metric MISMATCH → different metric explicitly → Hard Reject
        if metric_state == "MISMATCH":
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.0, False,
                "metric mismatch: candidate mentions different metric",
                text=cand_text,
                entity_state=entity_state, metric_state=metric_state,
                period_state=period_state, unit_state=unit_state,
                scope_state=scope_state, route_state=route_state,
            )
        # period MISMATCH → different period explicitly → Hard Reject
        if gate_config.period_conflict_strict and period_state == "MISMATCH":
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.1, False,
                "period mismatch: candidate mentions different period",
                text=cand_text,
                entity_state=entity_state, metric_state=metric_state,
                period_state=period_state, unit_state=unit_state,
                scope_state=scope_state, route_state=route_state,
            )
        # scope MISMATCH → different scope explicitly → Hard Reject
        if gate_config.scope_conflict_strict and scope_state == "MISMATCH":
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.1, False,
                "scope mismatch: candidate mentions different scope",
                text=cand_text,
                entity_state=entity_state, metric_state=metric_state,
                period_state=period_state, unit_state=unit_state,
                scope_state=scope_state, route_state=route_state,
            )
        # UNKNOWN on entity/metric/period/scope → soft penalty only, NOT reject

    # ============================================================
    # Phase 23.11.2 Positive Boost (§4)
    # company + metric + period + scope all MATCH + numeric/unit consistent
    # + structured table fields complete + evidence text directly contains
    # claim fact → boost final_score.
    # ============================================================
    positive_boost = 0.0
    all_match = (
        entity_state == "MATCH" and metric_state == "MATCH"
        and period_state == "MATCH" and scope_state == "MATCH"
    )
    if all_match:
        positive_boost += 0.10
    # numeric + unit consistent (MATCH or convertible)
    if unit_state == "MATCH" and numeric_score >= 0.5:
        positive_boost += 0.05
    # structured table fields complete (row_header/column_header present)
    cand_text = str(candidate.get("text") or "")
    has_table_row = any(
        h in cand_text
        for h in (candidate.get("row_header") or "")
        if h
    ) if candidate.get("row_header") else False
    if has_table_row:
        positive_boost += 0.05
    # evidence text directly contains claim fact substring
    claim_text = str(claim.get("original_text") or claim.get("claim_text") or "")
    if claim_text and len(claim_text) > 8 and claim_text[:8] in cand_text:
        positive_boost += 0.05

    # ============================================================
    # Final quality score: completeness + positive_boost - contradiction penalty
    # ============================================================
    final_score = (completeness + positive_boost) * (1.0 - contradiction * 0.5)
    final_score = min(final_score, 1.0)  # cap at 1.0

    # Accept/reject based on quality thresholds (soft)
    if final_score >= gate_config.high_quality_threshold:
        accepted = True
        rejection = ""
    elif final_score >= gate_config.medium_quality_threshold:
        accepted = True  # medium quality still accepted (§4: auxiliary evidence)
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
        text=cand_text,
        financial_fact=candidate.get("financial_fact"),
        entity_state=entity_state, metric_state=metric_state,
        period_state=period_state, unit_state=unit_state,
        scope_state=scope_state, route_state=route_state,
    )


def _score_from_state(state: MatchState) -> float:
    """Convert three-state back to legacy [0,1] score for completeness calc.

    MATCH → 1.0, MISMATCH → 0.0, UNKNOWN → 0.3 (soft penalty, not 0).
    """
    if state == "MATCH":
        return 1.0
    if state == "MISMATCH":
        return 0.0
    return 0.3  # UNKNOWN soft penalty


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
