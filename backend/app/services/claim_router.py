"""Phase 23.11 Claim Router (pure function).

Routes claims to one of 8 evidence retrieval paths:
STRUCTURED_NUMERIC | TABLE_METRIC | PERIOD_COMPARISON | SCOPE_VALIDATION
| NARRATIVE_FACT | CAUSALITY | FORECAST | INSUFFICIENTLY_PARSED

Pure: no DB, no I/O, no side effects. Tunable thresholds only via
leave-one-company-out cross-validation (never claim-specific).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

RouteType = Literal[
    "STRUCTURED_NUMERIC",
    "TABLE_METRIC",
    "PERIOD_COMPARISON",
    "SCOPE_VALIDATION",
    "NARRATIVE_FACT",
    "CAUSALITY",
    "FORECAST",
    "INSUFFICIENTLY_PARSED",
]

# Causal markers (must appear to pass CAUSALITY gate)
CAUSAL_MARKERS: tuple[str, ...] = (
    "导致", "推动", "主要由于", "主要系", "得益于", "带动",
    "attributable to", "driven by", "resulted from",
)
# Forecast markers (must appear to pass FORECAST gate)
FORECAST_MARKERS: tuple[str, ...] = (
    "预计", "指引", "目标", "管理层判断", "计划",
    "forecast", "guidance", "expect", "aim",
)
# Period comparison markers
PERIOD_COMPARISON_MARKERS: tuple[str, ...] = (
    "同比", "环比", "较上年", "较去年同期", "上年同期",
)
# Scope markers
SCOPE_MARKERS: tuple[str, ...] = (
    "归母", "归属于上市公司股东", "扣非", "扣除非经常性损益",
    "少数股东", "合并",
)

# Metric codes that prefer structured fact index
STRUCTURED_METRIC_CODES: frozenset[str] = frozenset({
    "revenue", "net_profit", "operating_cash_flow", "eps", "gross_margin",
    "net_margin", "total_assets", "net_assets", "roe", "roa", "debt_ratio",
})
# Metric codes that prefer table cell extraction
TABLE_METRIC_CODES: frozenset[str] = frozenset({
    "eps", "bps", "gross_margin", "net_margin", "roe", "roa", "debt_ratio",
})


@dataclass
class ClaimRoutingResult:
    """Result of routing a claim to one of 8 evidence retrieval paths."""

    claim_id: str
    claim_type: str
    entity: str
    metric: str
    metric_code: str
    value: float | None
    period: str
    unit: str
    scope: str
    direction: str
    route: RouteType
    route_confidence: float
    required_evidence_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "claim_type": self.claim_type,
            "entity": self.entity,
            "metric": self.metric,
            "metric_code": self.metric_code,
            "value": self.value,
            "period": self.period,
            "unit": self.unit,
            "scope": self.scope,
            "direction": self.direction,
            "route": self.route,
            "route_confidence": round(self.route_confidence, 3),
            "required_evidence_fields": self.required_evidence_fields,
        }


def _direction_of(text: str) -> str:
    if any(k in text for k in ("超过", "高于", "大于", "突破", "以上")):
        return ">="
    if any(k in text for k in ("低于", "小于", "以下", "不超过")):
        return "<="
    return "=="


def route_claim(claim: dict) -> ClaimRoutingResult:
    """Pure routing: claim dict -> ClaimRoutingResult (8 routes).

    Routing order (most specific first):
    1. CAUSALITY: causal language present
    2. FORECAST: forecast language present
    3. PERIOD_COMPARISON: comparison markers or growth_rate claim
    4. SCOPE_VALIDATION: scope markers present or non-default scope
    5. TABLE_METRIC: metric prefers table cell extraction
    6. STRUCTURED_NUMERIC: structured metric codes with numeric value
    7. NARRATIVE_FACT: business fact / strategy without structured metric
    8. INSUFFICIENTLY_PARSED: nothing matched (fallback)
    """
    cid = str(claim.get("claim_id") or claim.get("claim_uid") or "?")
    claim_type = str(claim.get("claim_type") or "").upper()
    entity = str(claim.get("entity") or claim.get("entity_name") or "").strip()
    metric = str(claim.get("metric") or "").strip()
    metric_code = str(claim.get("metric_code") or metric or "").strip()
    period = str(claim.get("period") or "").strip()
    unit = str(claim.get("unit") or "").strip()
    scope = str(claim.get("scope") or "consolidated").strip()
    value = (
        claim.get("value")
        if isinstance(claim.get("value"), (int, float))
        else None
    )
    text = str(
        claim.get("original_text") or claim.get("source_text") or ""
    ).strip()
    direction = _direction_of(text)

    # 1) CAUSALITY: causal language present
    if any(m in text for m in CAUSAL_MARKERS):
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "CAUSALITY", 0.85,
            ["causal_language", "metric", "entity"],
        )

    # 2) FORECAST: forecast language present
    if any(m in text for m in FORECAST_MARKERS):
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "FORECAST", 0.85,
            ["forecast_marker", "metric", "period"],
        )

    # 3) PERIOD_COMPARISON: comparison markers or growth_rate claim
    has_comparison = any(m in text for m in PERIOD_COMPARISON_MARKERS)
    is_growth = claim_type in ("GROWTH_RATE", "GROWTH_RATE_CHECK")
    if has_comparison or is_growth:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "PERIOD_COMPARISON", 0.8,
            ["current_period", "comparison_period", "metric", "unit"],
        )

    # 4) SCOPE_VALIDATION: scope markers present or non-default scope
    has_scope = any(m in text for m in SCOPE_MARKERS)
    if has_scope or scope in (
        "parent_attributable", "adjusted", "non_controlling_interest",
    ):
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "SCOPE_VALIDATION", 0.8,
            ["scope", "metric", "period", "unit"],
        )

    # 5) TABLE_METRIC: metric prefers table cell extraction
    if metric_code in TABLE_METRIC_CODES:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "TABLE_METRIC", 0.8,
            ["row_header", "column_header", "period_header",
             "unit_header", "cell_value"],
        )

    # 6) STRUCTURED_NUMERIC: structured metric codes with numeric value
    if metric_code in STRUCTURED_METRIC_CODES and value is not None:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "STRUCTURED_NUMERIC", 0.85,
            ["metric", "value", "period", "unit", "scope"],
        )

    # 7) NARRATIVE_FACT: business fact / strategy without structured metric
    if claim_type in ("BUSINESS_FACT", "STRATEGY", "SEMANTIC_CHECK"):
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "NARRATIVE_FACT", 0.75,
            ["entity", "keywords", "section"],
        )

    # 8) Fallback: STRUCTURED_NUMERIC if numeric value present
    if value is not None and metric_code:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "STRUCTURED_NUMERIC", 0.6,
            ["metric", "value", "period", "unit"],
        )

    # INSUFFICIENTLY_PARSED: nothing matched
    return ClaimRoutingResult(
        cid, claim_type, entity, metric, metric_code, value, period, unit,
        scope, direction, "INSUFFICIENTLY_PARSED", 0.3,
        ["entity", "keywords"],
    )


__all__ = [
    "route_claim", "ClaimRoutingResult", "RouteType",
    "CAUSAL_MARKERS", "FORECAST_MARKERS",
    "PERIOD_COMPARISON_MARKERS", "SCOPE_MARKERS",
    "STRUCTURED_METRIC_CODES", "TABLE_METRIC_CODES",
]
