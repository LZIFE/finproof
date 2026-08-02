"""Phase 23.8 明确四类 Verdict 边界与决策顺序。

四类 Verdict 统一定义：
- SUPPORTED：Evidence 直接支持主张的主体/指标/期间/单位/口径/数值，允许正常舍入误差
- REFUTED：Evidence 明确给出冲突事实/错误数值/错误期间/错误单位/相反方向
- PARTIALLY_SUPPORTED：主张含多个组成部分，部分得到支持但关键部分缺失，
  或 Evidence 仅支持较弱表述
- INSUFFICIENT_EVIDENCE：现有 Evidence 不能证明也不能反驳，
  不得因解析失败直接把明显错误主张归入 PARTIAL

决策顺序（8 步，不得跳过）：
1. Evidence 可用性
2. 实体匹配
3. 指标匹配
4. 期间匹配
5. 单位与口径匹配
6. 数值计算
7. 语义完整度
8. Verdict 映射

不得让 Semantic Verifier 覆盖确定性数值冲突（REFUTED 应优先于 PARTIAL）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Verdict = Literal["SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE",
                  "OPINION_OR_FORECAST", "UNABLE_TO_DETERMINE"]

# 决策步骤顺序（不得跳过）
DECISION_STEPS = (
    "evidence_availability",
    "entity_match",
    "metric_match",
    "period_match",
    "unit_scope_match",
    "numeric_calculation",
    "semantic_completeness",
    "verdict_mapping",
)


@dataclass
class DecisionTrace:
    """决策链追踪（8 步逐步记录）。"""
    steps: list[dict]  # [{step, passed, reason}, ...]

    def add(self, step: str, passed: bool, reason: str) -> None:
        self.steps.append({"step": step, "passed": passed, "reason": reason})

    def final_verdict(self) -> Verdict:
        """根据决策链最后一个 passed 步骤的 reason 推断 verdict。

        若某步 failed 则提前返回该步对应的 verdict（如 evidence_availability failed → INSUFFICIENT）。
        全部 passed 且 semantic_completeness 未覆盖数值冲突 → SUPPORTED。
        """
        for s in self.steps:
            if not s["passed"]:
                return _step_failed_verdict(s["step"])
        # 全部 passed：默认 SUPPORTED（数值已在 step 6 匹配）
        return "SUPPORTED"

    def to_dict(self) -> dict:
        return {"steps": self.steps, "final_verdict": self.final_verdict()}


def _step_failed_verdict(step: str) -> Verdict:
    """某步 failed 时对应的 verdict。"""
    return {
        "evidence_availability": "INSUFFICIENT_EVIDENCE",
        "entity_match": "INSUFFICIENT_EVIDENCE",
        "metric_match": "INSUFFICIENT_EVIDENCE",
        "period_match": "INSUFFICIENT_EVIDENCE",
        "unit_scope_match": "INSUFFICIENT_EVIDENCE",
        "numeric_calculation": "REFUTED",  # 数值冲突 → REFUTED，不让 Semantic 覆盖
        "semantic_completeness": "PARTIALLY_SUPPORTED",
        "verdict_mapping": "UNABLE_TO_DETERMINE",
    }.get(step, "INSUFFICIENT_EVIDENCE")


# ---------------------------------------------------------------------------
# Verdict 边界判定（优先级：REFUTED > SUPPORTED > PARTIAL > INSUFFICIENT）
# ---------------------------------------------------------------------------
def resolve_verdict(
    evidence_available: bool,
    entity_match: bool,
    metric_match: bool,
    period_match: bool,
    unit_scope_match: bool,
    numeric_match: bool | None,       # True=SUPPORTED, False=REFUTED, None=无数值
    semantic_completeness: float,     # 0.0-1.0，语义完整度
    claim_type: str = "raw_number",
) -> tuple[Verdict, DecisionTrace]:
    """按 8 步决策顺序判定 Verdict。

    Phase 23.8 核心：不让 Semantic Verifier 覆盖确定性数值冲突。
    - numeric_match=False（数值冲突）→ REFUTED，即使 semantic_completeness 高也不降级为 PARTIAL
    - numeric_match=True + semantic_completeness≥0.8 → SUPPORTED
    - numeric_match=True + semantic_completeness<0.8 → PARTIALLY_SUPPORTED
    - numeric_match=None（无数值类）→ 依赖 semantic_completeness
    """
    trace = DecisionTrace(steps=[])

    # Step 1: Evidence 可用性
    trace.add("evidence_availability", evidence_available,
              "有 Evidence" if evidence_available else "无可用 Evidence")
    if not evidence_available:
        return "INSUFFICIENT_EVIDENCE", trace

    # Step 2: 实体匹配
    trace.add("entity_match", entity_match,
              "实体匹配" if entity_match else "实体不匹配")
    if not entity_match:
        return "INSUFFICIENT_EVIDENCE", trace

    # Step 3: 指标匹配
    trace.add("metric_match", metric_match,
              "指标匹配" if metric_match else "指标不匹配")
    if not metric_match:
        return "INSUFFICIENT_EVIDENCE", trace

    # Step 4: 期间匹配
    trace.add("period_match", period_match,
              "期间匹配" if period_match else "期间不匹配")
    if not period_match:
        return "INSUFFICIENT_EVIDENCE", trace

    # Step 5: 单位与口径匹配
    trace.add("unit_scope_match", unit_scope_match,
              "单位口径匹配" if unit_scope_match else "单位口径不匹配")
    if not unit_scope_match:
        return "INSUFFICIENT_EVIDENCE", trace

    # Step 6: 数值计算（确定性数值冲突 → REFUTED，不让 Semantic 覆盖）
    if numeric_match is False:
        trace.add("numeric_calculation", False, "数值冲突（REFUTED，不被 Semantic 覆盖）")
        return "REFUTED", trace
    if numeric_match is True:
        trace.add("numeric_calculation", True, "数值匹配")
    else:
        trace.add("numeric_calculation", True, "无数值类主张，跳过数值计算")

    # Step 7: 语义完整度
    if semantic_completeness >= 0.8:
        trace.add("semantic_completeness", True, f"语义完整度 {semantic_completeness:.2f} ≥ 0.8")
    else:
        trace.add("semantic_completeness", False, f"语义完整度 {semantic_completeness:.2f} < 0.8，部分支持")

    # Step 8: Verdict 映射
    # forecast 类特殊处理（优先于语义判定，避免误判为 INSUFFICIENT）
    if claim_type == "forecast":
        trace.add("semantic_completeness", True, f"forecast 类，语义完整度 {semantic_completeness:.2f}")
        trace.add("verdict_mapping", True, "forecast 类 → OPINION_OR_FORECAST")
        return "OPINION_OR_FORECAST", trace

    if numeric_match is True and semantic_completeness >= 0.8:
        trace.add("verdict_mapping", True, "数值匹配 + 语义完整 → SUPPORTED")
        return "SUPPORTED", trace
    if numeric_match is True and semantic_completeness < 0.8:
        trace.add("verdict_mapping", True, "数值匹配但语义不完整 → PARTIALLY_SUPPORTED")
        return "PARTIALLY_SUPPORTED", trace
    if numeric_match is None:
        # 非数值类：语义完整度决定
        if semantic_completeness >= 0.8:
            trace.add("verdict_mapping", True, "非数值类语义完整 → SUPPORTED")
            return "SUPPORTED", trace
        if semantic_completeness > 0:
            trace.add("verdict_mapping", True, "非数值类语义部分 → PARTIALLY_SUPPORTED")
            return "PARTIALLY_SUPPORTED", trace
        trace.add("verdict_mapping", False, "非数值类无语义匹配 → INSUFFICIENT_EVIDENCE")
        return "INSUFFICIENT_EVIDENCE", trace

    return "SUPPORTED", trace


# ---------------------------------------------------------------------------
# 不让 Semantic 覆盖数值冲突的守卫函数
# ---------------------------------------------------------------------------
def guard_semantic_not_override_numeric(
    numeric_verdict: Verdict, semantic_verdict: Verdict
) -> Verdict:
    """守卫：Semantic Verifier 不得覆盖确定性数值冲突。

    规则：
    - 若 numeric_verdict=REFUTED，semantic_verdict=PARTIALLY_SUPPORTED → 保留 REFUTED
    - 若 numeric_verdict=REFUTED，semantic_verdict=INSUFFICIENT → 保留 REFUTED
    - 若 numeric_verdict=SUPPORTED，semantic_verdict 可降级为 PARTIALLY_SUPPORTED（语义不完整）
    - 其他情况取 numeric_verdict（数值优先）
    """
    if numeric_verdict == "REFUTED":
        return "REFUTED"  # 数值冲突优先，不让 Semantic 覆盖
    if numeric_verdict == "SUPPORTED" and semantic_verdict == "PARTIALLY_SUPPORTED":
        return "PARTIALLY_SUPPORTED"  # 数值匹配但语义部分支持，允许降级
    return numeric_verdict


__all__ = [
    "Verdict",
    "DECISION_STEPS",
    "DecisionTrace",
    "resolve_verdict",
    "guard_semantic_not_override_numeric",
]
