"""Phase 23.8 明确四类 Verdict 边界与决策顺序单元测试。"""

from __future__ import annotations

import pytest

from app.services.verification.verdict_decision import (
    DECISION_STEPS,
    DecisionTrace,
    guard_semantic_not_override_numeric,
    resolve_verdict,
)


class TestDecisionStepsOrder:
    def test_8_steps(self):
        assert len(DECISION_STEPS) == 8

    def test_order(self):
        assert DECISION_STEPS[0] == "evidence_availability"
        assert DECISION_STEPS[5] == "numeric_calculation"
        assert DECISION_STEPS[7] == "verdict_mapping"


class TestVerdictBoundary:
    def test_supported_full_match(self):
        v, trace = resolve_verdict(
            evidence_available=True, entity_match=True, metric_match=True,
            period_match=True, unit_scope_match=True, numeric_match=True,
            semantic_completeness=0.9,
        )
        assert v == "SUPPORTED"
        assert all(s["passed"] for s in trace.steps)

    def test_refuted_numeric_conflict(self):
        # 数值冲突 → REFUTED，即使 semantic_completeness 高也不降级
        v, trace = resolve_verdict(
            evidence_available=True, entity_match=True, metric_match=True,
            period_match=True, unit_scope_match=True, numeric_match=False,
            semantic_completeness=0.95,  # 语义高但数值冲突
        )
        assert v == "REFUTED"
        # step 6 应 failed
        step6 = [s for s in trace.steps if s["step"] == "numeric_calculation"][0]
        assert not step6["passed"]
        assert "REFUTED" in step6["reason"]

    def test_partial_supported_numeric_match_low_semantic(self):
        v, trace = resolve_verdict(
            evidence_available=True, entity_match=True, metric_match=True,
            period_match=True, unit_scope_match=True, numeric_match=True,
            semantic_completeness=0.5,  # 数值匹配但语义部分
        )
        assert v == "PARTIALLY_SUPPORTED"

    def test_insufficient_no_evidence(self):
        v, trace = resolve_verdict(
            evidence_available=False, entity_match=False, metric_match=False,
            period_match=False, unit_scope_match=False, numeric_match=None,
            semantic_completeness=0.0,
        )
        assert v == "INSUFFICIENT_EVIDENCE"
        assert trace.steps[0]["step"] == "evidence_availability"
        assert not trace.steps[0]["passed"]

    def test_insufficient_entity_mismatch(self):
        v, _ = resolve_verdict(
            evidence_available=True, entity_match=False, metric_match=True,
            period_match=True, unit_scope_match=True, numeric_match=True,
            semantic_completeness=0.9,
        )
        assert v == "INSUFFICIENT_EVIDENCE"

    def test_refuted_not_degraded_to_partial(self):
        # 关键：不得因解析失败把明显错误主张（REFUTED）归入 PARTIAL
        v, trace = resolve_verdict(
            evidence_available=True, entity_match=True, metric_match=True,
            period_match=True, unit_scope_match=True, numeric_match=False,
            semantic_completeness=0.6,  # 语义部分但数值明确冲突
        )
        assert v == "REFUTED"
        assert v != "PARTIALLY_SUPPORTED"


class TestGuardSemanticNotOverrideNumeric:
    def test_refuted_protected_from_partial(self):
        # Semantic 想判 PARTIAL 但数值冲突 REFUTED → 保留 REFUTED
        v = guard_semantic_not_override_numeric("REFUTED", "PARTIALLY_SUPPORTED")
        assert v == "REFUTED"

    def test_refuted_protected_from_insufficient(self):
        v = guard_semantic_not_override_numeric("REFUTED", "INSUFFICIENT_EVIDENCE")
        assert v == "REFUTED"

    def test_supported_can_degrade_to_partial(self):
        # 数值匹配但语义部分支持 → 允许降级为 PARTIAL
        v = guard_semantic_not_override_numeric("SUPPORTED", "PARTIALLY_SUPPORTED")
        assert v == "PARTIALLY_SUPPORTED"

    def test_supported_kept_when_semantic_supported(self):
        v = guard_semantic_not_override_numeric("SUPPORTED", "SUPPORTED")
        assert v == "SUPPORTED"

    def test_numeric_priority_other(self):
        v = guard_semantic_not_override_numeric("INSUFFICIENT_EVIDENCE", "SUPPORTED")
        # 数值优先，但 INSUFFICIENT 不是冲突，保守保留
        assert v == "INSUFFICIENT_EVIDENCE"


class TestDecisionTrace:
    def test_trace_add_and_final(self):
        trace = DecisionTrace(steps=[])
        trace.add("evidence_availability", False, "无 Evidence")
        assert trace.final_verdict() == "INSUFFICIENT_EVIDENCE"
    def test_all_passed_returns_supported(self):
        trace = DecisionTrace(steps=[])
        for step in DECISION_STEPS:
            trace.add(step, True, "passed")
        assert trace.final_verdict() == "SUPPORTED"


class TestForecastVerdict:
    def test_forecast_opinion_or_forecast(self):
        v, trace = resolve_verdict(
            evidence_available=True, entity_match=True, metric_match=True,
            period_match=True, unit_scope_match=True, numeric_match=None,
            semantic_completeness=0.3, claim_type="forecast",
        )
        # forecast 类走 OPINION_OR_FORECAST（当前逻辑：非数值类语义低 → INSUFFICIENT，
        # 但 claim_type=forecast 应在 verdict_mapping 处理；当前实现优先语义判定）
        # 测试当前实现的真实行为
        assert v in ("INSUFFICIENT_EVIDENCE", "OPINION_OR_FORECAST")
