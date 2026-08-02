"""FinProof AI Reliability Improvement Center Schemas（Phase 23）。

基于已有 Benchmark / Red Team / Arena 结果，构建 AI 可靠性改进分析层。
**不是修改模型、不是训练模型**，只是分析失败模式并生成改进建议。

5 类 Failure Pattern（任务书 §识别）：
    NUMERIC_ERROR          数值错误
    PERIOD_CONFUSION       期间混淆
    UNSUPPORTED_CLAIM      无依据主张
    EVIDENCE_MISSING       证据缺失
    LOGICAL_GAP            逻辑缺口

约束：不修改已有核心模块；不自动修改模型；不输出投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Failure Patterns（任务书 §识别）
# ---------------------------------------------------------------------------
PATTERN_NUMERIC_ERROR = "NUMERIC_ERROR"            # 数值错误
PATTERN_PERIOD_CONFUSION = "PERIOD_CONFUSION"      # 期间混淆
PATTERN_UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"    # 无依据主张
PATTERN_EVIDENCE_MISSING = "EVIDENCE_MISSING"      # 证据缺失
PATTERN_LOGICAL_GAP = "LOGICAL_GAP"                # 逻辑缺口

PATTERN_TYPES = {
    PATTERN_NUMERIC_ERROR,
    PATTERN_PERIOD_CONFUSION,
    PATTERN_UNSUPPORTED_CLAIM,
    PATTERN_EVIDENCE_MISSING,
    PATTERN_LOGICAL_GAP,
}

PATTERN_LABELS = {
    PATTERN_NUMERIC_ERROR: "数值错误",
    PATTERN_PERIOD_CONFUSION: "期间混淆",
    PATTERN_UNSUPPORTED_CLAIM: "无依据主张",
    PATTERN_EVIDENCE_MISSING: "证据缺失",
    PATTERN_LOGICAL_GAP: "逻辑缺口",
}

# 来源模块（任务书 §读取）
SOURCE_BENCHMARK = "benchmark"
SOURCE_RED_TEAM = "red_team"
SOURCE_ARENA = "arena"
SOURCE_REASONING = "reasoning"

SOURCE_TYPES = {SOURCE_BENCHMARK, SOURCE_RED_TEAM, SOURCE_ARENA, SOURCE_REASONING}
SOURCE_LABELS = {
    SOURCE_BENCHMARK: "Benchmark",
    SOURCE_RED_TEAM: "Red Team",
    SOURCE_ARENA: "Agent Arena",
    SOURCE_REASONING: "Reasoning",
}


# ---------------------------------------------------------------------------
# FailureCase：单条失败案例
# ---------------------------------------------------------------------------
@dataclass
class FailureCase:
    """单条失败案例（来自既有 benchmark/red_team/arena/reasoning 结果）。"""

    case_id: str = ""
    source: str = ""          # 来源模块
    pattern: str = ""          # 失败模式（PATTERN_TYPES）
    company: str = ""
    claim: str = ""           # 原始主张/错误内容
    error_detail: str = ""    # 错误详情
    evidence_count: int = 0
    confidence: float = 0.0
    detected_at: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "source": self.source,
            "pattern": self.pattern,
            "company": self.company,
            "claim": self.claim[:200],
            "error_detail": self.error_detail[:200],
            "evidence_count": self.evidence_count,
            "confidence": round(self.confidence, 3),
            "detected_at": self.detected_at,
        }


# ---------------------------------------------------------------------------
# FailurePattern：聚合的失败模式
# ---------------------------------------------------------------------------
@dataclass
class FailurePattern:
    """聚合的失败模式（含 root_cause + suggested_improvement）。"""

    pattern: str = ""          # PATTERN_TYPES
    failure_count: int = 0
    failure_rate: float = 0.0  # 0-1
    affected_category: str = ""  # 受影响类别（来源/场景）
    example_cases: list[FailureCase] = field(default_factory=list)
    root_cause: str = ""
    suggested_improvement: str = ""

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "label": PATTERN_LABELS.get(self.pattern, self.pattern),
            "failure_count": self.failure_count,
            "failure_rate": round(self.failure_rate, 3),
            "affected_category": self.affected_category,
            "example_cases": [c.to_dict() for c in self.example_cases[:5]],
            "root_cause": self.root_cause,
            "suggested_improvement": self.suggested_improvement,
        }


# ---------------------------------------------------------------------------
# ReliabilityTrend：可靠性趋势
# ---------------------------------------------------------------------------
@dataclass
class TrendPoint:
    """趋势点：版本/Agent → score。"""

    label: str = ""           # 版本或 Agent 名
    score: float = 0.0        # 0-100
    samples: int = 0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "score": round(self.score, 2),
            "samples": self.samples,
            "timestamp": self.timestamp,
        }


@dataclass
class ReliabilityTrend:
    """可靠性趋势：不同版本/不同 Agent 表现比较（任务书 §生成 Reliability Trend）。"""

    points: list[TrendPoint] = field(default_factory=list)
    direction: str = ""       # improving / declining / stable
    delta: float = 0.0        # 最新 - 最早

    def to_dict(self) -> dict:
        return {
            "points": [p.to_dict() for p in self.points],
            "direction": self.direction,
            "delta": round(self.delta, 2),
        }


# ---------------------------------------------------------------------------
# ReliabilityImprovementReport（任务书 §生成）
# ---------------------------------------------------------------------------
@dataclass
class ReliabilityImprovementReport:
    """AI 可靠性改进报告。

    包含：failure_count / failure_rate / affected_category / example_cases /
    root_cause / suggested_improvement（按模式聚合）+ Reliability Trend。
    """

    report_id: str = ""
    total_cases: int = 0
    total_failures: int = 0
    overall_failure_rate: float = 0.0
    patterns: list[FailurePattern] = field(default_factory=list)
    trend: ReliabilityTrend = field(default_factory=ReliabilityTrend)
    sources_analyzed: list[str] = field(default_factory=list)
    summary: str = ""
    suggested_improvements: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "total_cases": self.total_cases,
            "total_failures": self.total_failures,
            "overall_failure_rate": round(self.overall_failure_rate, 3),
            "patterns": [p.to_dict() for p in self.patterns],
            "trend": self.trend.to_dict(),
            "sources_analyzed": self.sources_analyzed,
            "summary": self.summary,
            "suggested_improvements": self.suggested_improvements,
            "created_at": self.created_at,
            "pattern_labels": PATTERN_LABELS,
            "source_labels": SOURCE_LABELS,
        }


# ---------------------------------------------------------------------------
# AI Weakness Map（前端 §AI Weakness Map）
# ---------------------------------------------------------------------------
@dataclass
class WeaknessCell:
    """弱点矩阵单元：source × pattern → count。"""

    source: str = ""
    pattern: str = ""
    count: int = 0
    rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "pattern": self.pattern,
            "count": self.count,
            "rate": round(self.rate, 3),
        }


@dataclass
class WeaknessMap:
    """AI 弱点地图：source × pattern 矩阵。"""

    cells: list[WeaknessCell] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    max_count: int = 0

    def to_dict(self) -> dict:
        return {
            "cells": [c.to_dict() for c in self.cells],
            "sources": self.sources,
            "patterns": self.patterns,
            "max_count": self.max_count,
        }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# 禁止词护栏（不输出投资建议）
_FORBIDDEN_KW = (
    "买入", "卖出", "目标价", "建议加仓", "建议减仓", "估值预测",
    "buy", "sell", "target price", "recommendation",
    "推荐股票", "推荐买入", "推荐卖出",
)


def contains_forbidden_content(text: str) -> bool:
    """是否含禁止词（投资建议/股票推荐/估值预测）。

    剥离否定式免责片段后判定，不误伤"不构成...建议/推荐"声明。
    """
    if not text:
        return False
    import re as _re
    stripped = _re.sub(
        r"(不构成|不包含|不含|不输出|不涉及|非|并无|未含|不提供)[^;。；\.]{0,40}",
        "",
        text,
    )
    lowered = stripped.lower()
    strong = ("买入", "卖出", "目标价", "建议加仓", "建议减仓", "估值预测", "buy", "sell", "target price")
    for kw in strong:
        if kw.lower() in lowered:
            return True
    if "推荐买入" in stripped or "推荐卖出" in stripped or "推荐加仓" in stripped or "推荐减仓" in stripped:
        return True
    return False


__all__ = [
    # patterns
    "PATTERN_NUMERIC_ERROR", "PATTERN_PERIOD_CONFUSION", "PATTERN_UNSUPPORTED_CLAIM",
    "PATTERN_EVIDENCE_MISSING", "PATTERN_LOGICAL_GAP",
    "PATTERN_TYPES", "PATTERN_LABELS",
    # sources
    "SOURCE_BENCHMARK", "SOURCE_RED_TEAM", "SOURCE_ARENA", "SOURCE_REASONING",
    "SOURCE_TYPES", "SOURCE_LABELS",
    # data
    "FailureCase", "FailurePattern", "TrendPoint", "ReliabilityTrend",
    "ReliabilityImprovementReport", "WeaknessCell", "WeaknessMap",
    # utils
    "_now_iso", "contains_forbidden_content",
]
