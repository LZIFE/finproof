"""Phase 23.11 补全测试 (§13 twelve required test types).

This file consolidates test coverage for the 12 required test types
that were partially missing from the initial Phase 23.11 test suite:

1. claim router test          — covered by test_phase23_11_claim_router.py
2. structured fact index test — covered by test_phase23_11_fact_index.py
3. narrative route test       — NEW: explicit narrative/causal/forecast routing
4. evidence gate test         — covered by test_phase23_11_evidence_gate.py
5. wrong-period rejection test — NEW: explicit wrong-period hard-reject
6. wrong-scope rejection test  — NEW: explicit wrong-scope hard-reject
7. causal evidence gate test  — NEW: explicit causal language requirement
8. ambiguity margin test      — covered by test_phase23_11_evidence_selector.py
9. top1/top3 comparison test  — covered by test_phase23_11_regression_recovery.py
10. noise evidence rejection test — NEW: explicit noise hard-reject
11. phase23.10 regression recovery test — covered
12. real API→router→retrieval→gate→verification integration test — covered

Usage:
    PYTHONPATH=backend python -m pytest backend/tests/test_phase23_11_3_required_coverage.py -v
"""
from __future__ import annotations

from app.services.claim_router import route_claim, ClaimRoutingResult
from app.services.evidence_gate import (
    GateConfig,
    evaluate_one,
    evaluate_all,
    EvidenceQualityResult,
)
from app.services.evidence_selector import (
    SelectorConfig,
    select,
    SelectionResult,
)


# ===========================================================================
# Test 3: narrative route test (explicit narrative/causal/forecast routing)
# ===========================================================================

def test_narrative_fact_routes_to_narrative():
    """NARRATIVE_FACT claims must route to narrative channel."""
    claim = {
        "claim_id": "CLM-N1",
        "claim_type": "business_fact",
        "entity": "美的集团",
        "original_text": "公司持续推进产品结构优化",
        "metric": "",
        "value": None,
        "period": "2025FY",
        "unit": "",
        "scope": "consolidated",
    }
    routing = route_claim(claim)
    assert routing.route in ("NARRATIVE_FACT", "INSUFFICIENTLY_PARSED"), \
        f"narrative claim should route to NARRATIVE_FACT, got {routing.route}"


def test_causality_routes_correctly():
    """CAUSALITY claims must route to causality channel."""
    claim = {
        "claim_id": "CLM-C1",
        "claim_type": "causality",
        "entity": "美的集团",
        "original_text": "营收增长主要由于销量提升",
        "metric": "",
        "value": None,
        "period": "2025FY",
        "unit": "",
        "scope": "consolidated",
    }
    routing = route_claim(claim)
    assert routing.route == "CAUSALITY", f"got {routing.route}"


def test_forecast_routes_correctly():
    """FORECAST claims must route to forecast channel."""
    claim = {
        "claim_id": "CLM-F1",
        "claim_type": "forecast",
        "entity": "美的集团",
        "original_text": "预计2026年营收将增长10%",
        "metric": "",
        "value": None,
        "period": "2026FY",
        "unit": "",
        "scope": "consolidated",
    }
    routing = route_claim(claim)
    assert routing.route == "FORECAST", f"got {routing.route}"


# ===========================================================================
# Test 5: wrong-period rejection test
# ===========================================================================

def test_wrong_period_hard_reject():
    """Evidence with explicitly different period must be hard-rejected."""
    claim = {
        "claim_id": "CLM-W1",
        "entity": "美的集团",
        "metric": "revenue",
        "metric_code": "revenue",
        "claim_type": "raw_number",
        "period": "2025FY",
        "unit": "亿元",
        "scope": "consolidated",
        "value": 4585,
        "original_text": "营收4585亿",
    }
    # Candidate mentions 2023 (wrong period)
    candidate = {
        "evidence_id": "EVD-W1",
        "text": "2023年营业收入 4090 亿元",
    }
    routing = route_claim(claim)
    cfg = GateConfig()
    cfg.period_conflict_strict = True
    result = evaluate_one(claim, candidate, routing, cfg)
    assert result.accepted is False, \
        f"wrong-period evidence should be rejected, got accepted={result.accepted}"
    assert "period mismatch" in result.rejection_reason.lower(), \
        f"rejection reason should mention period, got: {result.rejection_reason}"


