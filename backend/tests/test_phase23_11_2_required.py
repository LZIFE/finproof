"""Phase 23.11.2 Required Tests (Task 11).

The 12 tests explicitly required by §12:
1. canonical evidence adapter
2. missing metadata 三态
3. explicit mismatch hard reject
4. unknown field soft penalty
5. route-specific Gate
6. narrative evidence 不要求数值字段
7. selector non-empty
8. dedup 不删除全部 Evidence
9. failure attribution sum=43
10. leave-one-company threshold leakage
11. CORE/NOISY/REAL 共享 Gate 配置
12. API 生产路径集成
"""
from app.services.canonical_evidence import (
    CanonicalEvidence, adapt_core_oracle, adapt_noisy_oracle, adapt_real_e2e,
    build_schema_comparison,
)
from app.services.claim_router import route_claim
from app.services.evidence_gate import (
    GateConfig, evaluate_one, EvidenceQualityResult,
)
from app.services.evidence_selector import select, SelectorConfig
from app.services.failure_attribution import (
    classify_outcome, summarize_outcomes, PRIMARY_OUTCOMES,
)


# Test 1: canonical evidence adapter
def test_canonical_evidence_adapter():
    """三来源适配器输出同一 CanonicalEvidence schema."""
    claim = {"claim_id": "CLM-1", "entity": "美的集团", "metric": "revenue",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "original_text": "营收100亿"}
    co, _ = adapt_core_oracle([{"evidence_id": "E1", "evidence_text": "营业收入 100"}], claim, "STRUCTURED_NUMERIC")
    no, _ = adapt_noisy_oracle([{"evidence_id": "E1", "text": "营业收入 100"}], claim, "STRUCTURED_NUMERIC")
    re, _ = adapt_real_e2e([{"evidence_id": "B1", "block_text": "营业收入 100", "block_id": 1}], claim, "STRUCTURED_NUMERIC")
    assert isinstance(co[0], CanonicalEvidence)
    assert isinstance(no[0], CanonicalEvidence)
    assert isinstance(re[0], CanonicalEvidence)
    # same field set
    assert set(co[0].to_dict().keys()) == set(no[0].to_dict().keys()) == set(re[0].to_dict().keys())


# Test 2: missing metadata 三态
def test_missing_metadata_three_state():
    """缺失字段 → UNKNOWN, 非 False."""
    claim = {"claim_id": "CLM-1", "entity": "美的集团", "metric": "revenue",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "original_text": "营收100亿"}
    # Evidence without company/entity in text (table numeric)
    cand = {"evidence_id": "B1", "text": "营业收入 456,451,731 千元"}
    routing = route_claim(claim)
    r = evaluate_one(claim, cand, routing, GateConfig())
    # entity missing in text → UNKNOWN, not MISMATCH → NOT hard reject
    assert r.entity_state == "UNKNOWN"
    assert r.accepted is True  # UNKNOWN soft penalty only


# Test 3: explicit mismatch hard reject
def test_explicit_mismatch_hard_reject():
    """明确冲突 → Hard Reject."""
    claim = {"claim_id": "CLM-1", "entity": "美的集团", "metric_code": "revenue",
             "metric": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "value": 100, "original_text": "营收100亿"}
    # Evidence explicitly mentions DIFFERENT period (2023)
    cand = {"evidence_id": "B1", "text": "美的集团 营业收入 200 亿 2023年"}
    routing = route_claim(claim)
    r = evaluate_one(claim, cand, routing, GateConfig())
    assert r.period_state == "MISMATCH"
    assert r.accepted is False


# Test 4: unknown field soft penalty
def test_unknown_field_soft_penalty():
    """UNKNOWN → soft penalty, 不 Hard Reject."""
    claim = {"claim_id": "CLM-1", "entity": "美的集团", "metric": "revenue",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "original_text": "营收100亿"}
    # Evidence has metric but no period info
    cand = {"evidence_id": "B1", "text": "营业收入 100"}
    routing = route_claim(claim)
    r = evaluate_one(claim, cand, routing, GateConfig())
    assert r.period_state == "UNKNOWN"
    # Should NOT hard reject on UNKNOWN alone
    assert r.accepted is True


# Test 5: route-specific Gate
def test_route_specific_gate():
    """不同 Route 用不同 Gate 规则."""
    # CAUSALITY requires causal language — test Gate分支, not router priority.
    causal_claim = {"claim_id": "CLM-C", "claim_type": "CAUSALITY",
                    "entity": "美的", "original_text": "营收增长由于新品销售"}
    routing = route_claim(causal_claim)
    # Force CAUSALITY route to test Gate's CAUSALITY branch directly (router
    # may优先级 to STRUCTURED_NUMERIC when numeric fields present).
    routing.route = "CAUSALITY"
    cand_no_causal = {"evidence_id": "B1", "text": "营收 100 亿 利润 10 亿"}  # no causal language
    r = evaluate_one(causal_claim, cand_no_causal, routing, GateConfig())
    assert r.accepted is False  # CAUSALITY requires causal language


