"""Phase 23.11 EvidenceGate tests (Task 3).

Tests gate behavior for all route types, including wrong-period rejection,
wrong-scope rejection, causal language requirement, and pure coincidence
rejection.
"""
from app.services.claim_router import route_claim
from app.services.evidence_gate import (
    evaluate_one,
    evaluate_all,
    GateConfig,
    EvidenceQualityResult,
)


def test_numeric_gate_accepts_correct_evidence():
    claim = {
        "claim_id": "CLM-001", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "scope": "consolidated",
        "value": 931.8, "original_text": "五粮液2025年营业收入931.8亿元",
    }
    routing = route_claim(claim)
    candidate = {
        "evidence_id": "B1", "text": "五粮液 营业收入 931.8 亿元 2025年",
        "page": 5, "document_id": 1,
    }
    cfg = GateConfig()
    r = evaluate_one(claim, candidate, routing, cfg)
    assert isinstance(r, EvidenceQualityResult)
    assert r.accepted is True
    assert r.final_quality_score >= cfg.medium_quality_threshold


def test_gate_rejects_wrong_period():
    """Wrong-period evidence must be rejected."""
    claim = {
        "claim_id": "CLM-002", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "scope": "consolidated",
        "value": 931.8, "original_text": "2025年营收931.8亿",
    }
    routing = route_claim(claim)
    candidate = {
        "evidence_id": "B2", "text": "营业收入 800 亿元 2023年",
        "page": 5, "document_id": 1,
    }
    cfg = GateConfig()
    r = evaluate_one(claim, candidate, routing, cfg)
    assert r.accepted is False
    assert "period" in r.rejection_reason.lower() or r.period_match == 0.0


def test_gate_rejects_wrong_scope():
    """Wrong-scope evidence must be rejected."""
    claim = {
        "claim_id": "CLM-003", "entity": "五粮液",
        "metric_code": "net_profit", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "scope": "parent_attributable",
        "value": 317.9, "original_text": "归母净利润317.9亿元",
    }
    routing = route_claim(claim)
    candidate = {
        "evidence_id": "B3", "text": "少数股东损益 50 万元",
        "page": 10, "document_id": 1,
    }
    cfg = GateConfig()
    r = evaluate_one(claim, candidate, routing, cfg)
    assert r.accepted is False


def test_causal_gate_requires_causal_language():
    """CAUSALITY gate rejects evidence without causal language."""
    claim = {
        "claim_id": "CLM-004", "claim_type": "BUSINESS_FACT",
        "original_text": "毛利率下降主要由于原材料成本上升",
    }
    routing = route_claim(claim)
    candidate_no_causal = {
        "evidence_id": "B4", "text": "毛利率30% 营收100亿",
        "page": 5, "document_id": 1,
    }
    cfg = GateConfig()
    r = evaluate_one(claim, candidate_no_causal, routing, cfg)
    assert r.accepted is False
    assert "causal" in r.rejection_reason.lower()


def test_causal_gate_accepts_causal_language():
    """CAUSALITY gate accepts evidence with causal language."""
    claim = {
        "claim_id": "CLM-005", "claim_type": "BUSINESS_FACT",
        "original_text": "毛利率下降主要由于原材料成本上升",
    }
    routing = route_claim(claim)
    candidate_causal = {
        "evidence_id": "B5", "text": "毛利率下降主要由于原材料成本上升",
        "page": 5, "document_id": 1,
    }
    cfg = GateConfig()
    r = evaluate_one(claim, candidate_causal, routing, cfg)
    assert r.accepted is True


def test_evaluate_all_returns_list():
    """evaluate_all returns a list of EvidenceQualityResult."""
    claim = {
        "claim_id": "CLM-006", "entity": "美的",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 100,
        "original_text": "营收100亿",
    }
    routing = route_claim(claim)
    candidates = [
        {"evidence_id": "B1", "text": "营业收入 100 亿元", "page": 1, "document_id": 1},
        {"evidence_id": "B2", "text": "无关文本", "page": 2, "document_id": 1},
    ]
    cfg = GateConfig()
    results = evaluate_all(claim, candidates, routing, cfg)
    assert isinstance(results, list)
    assert len(results) == 2
    assert all(isinstance(r, EvidenceQualityResult) for r in results)


def test_gate_rejects_pure_coincidence_two_facts():
    """CAUSALITY gate rejects evidence with two facts but no causal language."""
    claim = {
        "claim_id": "CLM-007", "claim_type": "BUSINESS_FACT",
        "original_text": "毛利率下降主要由于原材料成本上升",
    }
    routing = route_claim(claim)
    candidate = {
        "evidence_id": "B6", "text": "毛利率30% 原材料成本50亿元",
        "page": 5, "document_id": 1,
    }
    cfg = GateConfig()
    r = evaluate_one(claim, candidate, routing, cfg)
    assert r.accepted is False


def test_gate_result_has_all_fields():
    """EvidenceQualityResult has all required fields."""
    claim = {"claim_id": "CLM-008", "entity": "美的",
             "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "value": 100,
             "original_text": "营收100亿"}
    routing = route_claim(claim)
    candidate = {"evidence_id": "B1", "text": "营业收入 100 亿元",
                 "page": 1, "document_id": 1}
    r = evaluate_one(claim, candidate, routing, GateConfig())
    required = ["evidence_id", "entity_match", "metric_match",
                "period_match", "unit_match", "scope_match",
                "numeric_match", "source_quality", "route_match",
                "contradiction_signal", "completeness_score",
                "final_quality_score", "accepted", "rejection_reason"]
    for f in required:
        assert hasattr(r, f), f"missing field {f}"


def test_to_dict_serialization():
    """EvidenceQualityResult.to_dict() works."""
    claim = {"claim_id": "CLM-009", "entity": "美的",
             "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "value": 100,
             "original_text": "营收100亿"}
    routing = route_claim(claim)
    candidate = {"evidence_id": "B1", "text": "营业收入 100 亿元",
                 "page": 1, "document_id": 1}
    r = evaluate_one(claim, candidate, routing, GateConfig())
    d = r.to_dict()
    assert "evidence_id" in d
    assert "final_quality_score" in d


def test_gate_config_defaults():
    """GateConfig has sensible defaults."""
    cfg = GateConfig()
    assert cfg.metric_match_threshold > 0
    assert cfg.high_quality_threshold > cfg.medium_quality_threshold
    assert cfg.causal_language_required is True
