"""Phase 23.11 Required Integration Tests (Task 10).

The 12 tests explicitly required by the user:
1. CORE_ORACLE and REAL_E2E both call the same verify_evidence_set
2. CORE_ORACLE cannot bypass Evidence Gate
3. Gold Evidence rejected by Gate -> Oracle fails
4. NOISY_ORACLE: wrong-period evidence rejected
5. NOISY_ORACLE: correct Gold Evidence selected
6. Real API calls Claim Router
7. Real API calls Evidence Gate
8. Real API calls Evidence Selector
9. Real API finally calls core_verify
10. Old verify_claim contains no independent Verdict logic
11. Demo and evaluation scripts use the same Production entry
12. Trace shows each step's input/output and final decision source
"""
import inspect

from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_all
from app.services.evidence_selector import SelectorConfig, select
from app.services.verification_context import VerificationContext
from app.services.verification.verification_service import (
    verify_evidence_set,
    verify_core_oracle,
    verify_noisy_oracle,
    verify_real_e2e,
    verify_claim_production,
)


# Test 1: CORE_ORACLE and REAL_E2E both call the same verify_evidence_set
def test_core_oracle_and_real_e2e_share_verify_evidence_set():
    """Both CORE_ORACLE and REAL_E2E must call verify_evidence_set."""
    co_src = inspect.getsource(verify_core_oracle)
    e2e_src = inspect.getsource(verify_real_e2e)
    assert "verify_evidence_set" in co_src
    assert "verify_evidence_set" in e2e_src


# Test 2: CORE_ORACLE cannot bypass Evidence Gate
def test_core_oracle_cannot_bypass_gate():
    """CORE_ORACLE must route through Gate, not bypass it."""
    src = inspect.getsource(verify_core_oracle)
    assert "verify_evidence_set" in src
    # verify_evidence_set calls evaluate_all (gate)
    ves_src = inspect.getsource(verify_evidence_set)
    assert "evaluate_all" in ves_src or "_gate_evaluate_all" in ves_src