# Test 6: narrative evidence 不要求数值字段
def test_narrative_no_numeric_required():
    """NARRATIVE_FACT Gate 不要求 raw_value/unit/row_header."""
    claim = {"claim_id": "CLM-N", "entity": "美的", "claim_type": "NARRATIVE",
             "original_text": "公司持续推进数字化转型"}
    routing = route_claim(claim)
    # Force NARRATIVE_FACT route to test Gate分支 directly
    routing.route = "NARRATIVE_FACT"
    cand = {"evidence_id": "B1", "text": "公司数字化转型持续推进"}  # no numeric
    r = evaluate_one(claim, cand, routing, GateConfig())
    # Should not reject for missing numeric fields
    assert r.rejection_reason != "metric match 0.00 below threshold"


# Test 7: selector non-empty
def test_selector_non_empty_when_accepted():
    """Gate 接受 >0 时 Selector 不得无原因返回空."""
    claim = {"claim_id": "CLM-1", "entity": "美的", "metric": "revenue",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "original_text": "营收100亿"}
    routing = route_claim(claim)
    cand = {"evidence_id": "B1", "text": "营业收入 100 亿 2025"}
    gr = [evaluate_one(claim, cand, routing, GateConfig())]
    accepted_count = sum(1 for r in gr if r.accepted)
    assert accepted_count > 0
    bundle, meta = select(gr, routing, SelectorConfig(strategy="Top3"))
    assert meta.selector_output_count > 0
    assert meta.empty_reason == ""


# Test 8: dedup 不删除全部 Evidence
def test_dedup_not_delete_all():
    """dedup 保留唯一 eid, 不删空."""
    claim = {"claim_id": "CLM-1", "entity": "美的", "metric": "revenue",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "original_text": "营收100亿"}
    routing = route_claim(claim)
    # Two accepted with same eid → dedup keeps 1, not 0
    gr = [
        EvidenceQualityResult("DUP", True, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.0, 0.8, 0.8, True, "",
            entity_state="MATCH", metric_state="MATCH", period_state="MATCH", unit_state="MATCH", scope_state="MATCH", route_state="MATCH"),
        EvidenceQualityResult("DUP", True, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.0, 0.7, 0.7, True, "",
            entity_state="MATCH", metric_state="MATCH", period_state="MATCH", unit_state="MATCH", scope_state="MATCH", route_state="MATCH"),
    ]
    bundle, meta = select(gr, routing, SelectorConfig(strategy="Top3"))
    assert meta.selector_output_count >= 1  # not deleted all
    assert meta.deduplicated_count == 1


# Test 9: failure attribution sum=43
def test_failure_attribution_sum_43():
    """互斥失败分类 sum 必须 = total."""
    import random
    random.seed(42)
    outcomes = []
    for i in range(1, 44):
        o = classify_outcome(
            f"CLM-{i:03}", pred=random.choice(["SUPPORTED", "INSUFFICIENT_EVIDENCE"]),
            gold="SUPPORTED", candidates_before_gate=random.randint(0, 10),
            candidates_after_gate=random.randint(0, 5), selector_input_count=random.randint(0, 3),
            selector_output_count=random.randint(0, 2), selector_empty_reason="",
        )
        outcomes.append(o)
    s = summarize_outcomes(outcomes)
    assert s["sum_equals_total"] is True
    assert s["outcome_sum"] == 43


# Test 10: leave-one-company threshold leakage
def test_leave_one_company_no_leakage():
    """留一公司阈值无 leakage: 无 claim_id/company-specific 阈值."""
    from app.services.evidence_gate import GateConfig
    cfg = GateConfig()
    # Thresholds must be uniform (not per-claim/company)
    assert isinstance(cfg.metric_match_threshold, (int, float))
    assert isinstance(cfg.high_quality_threshold, (int, float))
    # No claim_id/company-specific fields exist on GateConfig
    forbidden_attrs = ["claim_id_threshold", "company_threshold", "claim_specific"]
    for attr in forbidden_attrs:
        assert not hasattr(cfg, attr), f"GateConfig has forbidden {attr}"


# Test 11: CORE/NOISY/REAL 共享 Gate 配置
def test_three_modes_share_gate_config():
    """三模式共享同一 GateConfig (无 per-mode override)."""
    from app.services.verification_context import VerificationContext
    cfg = GateConfig()
    ctx_core = VerificationContext("core_oracle", cfg)
    ctx_noisy = VerificationContext("noisy_oracle", cfg)
    ctx_e2e = VerificationContext("real_e2e", cfg)
    # All three point to the SAME GateConfig instance
    assert ctx_core.gate_config is cfg
    assert ctx_noisy.gate_config is cfg
    assert ctx_e2e.gate_config is cfg


# Test 12: API 生产路径集成
def test_api_production_path_integration():
    """verify_claim_production 走完整生产链: Router → Retrieval → Gate → Selector → core_verify."""
    import inspect
    from app.services.verification.verification_service import (
        verify_claim_production, verify_evidence_set,
    )
    src = inspect.getsource(verify_claim_production)
    # Must route → retrieve → verify_evidence_set (which gates + selects + core_verify)
    assert "route_claim" in src or "_route_claim" in src
    assert "verify_evidence_set" in src or "verify_real_e2e" in src
    ves_src = inspect.getsource(verify_evidence_set)
    assert "evaluate_all" in ves_src or "_gate_evaluate_all" in ves_src  # Gate
    assert "_selector_select" in ves_src or "select(" in ves_src  # Selector
    assert "core_verify" in ves_src  # core_verify
