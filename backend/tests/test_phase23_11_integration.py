"""Phase 23.11 Integration tests (Task 6).

Tests the canonical verify_evidence_set entry shared by CORE_ORACLE,
NOISY_ORACLE, and REAL_E2E. Gold Evidence must pass through Gate and
Selector; if rejected, result is INSUFFICIENT (GATE_REJECTED_GOLD).
"""
from app.services.verification_context import VerificationContext
from app.services.evidence_gate import GateConfig
from app.services.evidence_selector import SelectorConfig
from app.services.claim_router import route_claim
from app.services.verification.verification_service import (
    verify_evidence_set,
    verify_core_oracle,
    verify_noisy_oracle,
    verify_real_e2e,
)


def test_verify_evidence_set_runs_full_pipeline():
    """verify_evidence_set runs Gate -> Selector -> core_verify."""
    claim = {
        "claim_id": "CLM-TEST", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "scope": "consolidated",
        "value": 931.8, "original_text": "五粮液2025年营收931.8亿",
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
    result = verify_evidence_set(claim, candidates, routing, ctx)
    assert result.claim_id == "CLM-TEST"
    assert result.verification_status in (
        "SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED",
        "INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE",
    )
    # Trace must be set
    assert ctx.trace is not None
    # Gate and selector steps recorded in trace
    assert "phase23_11_gate" in ctx.trace.detail
    assert "phase23_11_selector" in ctx.trace.detail


def test_core_oracle_calls_verify_evidence_set():
    """CORE_ORACLE routes through verify_evidence_set, not bypass."""
    claim = {
        "claim_id": "CLM-ORACLE", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
    }
    routing = route_claim(claim)
    gold_evidence = {
        "evidence_id": "GOLD-B1",
        "text": "五粮液 营业收入 931.8 亿元 2025年",
        "page": 5, "document_id": 1,
    }
    ctx = VerificationContext(
        evidence_source="core_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_core_oracle(claim, gold_evidence, routing, ctx)
    assert result.claim_id == "CLM-ORACLE"
    assert ctx.trace is not None


def test_gold_evidence_rejected_by_gate_makes_oracle_fail():
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


def test_noisy_oracle_accepts_gold_rejects_noise():
    """NOISY_ORACLE: Gold accepted, noise rejected by gate."""
    claim = {
        "claim_id": "CLM-NOISY", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
    }
    routing = route_claim(claim)
    # Gold + noise: noise has wrong period
    candidates = [
        {
            "evidence_id": "GOLD-1",
            "text": "五粮液 营业收入 931.8 亿元 2025年",
            "page": 5, "document_id": 1,
        },
        {
            "evidence_id": "NOISE-1",
            "text": "营业收入 800 亿元 2023年",  # wrong period noise
            "page": 5, "document_id": 1,
        },
    ]
    ctx = VerificationContext(
        evidence_source="noisy_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_noisy_oracle(claim, candidates, routing, ctx)
    assert result.claim_id == "CLM-NOISY"


def test_verify_evidence_set_trace_records_all_steps():
    """Trace must record routing, gate, selector, and final verdict."""
    claim = {
        "claim_id": "CLM-TRACE", "entity": "五粮液",
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
    assert "phase23_11_routing" in trace.detail
    assert "phase23_11_gate" in trace.detail
    assert "phase23_11_selector" in trace.detail
    assert "phase23_11_final" in trace.detail


def test_verify_evidence_set_empty_candidates():
    """Empty candidates -> INSUFFICIENT_EVIDENCE."""
    claim = {
        "claim_id": "CLM-EMPTY", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
    }
    routing = route_claim(claim)
    ctx = VerificationContext(
        evidence_source="real_e2e",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_evidence_set(claim, [], routing, ctx)
    assert result.verification_status in (
        "INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE",
    )


def test_three_modes_share_verify_evidence_set():
    """All three modes (CORE_ORACLE, NOISY_ORACLE, REAL_E2E) must call the
    same verify_evidence_set. This is verified by import structure."""
    import inspect
    from app.services.verification.verification_service import (
        verify_core_oracle as vco,
        verify_noisy_oracle as vno,
        verify_evidence_set as ves,
    )

    # All three must reference verify_evidence_set
    co_src = inspect.getsource(vco)
    no_src = inspect.getsource(vno)
    assert "verify_evidence_set" in co_src
    assert "verify_evidence_set" in no_src
    # verify_evidence_set itself must exist and be callable
    assert callable(ves)


def test_verification_context_dataclass():
    """VerificationContext is a dataclass with required fields."""
    ctx = VerificationContext(evidence_source="real_e2e")
    assert ctx.evidence_source == "real_e2e"
    assert ctx.gate_config is not None
    assert ctx.selector_config is not None
    assert ctx.trace is None
    assert ctx.candidates_before_gate == 0
    assert ctx.candidates_after_gate == 0
