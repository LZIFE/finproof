"""FinProof Financial Reasoning Engine Package（Phase 16）。

可解释金融推理层：识别多证据之间的逻辑关系、隐含假设和结论跳跃。

模块：
- schemas                 数据结构与常量（9 类 reasoning types + status + growth quality）
- logic_rules             确定性逻辑规则（R001-R009）
- assumption_checker      隐含假设检查（HIDDEN_ASSUMPTION）
- contradiction_reasoner  冲突检测（4 类冲突）
- quality_analyzer        增长质量分析（HIGH/MIXED/LOW/INSUFFICIENT）
- reasoning_service       主调度器（reason_about / get_run / list_runs）

约束：不替代 Verification；不输出投资建议、自动估值或交易功能。
"""

from app.services.financial_reasoning.assumption_checker import check_assumptions
from app.services.financial_reasoning.contradiction_reasoner import (
    contradiction_to_results,
    detect_contradictions,
)
from app.services.financial_reasoning.logic_rules import RULE_VERSION, apply_rules
from app.services.financial_reasoning.quality_analyzer import (
    growth_to_reasoning_result,
    analyze_growth_quality,
)
from app.services.financial_reasoning.reasoning_service import (
    get_run,
    get_run_results,
    list_runs,
    reason_about,
)
from app.services.financial_reasoning.schemas import (
    Contradiction,
    GrowthIndicator,
    GrowthQualityResult,
    ReasoningInput,
    ReasoningResult,
    ReasoningRun,
    REASONING_LABELS,
    REASONING_TYPES,
    REASONING_STATUS,
    GROWTH_QUALITY_LEVELS,
)

__all__ = [
    # schemas
    "Contradiction",
    "GrowthIndicator",
    "GrowthQualityResult",
    "ReasoningInput",
    "ReasoningResult",
    "ReasoningRun",
    "REASONING_LABELS",
    "REASONING_TYPES",
    "REASONING_STATUS",
    "GROWTH_QUALITY_LEVELS",
    # logic_rules
    "RULE_VERSION",
    "apply_rules",
    # assumption
    "check_assumptions",
    # contradiction
    "detect_contradictions",
    "contradiction_to_results",
    # quality
    "analyze_growth_quality",
    "growth_to_reasoning_result",
    # service
    "reason_about",
    "get_run",
    "get_run_results",
    "list_runs",
]
