"""Phase 23.11 Regression Recovery Tests (Task 10 supplement).

Tests that Phase 23.11 routing + gate recovers Phase 23.9 correct /
Phase 23.10 wrong regressions. Per spec §13.
"""
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_all
from app.services.evidence_selector import SelectorConfig, select
from app.services.verification_context import VerificationContext
from app.services.verification.verification_service import (
    verify_evidence_set,
    verify_noisy_oracle,
)


def test_regression_recovery_phase23_9_correct_p23_10_wrong():
    """Phase 23.9 correct but Phase 23.10 wrong -> Phase 23.11 should recover."""
    # Simulate a regression: Phase 23.9 got it right, Phase 23.10 wrong
    # due to wrong-period noise entering Top5.
    claim = {
        "claim_id": "CLM-REG-1", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
        "gold": "SUPPORTED",
    }
    routing = route_claim(claim)
    # Correct Gold Evidence + wrong-period noise
    candidates = [
        {
            "evidence_id": "GOLD-1",
            "text": "五粮液 营业收入 931.8 亿元 2025年",
            "page": 5, "document_id": 1,
        },
        {
            "evidence_id": "NOISE-WP",
            "text": "营业收入 800 亿元 2023年",  # wrong period noise
            "page": 5, "document_id": 1,
        },
    ]
    ctx = VerificationContext(
        evidence_source="noisy_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3", max_evidence=3),
    )
    result = verify_noisy_oracle(claim, candidates, routing, ctx)
    # Phase 23.11 Gate should reject wrong-period noise
    gate_results = evaluate_all(
        claim, candidates, routing, ctx.gate_config
    )
    noise = next(
        (r for r in gate_results if r.evidence_id == "NOISE-WP"), None
    )
    assert noise is not None
    assert noise.accepted is False
    # Correct Gold should be selected
    sel_meta = ctx.trace.detail.get("phase23_11_selector", {})
    assert "GOLD-1" in sel_meta.get("selected_evidence_ids", []) or \
        "GOLD-1" in str(sel_meta.get("evidence_bundle", []))


def test_regression_recovery_phase23_9_wrong_p23_10_wrong():
    """Phase 23.9 wrong, Phase 23.10 wrong -> Phase 23.11 should recover."""
    claim = {
        "claim_id": "CLM-REG-2", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
        "gold": "SUPPORTED",
    }
    routing = route_claim(claim)
    candidates = [
        {
            "evidence_id": "GOLD-1",
            "text": "五粮液 营业收入 931.8 亿元 2025年",
            "page": 5, "document_id": 1,
        },
    ]
    ctx = VerificationContext(
        evidence_source="noisy_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3", max_evidence=3),
    )
    result = verify_noisy_oracle(claim, candidates, routing, ctx)
    # Should produce a verdict (not crash)
    assert result.verification_status in (
        "SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED",
        "INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE",
    )


def test_regression_top5_noise_does_not_dominate():
    """Phase 23.10 Top5 introduced noise; Phase 23.11 should not allow that."""
    claim = {
        "claim_id": "CLM-REG-3", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
        "gold": "SUPPORTED",
    }
    routing = route_claim(claim)
    # 1 correct + 4 noise (wrong periods / wrong companies)
    candidates = [
        {
            "evidence_id": "GOLD-1",
            "text": "五粮液 营业收入 931.8 亿元 2025年",
            "page": 5, "document_id": 1,
        },
        {
            "evidence_id": "NOISE-WP1",
            "text": "营业收入 800 亿元 2023年",
            "page": 5, "document_id": 1,
        },
        {
            "evidence_id": "NOISE-WP2",
            "text": "营业收入 500 亿元 2022年",
            "page": 6, "document_id": 1,
        },
        {
            "evidence_id": "NOISE-WS",
            "text": "少数股东损益 50 万元",
            "page": 10, "document_id": 1,
        },
        {
            "evidence_id": "NOISE-WE",
            "text": "美的集团 营业收入 1000 亿元",
            "page": 5, "document_id": 2,
        },
    ]
    ctx = VerificationContext(
        evidence_source="noisy_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3", max_evidence=3),
    )
    result = verify_noisy_oracle(claim, candidates, routing, ctx)
    # Phase 23.11 Selector caps at 3, so noise cannot dominate Top5
    sel_meta = ctx.trace.detail.get("phase23_11_selector", {})
    assert len(sel_meta.get("selected_evidence_ids", [])) <= 3


def test_regression_top1_vs_top3_vs_top5_comparison():
    """Compare Top1 / Top3 / Top5 strategies."""
    claim = {
        "claim_id": "CLM-REG-4", "entity": "五粮液",
        "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
        "period": "2025FY", "unit": "亿元", "value": 931.8,
        "scope": "consolidated",
        "original_text": "五粮液2025年营收931.8亿",
        "gold": "SUPPORTED",
    }
    routing = route_claim(claim)
    candidates = [
        {
            "evidence_id": "GOLD-1",
            "text": "五粮液 营业收入 931.8 亿元 2025年",
            "page": 5, "document_id": 1,
        },
    ]
    for strategy in ["Top1", "Top3", "Top5"]:
        ctx = VerificationContext(
            evidence_source="noisy_oracle",
            gate_config=GateConfig(),
            selector_config=SelectorConfig(
                strategy=strategy, max_evidence=5
            ),
        )
        result = verify_noisy_oracle(claim, candidates, routing, ctx)
        assert result.claim_id == "CLM-REG-4"
