"""Phase 23.11 EvidenceSelector tests (Task 5).

Tests Top1/Top3/Top5 strategies, ambiguity margin detection, empty results.
Pure function: no DB, no I/O.
"""
from app.services.claim_router import route_claim
from app.services.evidence_gate import EvidenceQualityResult
from app.services.evidence_selector import (
    select,
    SelectorConfig,
    SelectionResult,
)


def _qr(eid, score, accepted=True):
    """Helper: build an EvidenceQualityResult with uniform scores."""
    return EvidenceQualityResult(
        evidence_id=eid, entity_match=True, metric_match=score,
        period_match=score, unit_match=score, scope_match=score,
        numeric_match=score, source_quality=score, route_match=score,
        contradiction_signal=0.0, completeness_score=score,
        final_quality_score=score, accepted=accepted, rejection_reason="",
    )


def test_selector_top3_returns_max_3():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [_qr(f"B{i}", 0.8) for i in range(5)]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    selected, meta = select(gate_results, routing, cfg)
    assert isinstance(meta, SelectionResult)
    assert len(selected) <= 3
    assert meta.candidates_after_gate == 5


def test_selector_top1_strategy():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [_qr(f"B{i}", 0.9 - i * 0.1) for i in range(3)]
    cfg = SelectorConfig(strategy="Top1", max_evidence=1)
    selected, meta = select(gate_results, routing, cfg)
    assert len(selected) == 1
    assert meta.top1_quality >= 0.8


def test_selector_top5_strategy():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [_qr(f"B{i}", 0.8) for i in range(7)]
    cfg = SelectorConfig(strategy="Top5", max_evidence=5)
    selected, meta = select(gate_results, routing, cfg)
    assert len(selected) <= 5


def test_selector_flags_ambiguity_margin():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    # Two candidates with very close quality but different signals
    r1 = EvidenceQualityResult(
        evidence_id="B1", entity_match=True, metric_match=0.9,
        period_match=0.9, unit_match=0.9, scope_match=0.9,
        numeric_match=0.9, source_quality=0.9, route_match=0.9,
        contradiction_signal=0.0, completeness_score=0.9,
        final_quality_score=0.80, accepted=True, rejection_reason="",
    )
    r2 = EvidenceQualityResult(
        evidence_id="B2", entity_match=True, metric_match=0.5,
        period_match=0.5, unit_match=0.5, scope_match=0.5,
        numeric_match=0.5, source_quality=0.5, route_match=0.5,
        contradiction_signal=0.0, completeness_score=0.5,
        final_quality_score=0.79, accepted=True, rejection_reason="",
    )
    gate_results = [r1, r2]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3,
                         ambiguity_margin=0.05)
    selected, meta = select(gate_results, routing, cfg)
    assert meta.ambiguity_flag is True
    assert "differ" in meta.ambiguity_reason or "≈" in meta.ambiguity_reason


def test_selector_no_ambiguity_when_signals_match():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    # Identical signal dims (all 0.8) and close quality → no ambiguity
    # because metric_match/period_match/scope_match are EQUAL across both.
    gate_results = [_qr("B1", 0.80), _qr("B2", 0.80)]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3,
                         ambiguity_margin=0.05)
    selected, meta = select(gate_results, routing, cfg)
    assert meta.ambiguity_flag is False


def test_selector_no_accepted_evidence_returns_empty():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [_qr(f"B{i}", 0.1, accepted=False) for i in range(3)]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    selected, meta = select(gate_results, routing, cfg)
    assert len(selected) == 0
    assert meta.selection_reason != ""
    assert "no evidence" in meta.selection_reason


def test_selector_records_rejected_ids():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [
        _qr("B1", 0.8, accepted=True),
        _qr("B2", 0.1, accepted=False),
    ]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    selected, meta = select(gate_results, routing, cfg)
    assert "B2" in meta.rejected_evidence_ids
    assert "B1" in meta.selected_evidence_ids


def test_selector_to_dict_serialization():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [_qr("B1", 0.8)]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    selected, meta = select(gate_results, routing, cfg)
    d = meta.to_dict()
    assert "selected_evidence_ids" in d
    assert "top1_quality" in d
    assert "ambiguity_flag" in d


def test_selector_config_defaults():
    cfg = SelectorConfig()
    assert cfg.strategy == "Top3"
    assert cfg.max_evidence == 3
    assert cfg.ambiguity_margin > 0
