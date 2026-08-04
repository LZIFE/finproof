"""Phase 23.11 Claim Router tests (Task 2).

Tests all 8 route types + edge cases. Pure function: no DB, no I/O.
"""
from app.services.claim_router import (
    route_claim, ClaimRoutingResult, RouteType,
    CAUSAL_MARKERS, FORECAST_MARKERS,
)


def test_structured_numeric_route():
    claim = {"claim_id": "CLM-001", "entity": "五粮液", "metric": "营业收入",
             "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "value": 931.8, "original_text": "五粮液2025年营业收入931.8亿元"}
    r = route_claim(claim)
    assert isinstance(r, ClaimRoutingResult)
    assert r.entity == "五粮液"
    assert r.route_confidence >= 0.7
    assert "metric" in r.required_evidence_fields or "value" in r.required_evidence_fields


def test_period_comparison_route():
    claim = {"claim_id": "CLM-002", "metric_code": "revenue_growth",
             "claim_type": "GROWTH_RATE", "period": "2025FY",
             "original_text": "2025年营业收入同比增长12%"}
    r = route_claim(claim)
    assert r.route == "PERIOD_COMPARISON"


def test_causality_route():
    claim = {"claim_id": "CLM-003", "claim_type": "BUSINESS_FACT",
             "original_text": "毛利率下降主要由于原材料成本上升"}
    r = route_claim(claim)
    assert r.route == "CAUSALITY"
    assert "causal_language" in r.required_evidence_fields


def test_forecast_route():
    claim = {"claim_id": "CLM-004", "claim_type": "BUSINESS_FACT",
             "original_text": "公司预计2026年营收将增长15%"}
    r = route_claim(claim)
    assert r.route == "FORECAST"


def test_narrative_fact_route():
    claim = {"claim_id": "CLM-005", "claim_type": "BUSINESS_FACT",
             "metric_code": "overseas_obm_strategy",
             "original_text": "公司持续推进海外OBM战略"}
    r = route_claim(claim)
    assert r.route == "NARRATIVE_FACT"


def test_scope_validation_route():
    claim = {"claim_id": "CLM-006", "claim_type": "NUMERIC_VALUE",
             "scope": "parent_attributable", "metric_code": "net_profit",
             "period": "2025FY", "unit": "亿元", "value": 317.9,
             "original_text": "归母净利润317.9亿元"}
    r = route_claim(claim)
    assert r.route == "SCOPE_VALIDATION"


def test_table_metric_route():
    claim = {"claim_id": "CLM-007", "claim_type": "NUMERIC_VALUE",
             "metric_code": "eps", "period": "2025FY",
             "unit": "元/股", "value": 8.18,
             "original_text": "基本每股收益8.18元"}
    r = route_claim(claim)
    assert r.route in ("TABLE_METRIC", "STRUCTURED_NUMERIC")


def test_insufficiently_parsed_route():
    claim = {"claim_id": "CLM-008", "claim_type": "",
             "original_text": "公司表现良好"}
    r = route_claim(claim)
    assert r.route == "INSUFFICIENTLY_PARSED"


def test_routing_result_is_dataclass():
    claim = {"claim_id": "CLM-009", "claim_type": "NUMERIC_VALUE",
             "metric_code": "revenue", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    r = route_claim(claim)
    assert isinstance(r, ClaimRoutingResult)
    assert hasattr(r, "route_confidence")


def test_to_dict_serialization():
    claim = {"claim_id": "CLM-010", "entity": "美的",
             "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "value": 100,
             "original_text": "营收100亿"}
    r = route_claim(claim)
    d = r.to_dict()
    assert d["claim_id"] == "CLM-010"
    assert "route" in d
    assert "route_confidence" in d


def test_all_routes_are_valid_literals():
    """Every route returned must be one of the 8 valid RouteType values."""
    valid_routes = {
        "STRUCTURED_NUMERIC", "TABLE_METRIC", "PERIOD_COMPARISON",
        "SCOPE_VALIDATION", "NARRATIVE_FACT", "CAUSALITY", "FORECAST",
        "INSUFFICIENTLY_PARSED",
    }
    test_claims = [
        {"claim_id": "T1", "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
         "period": "2025FY", "unit": "亿元", "value": 100, "original_text": "营收100亿"},
        {"claim_id": "T2", "claim_type": "", "original_text": "无关文本"},
        {"claim_id": "T3", "claim_type": "BUSINESS_FACT",
         "original_text": "毛利率下降主要由于成本上升"},
        {"claim_id": "T4", "claim_type": "BUSINESS_FACT",
         "original_text": "公司预计2026年增长15%"},
    ]
    for c in test_claims:
        r = route_claim(c)
        assert r.route in valid_routes, f"invalid route {r.route}"


def test_causal_markers_nonempty():
    assert len(CAUSAL_MARKERS) > 0
    assert all(isinstance(m, str) for m in CAUSAL_MARKERS)


def test_forecast_markers_nonempty():
    assert len(FORECAST_MARKERS) > 0
    assert all(isinstance(m, str) for m in FORECAST_MARKERS)
