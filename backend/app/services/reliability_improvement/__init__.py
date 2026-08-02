"""FinProof AI Reliability Improvement Center Package（Phase 23）。

基于已有 Benchmark / Red Team / Arena 结果，构建 AI 可靠性改进分析层。
**不是修改模型、不是训练模型**，只是分析失败模式并生成改进建议。

约束：不修改已有核心模块；不自动修改模型；不输出投资建议。
"""

from app.services.reliability_improvement.failure_analyzer import collect_failures
from app.services.reliability_improvement.improvement_report import (
    analyze_reliability,
    get_report,
    list_reports,
    persist_report,
)
from app.services.reliability_improvement.pattern_detector import (
    PATTERN_IMPROVEMENT,
    PATTERN_ROOT_CAUSE,
    build_weakness_map,
    detect_patterns,
)
from app.services.reliability_improvement.schemas import (
    SOURCE_ARENA,
    SOURCE_BENCHMARK,
    SOURCE_LABELS,
    SOURCE_REASONING,
    SOURCE_RED_TEAM,
    SOURCE_TYPES,
    PATTERN_EVIDENCE_MISSING,
    PATTERN_LABELS,
    PATTERN_LOGICAL_GAP,
    PATTERN_NUMERIC_ERROR,
    PATTERN_PERIOD_CONFUSION,
    PATTERN_TYPES,
    PATTERN_UNSUPPORTED_CLAIM,
    FailureCase,
    FailurePattern,
    ReliabilityImprovementReport,
    ReliabilityTrend,
    TrendPoint,
    WeaknessCell,
    WeaknessMap,
    contains_forbidden_content,
)

__all__ = [
    # schemas
    "PATTERN_NUMERIC_ERROR", "PATTERN_PERIOD_CONFUSION", "PATTERN_UNSUPPORTED_CLAIM",
    "PATTERN_EVIDENCE_MISSING", "PATTERN_LOGICAL_GAP", "PATTERN_TYPES", "PATTERN_LABELS",
    "SOURCE_BENCHMARK", "SOURCE_RED_TEAM", "SOURCE_ARENA", "SOURCE_REASONING",
    "SOURCE_TYPES", "SOURCE_LABELS",
    "FailureCase", "FailurePattern", "TrendPoint", "ReliabilityTrend",
    "ReliabilityImprovementReport", "WeaknessCell", "WeaknessMap",
    "contains_forbidden_content",
    # analyzer + detector + report
    "collect_failures", "detect_patterns", "build_weakness_map",
    "PATTERN_ROOT_CAUSE", "PATTERN_IMPROVEMENT",
    "analyze_reliability", "persist_report", "get_report", "list_reports",
]