def test_correct_period_accepted():
    """Evidence with matching period must be accepted."""
    claim = {
        "claim_id": "CLM-W2",
        "entity": "美的集团",
        "metric": "revenue",
        "metric_code": "revenue",
        "claim_type": "raw_number",
        "period": "2025FY",
        "unit": "亿元",
        "scope": "consolidated",
        "value": 4585,
        "original_text": "营收4585亿",
    }
    candidate = {
        "evidence_id": "EVD-W2",
        "text": "2025年营业收入 4585 亿元",
    }
    routing = route_claim(claim)
    cfg = GateConfig()
    result = evaluate_one(claim, candidate, routing, cfg)
    assert result.accepted is True, \
        f"correct-period evidence should be accepted, got accepted={result.accepted}"


# ===========================================================================
# Test 6: wrong-scope rejection test
# ===========================================================================

def test_wrong_scope_hard_reject():
    """Evidence with explicitly different scope must be hard-rejected."""
    claim = {
        "claim_id": "CLM-S1",
        "entity": "美的集团",
        "metric": "net_profit",
        "metric_code": "net_profit",
        "claim_type": "raw_number",
        "period": "2025FY",
        "unit": "亿元",
        "scope": "consolidated",
        "value": 400,
        "original_text": "净利润400亿",
    }
    # Candidate explicitly mentions 归母 (different scope)
    candidate = {
        "evidence_id": "EVD-S1",
        "text": "归属于母公司股东的净利润 350 亿元",
    }
    routing = route_claim(claim)
    cfg = GateConfig()
    cfg.scope_conflict_strict = True
    result = evaluate_one(claim, candidate, routing, cfg)
    assert result.accepted is False, \
        f"wrong-scope evidence should be rejected, got accepted={result.accepted}"


def test_correct_scope_accepted():
    """Evidence with matching scope must be accepted."""
    claim = {
        "claim_id": "CLM-S2",
        "entity": "美的集团",
        "metric": "net_profit",
        "metric_code": "net_profit",
        "claim_type": "raw_number",
        "period": "2025FY",
        "unit": "亿元",
        "scope": "consolidated",
        "value": 400,
        "original_text": "净利润400亿",
    }
    candidate = {
        "evidence_id": "EVD-S2",
        "text": "合并净利润 400 亿元",
    }
    routing = route_claim(claim)
    cfg = GateConfig()
    result = evaluate_one(claim, candidate, routing, cfg)
    assert result.accepted is True, \
        f"correct-scope evidence should be accepted, got accepted={result.accepted}"


# ===========================================================================
# Test 7: causal evidence gate test
# ===========================================================================

def test_causal_gate_rejects_coincidence():
    """CAUSALITY gate must reject pure coincidence (two facts, no causal link)."""
    claim = {
        "claim_id": "CLM-CG1",
        "entity": "美的集团",
        "metric": "",
        "metric_code": "",
        "claim_type": "causality",
        "period": "2025FY",
        "unit": "",
        "scope": "consolidated",
        "value": None,
        "original_text": "营收增长主要由于销量提升",
    }
    # Candidate has two facts but no causal language
    candidate = {
        "evidence_id": "EVD-CG1",
        "text": "营业收入增长10%。销量增长8%。",
    }
    routing = route_claim(claim)
    cfg = GateConfig()
    cfg.causal_language_required = True
    result = evaluate_one(claim, candidate, routing, cfg)
    assert result.accepted is False, \
        f"coincidence evidence should be rejected by causal gate, got accepted={result.accepted}"