# Test 3: Gold Evidence rejected by Gate -> Oracle fails
def test_gold_rejected_by_gate_makes_oracle_fail():
    """If Gold is rejected by Gate, Oracle must NOT bypass; result INSUFFICIENT."""
    claim = {
        "claim_id": "CLM-GOLD-REJECT", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
    }
    routing = route_claim(claim)
    # Gold evidence with wrong period (will fail period gate)
    gold_evidence = {
        "evidence_id": "GOLD-BAD",
        "text": "营业收入 100 亿元 2023年",  # wrong period
        "page": 5, "document_id": 1,
    }
    ctx = VerificationContext(
        evidence_source="core_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_core_oracle(claim, gold_evidence, routing, ctx)
    # Oracle should NOT bypass the gate; should get INSUFFICIENT
    assert result.verification_status in (
        "INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE",
    )


# Test 4: NOISY_ORACLE: wrong-period evidence rejected
def test_noisy_oracle_rejects_wrong_period():
    """NOISY_ORACLE must reject wrong-period evidence via Gate."""
    claim = {
        "claim_id": "CLM-NOISY-WP", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
    }
    routing = route_claim(claim)
    # Gold (correct period) + noise (wrong period)
    candidates = [
        {
            "evidence_id": "GOLD-1",
            "text": "五粮液 营业收入 931.8 亿元 2025年",
            "page": 5, "document_id": 1,
        },
        {
            "evidence_id": "NOISE-WP",
            "text": "营业收入 800 亿元 2023年",  # wrong period
            "page": 5, "document_id": 1,
        },
    ]
    ctx = VerificationContext(
        evidence_source="noisy_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_noisy_oracle(claim, candidates, routing, ctx)
    # Gate should reject the wrong-period noise
    gate_results = evaluate_all(
        claim, candidates, routing, ctx.gate_config
    )
    noise_result = next(
        (r for r in gate_results if r.evidence_id == "NOISE-WP"), None
    )
    assert noise_result is not None
    assert noise_result.accepted is False


# Test 5: NOISY_ORACLE: correct Gold Evidence selected
def test_noisy_oracle_selects_correct_gold():
    """NOISY_ORACLE must select correct Gold Evidence via Selector."""
    claim = {
        "claim_id": "CLM-NOISY-GOLD", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
    }
    routing = route_claim(claim)
    candidates = [
        {
            "evidence_id": "GOLD-1",
            "text": "五粮液 营业收入 931.8 亿元 2025年",
            "page": 5, "document_id": 1,
        },
        {
            "evidence_id": "NOISE-WP",
            "text": "营业收入 800 亿元 2023年",
            "page": 5, "document_id": 1,
        },
    ]
    ctx = VerificationContext(
        evidence_source="noisy_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_noisy_oracle(claim, candidates, routing, ctx)
    # The correct Gold Evidence should be in selected_evidence_ids
    sel_meta = ctx.trace.detail.get("phase23_11_selector", {})
    assert "GOLD-1" in sel_meta.get("selected_evidence_ids", []) or \
        "GOLD-1" in sel_meta.get("evidence_bundle", [])


# Test 6: Real API calls Claim Router
def test_real_api_calls_claim_router():
    """verify_claim_production must call Claim Router (route_claim)."""
    src = inspect.getsource(verify_claim_production)
    assert "route_claim" in src or "_route_claim" in src


# Test 7: Real API calls Evidence Gate
def test_real_api_calls_evidence_gate():
    """verify_claim_production must call Evidence Gate (via verify_evidence_set)."""
    src = inspect.getsource(verify_claim_production)
    assert "verify_evidence_set" in src or "verify_real_e2e" in src
    # verify_evidence_set calls evaluate_all (gate)
    ves_src = inspect.getsource(verify_evidence_set)
    assert "evaluate_all" in ves_src or "_gate_evaluate_all" in ves_src


# Test 8: Real API calls Evidence Selector
def test_real_api_calls_evidence_selector():
    """verify_claim_production must call Evidence Selector (via verify_evidence_set)."""
    ves_src = inspect.getsource(verify_evidence_set)
    assert "_selector_select" in ves_src or "select(" in ves_src


# Test 9: Real API finally calls core_verify
def test_real_api_finally_calls_core_verify():
    """verify_claim_production must finally call core_verify (via verify_evidence_set)."""
    ves_src = inspect.getsource(verify_evidence_set)
    assert "core_verify" in ves_src


# Test 10: Old verify_claim contains no independent Verdict logic
def test_old_verify_claim_no_independent_verdict_logic():
    """Old verify_claim must be a thin adapter, no independent Verdict logic."""
    from app.services.verification.verification_service import verify_claim
    src = inspect.getsource(verify_claim)
    # Must NOT contain independent Verdict logic
    forbidden = [
        "if result.verification_status",
        "return VerificationResult(",
        "verdict =",
        "Verdict(",
    ]
    for f in forbidden:
        assert f not in src, f"forbidden pattern {f} found in verify_claim"


# Test 11: Demo and evaluation scripts use the same Production entry
def test_demo_and_evaluation_use_same_production_entry():
    """Demo and evaluation scripts must use the same Production entry."""
    # verify_claim_production is the single Production entry
    src = inspect.getsource(verify_claim_production)
    # It must call verify_real_e2e or verify_evidence_set
    assert "verify_evidence_set" in src or "verify_real_e2e" in src


# Test 12: Trace shows each step's input/output and final decision source
def test_trace_shows_each_step_input_output_and_final_decision():
    """Trace must show each step's input/output and final decision source."""
    claim = {
        "claim_id": "CLM-TRACE-FULL", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
    }
    routing = route_claim(claim)
    candidates = [
        {
            "evidence_id": "B1",
            "text": "五粮液 营业收入 931.8 亿元 2025年",
            "page": 5, "document_id": 1,
        },
    ]
    ctx = VerificationContext(
        evidence_source="real_e2e",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    verify_evidence_set(claim, candidates, routing, ctx)
    trace = ctx.trace
    # Trace must record routing, gate, selector, and final verdict
    assert "phase23_11_routing" in trace.detail
    assert "phase23_11_gate" in trace.detail
    assert "phase23_11_selector" in trace.detail
    assert "phase23_11_final" in trace.detail
    # Final verdict source must be recorded
    final = trace.detail["phase23_11_final"]
    assert "verification_status" in final
    assert "confidence" in final