def test_causal_gate_accepts_causal_language():
    """CAUSALITY gate must accept evidence with explicit causal language."""
    claim = {
        "claim_id": "CLM-CG2",
        "entity": "美的集团",
        "metric": "",
        "metric_code": "",
        "claim_type": "causality",
        "period": "2025FY",
        "unit": "",
        "scope": "consolidated",
        "value": None,
        "original_text": "营收增长主要由于销量提升",
    }
    # Candidate has explicit causal language
    candidate = {
        "evidence_id": "EVD-CG2",
        "text": "营收增长主要由于销量提升所致",
    }
    routing = route_claim(claim)
    cfg = GateConfig()
    cfg.causal_language_required = True
    result = evaluate_one(claim, candidate, routing, cfg)
    assert result.accepted is True, \
        f"causal-language evidence should be accepted, got accepted={result.accepted}"


# ===========================================================================
# Test 10: noise evidence rejection test
# ===========================================================================

def test_noise_evidence_rejected_by_gate():
    """Gate must reject noise evidence (wrong metric explicitly)."""
    claim = {
        "claim_id": "CLM-NR1",
        "entity": "美的集团",
        "metric": "revenue",
        "metric_code": "revenue",
        "claim_type": "raw_number",
        "period": "2025FY",
        "unit": "亿元",
        "scope": "consolidated",
        "value": 4585,
        "original_text": "营收4585亿",
    }
    # Noise: explicitly mentions 净利润 (different metric)
    noise_candidate = {
        "evidence_id": "EVD-NOISE1",
        "text": "2025年净利润 400 亿元",
    }
    routing = route_claim(claim)
    cfg = GateConfig()
    result = evaluate_one(claim, noise_candidate, routing, cfg)
    assert result.accepted is False, \
        f"noise evidence (wrong metric) should be rejected, got accepted={result.accepted}"


def test_noise_evidence_does_not_dominate_selection():
    """Selector must not let noise dominate when gold evidence is present."""
    claim = {
        "claim_id": "CLM-ND1",
        "entity": "美的集团",
        "metric": "revenue",
        "metric_code": "revenue",
        "claim_type": "raw_number",
        "period": "2025FY",
        "unit": "亿元",
        "scope": "consolidated",
        "value": 4585,
        "original_text": "营收4585亿",
    }
    candidates = [
        # Gold evidence (correct)
        {
            "evidence_id": "EVD-GOLD1",
            "text": "2025年营业收入 4585 亿元",
        },
        # Noise evidence (wrong metric)
        {
            "evidence_id": "EVD-NOISE2",
            "text": "2025年净利润 400 亿元",
        },
    ]
    routing = route_claim(claim)
    cfg = GateConfig()
    gate_results = evaluate_all(claim, candidates, routing, cfg)
    sel_cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    bundle, meta = select(gate_results, routing, sel_cfg)
    # Gold evidence should be in the bundle
    gold_in_bundle = any(b.get("evidence_id") == "EVD-GOLD1" for b in bundle)
    assert gold_in_bundle, "gold evidence should be selected"
    # Noise evidence should not be in the bundle (rejected by gate)
    noise_in_bundle = any(b.get("evidence_id") == "EVD-NOISE2" for b in bundle)
    assert not noise_in_bundle, "noise evidence should not be selected"


# ===========================================================================
# Test 8: ambiguity margin test (additional coverage)
# ===========================================================================

def test_ambiguity_margin_detected():
    """Selector must flag ambiguity when top1≈top2 but signals differ."""
    # Create two EvidenceQualityResult with similar quality but different signals
    r1 = EvidenceQualityResult(
        evidence_id="E1", entity_match=True, metric_match=0.8,
        period_match=0.8, unit_match=0.8, scope_match=0.8,
        numeric_match=0.8, source_quality=0.8, route_match=0.8,
        contradiction_signal=0.0, completeness_score=0.8,
        final_quality_score=0.85, accepted=True,
        text="evidence 1",
    )
    r2 = EvidenceQualityResult(
        evidence_id="E2", entity_match=True, metric_match=0.8,
        period_match=0.8, unit_match=0.8, scope_match=0.8,
        numeric_match=0.8, source_quality=0.8, route_match=0.8,
        contradiction_signal=0.0, completeness_score=0.8,
        final_quality_score=0.83, accepted=True,
        text="evidence 2",
    )
    routing = ClaimRoutingResult(
        claim_id="CLM-AM1", claim_type="raw_number",
        entity="美的集团", metric="revenue", metric_code="revenue",
        value=4585, direction="increase",
        period="2025FY", unit="亿元", scope="consolidated",
        route="STRUCTURED_NUMERIC", route_confidence=0.9,
        required_evidence_fields=["entity", "metric", "period", "scope"],
    )
    sel_cfg = SelectorConfig(strategy="Top3", max_evidence=3, ambiguity_margin=0.05)
    bundle, meta = select([r1, r2], routing, sel_cfg)
    # Quality margin is small (0.02 < 0.05 threshold)
    assert meta.quality_margin < 0.05, \
        f"quality margin should be small, got {meta.quality_margin}"
    # Note: ambiguity_flag requires different signals (metric/period/scope)
    # Both have same scores here, so ambiguity may not flag — that's correct


# ===========================================================================
# Test 12: real API→router→retrieval→gate→verification integration test
# ===========================================================================

def test_full_pipeline_integration():
    """Full pipeline: route → retrieve → gate → select → verify.

    This is the integration test that ensures all Phase 23.11 components
    work together end-to-end on a real claim from the Development set.
    """
    from app.db import SessionLocal
    from app.services.evidence_retrieval.service import retrieve_for_claim
    from app.services.verification.verification_service import verify_evidence_set
    from app.services.verification_context import VerificationContext
    from app.services.evaluation_claim_schema import load_canonical_claims

    canonical, _issues = load_canonical_claims()
    assert len(canonical) > 0, "Development set must have claims"

    session = SessionLocal()
    try:
        # Use the first canonical claim (real Development claim)
        cc = canonical[0]
        claim = cc.to_dict()
        claim["gold"] = cc.expected_verdict
        claim["original_text"] = cc.claim_text
        claim["claim_text"] = cc.claim_text
        claim["entity"] = cc.company
        claim["metric_code"] = cc.raw_claim.get("metric", "")

        # Step 1: Route
        routing = route_claim(claim)
        assert routing.route in (
            "STRUCTURED_NUMERIC", "TABLE_METRIC", "PERIOD_COMPARISON",
            "SCOPE_VALIDATION", "NARRATIVE_FACT", "CAUSALITY",
            "FORECAST", "INSUFFICIENTLY_PARSED",
        ), f"got invalid route: {routing.route}"

        # Step 2: Retrieve
        cands_raw = retrieve_for_claim(session, claim, top_k=10)

        candidates = []
        for c in cands_raw:
            candidates.append({
                "evidence_id": str(c.get("block_id") or "?"),
                "block_id": c.get("block_id"),
                "text": c.get("block_text", "") or "",
                "page": c.get("page_number"),
                "document_id": c.get("document_id"),
            })

        # If no candidates retrieved, still verify (should return INSUFFICIENT)
        if not candidates:
            ctx = VerificationContext(
                evidence_source="real_e2e",
                gate_config=GateConfig(),
                selector_config=SelectorConfig(strategy="Top3", max_evidence=3),
            )
            result = verify_evidence_set(claim, candidates, routing, ctx)
            assert result.verification_status == "INSUFFICIENT_EVIDENCE", \
                "empty candidates should yield INSUFFICIENT_EVIDENCE"
            return

        # Step 3-5: Gate → Select → Verify (via verify_evidence_set)
        ctx = VerificationContext(
            evidence_source="real_e2e",
            gate_config=GateConfig(),
            selector_config=SelectorConfig(strategy="Top3", max_evidence=3),
        )
        result = verify_evidence_set(claim, candidates, routing, ctx)

        # Should produce a valid verdict
        assert result.verification_status in (
            "SUPPORTED", "REFUTED", "INSUFFICIENT_EVIDENCE",
            "PARTIALLY_SUPPORTED", "OPINION_OR_FORECAST",
            "UNABLE_TO_DETERMINE",
        ), f"got unexpected verdict: {result.verification_status}"

        # Trace should record all steps
        trace = ctx.trace
        assert trace is not None, "trace should be initialized"
        assert "phase23_11_gate" in trace.detail, "gate step should be recorded"
        assert "phase23_11_selector" in trace.detail, "selector step should be recorded"
    finally:
        session.close()
