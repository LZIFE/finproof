"""FinProof Red Team Schemas（Phase 14）。

金融 AI 可靠性测试模块：自动生成金融 AI 常见错误，调用已有核验链路检测。

数据结构：
- AttackCase          攻击案例（original_claim / attacked_claim / attack_type / expected_risk）
- DetectionResult     检测结果（detected / error_type / evidence / risk_score）
- ReliabilityScore    可靠性评分（FinProof Score + 维度）
- StressTestResult    压力测试结果（多攻击案例汇总）
- RedTeamRun          Red Team 运行（cases / detection_results / metrics / reliability_score）

攻击类型（任务书 §2）：
- NUMERIC_HALLUCINATION    数字幻觉
- PERIOD_CONFUSION         期间混淆
- GROWTH_ERROR             增长错误
- UNSUPPORTED_STRATEGIC    无证据战略主张
- FORECAST_AS_FACT         预测被描述为事实

约束（任务书）：不修改已有核心模块；保持 Evidence First。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 攻击类型（任务书 §2）
# ---------------------------------------------------------------------------
ATTACK_NUMERIC_HALLUCINATION = "NUMERIC_HALLUCINATION"
ATTACK_PERIOD_CONFUSION = "PERIOD_CONFUSION"
ATTACK_GROWTH_ERROR = "GROWTH_ERROR"
ATTACK_UNSUPPORTED_STRATEGIC = "UNSUPPORTED_STRATEGIC"
ATTACK_FORECAST_AS_FACT = "FORECAST_AS_FACT"

ATTACK_TYPES = {
    ATTACK_NUMERIC_HALLUCINATION,
    ATTACK_PERIOD_CONFUSION,
    ATTACK_GROWTH_ERROR,
    ATTACK_UNSUPPORTED_STRATEGIC,
    ATTACK_FORECAST_AS_FACT,
}

ATTACK_LABELS = {
    ATTACK_NUMERIC_HALLUCINATION: "数字幻觉",
    ATTACK_PERIOD_CONFUSION: "期间混淆",
    ATTACK_GROWTH_ERROR: "增长错误",
    ATTACK_UNSUPPORTED_STRATEGIC: "无证据战略主张",
    ATTACK_FORECAST_AS_FACT: "预测当事实",
}


# ---------------------------------------------------------------------------
# 错误类型（检测输出，任务书 §3）
# ---------------------------------------------------------------------------
ERROR_NUMERIC_MISMATCH = "NUMERIC_MISMATCH"
ERROR_PERIOD_MISMATCH = "PERIOD_MISMATCH"
ERROR_GROWTH_MISMATCH = "GROWTH_MISMATCH"
ERROR_UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
ERROR_FORECAST_AS_FACT = "FORECAST_AS_FACT"
ERROR_NONE = "NONE"


# ---------------------------------------------------------------------------
# AttackCase（任务书 §2 输出）
# ---------------------------------------------------------------------------
@dataclass
class AttackCase:
    """攻击案例：原始主张 + 被攻击主张 + 攻击类型 + 预期风险。"""

    case_id: str  # ATC-XXXXX
    original_claim: str  # 真实主张
    attacked_claim: str  # 被攻击后的主张
    attack_type: str  # ATTACK_TYPES
    expected_risk: float = 0.0  # 预期风险分（FinProof 应检测到）
    company: str = ""
    stock_code: str = ""
    metric: str = ""  # 关联指标
    original_value: float | None = None  # 真实数值
    attacked_value: float | None = None  # 被攻击后数值
    period_original: str = ""  # 真实期间
    period_attacked: str = ""  # 被攻击期间

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "original_claim": self.original_claim,
            "attacked_claim": self.attacked_claim,
            "attack_type": self.attack_type,
            "expected_risk": self.expected_risk,
            "company": self.company,
            "stock_code": self.stock_code,
            "metric": self.metric,
            "original_value": self.original_value,
            "attacked_value": self.attacked_value,
            "period_original": self.period_original,
            "period_attacked": self.period_attacked,
        }


# ---------------------------------------------------------------------------
# DetectionResult（任务书 §3 输出）
# ---------------------------------------------------------------------------
@dataclass
class DetectionResult:
    """幻觉检测结果。"""

    case_id: str
    detected: bool = False  # FinProof 是否检测到攻击
    error_type: str = ERROR_NONE  # 检测到的错误类型
    evidence: list[dict] = field(default_factory=list)  # 引用证据
    risk_score: float = 0.0  # 风险分
    verification_status: str = ""  # 核验结论
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "detected": self.detected,
            "error_type": self.error_type,
            "evidence_count": len(self.evidence),
            "evidence": self.evidence[:3],  # 仅展示前 3 条
            "risk_score": round(self.risk_score, 1),
            "verification_status": self.verification_status,
            "confidence": round(self.confidence, 3),
        }


# ---------------------------------------------------------------------------
# ReliabilityScore（任务书 §5 FinProof Reliability Score）
# ---------------------------------------------------------------------------
@dataclass
class ReliabilityDimension:
    """可靠性维度。"""

    name: str  # EVIDENCE_GROUNDING / NUMERIC_ACCURACY / PERIOD_ACCURACY / RISK_DETECTION
    score: float = 0.0  # 0-100
    weight: float = 0.25  # 权重

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "weight": self.weight,
        }


@dataclass
class ReliabilityScore:
    """FinProof Reliability Score（任务书 §5）。"""

    finproof_score: float = 0.0  # 0-100
    dimensions: list[ReliabilityDimension] = field(default_factory=list)
    grade: str = "F"  # A/B/C/D/F 等级
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "finproof_score": round(self.finproof_score, 1),
            "dimensions": [d.to_dict() for d in self.dimensions],
            "grade": self.grade,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# StressTestResult / RedTeamRun（任务书 §4）
# ---------------------------------------------------------------------------
@dataclass
class StressTestMetrics:
    """压力测试指标。"""

    total_cases: int = 0
    detected_cases: int = 0  # FinProof 检测到的攻击案例数
    detection_accuracy: float = 0.0  # 检测准确率
    recall: float = 0.0  # 召回率（应检测的攻击中被检测比例）
    precision: float = 0.0  # 精确率
    category_recall: dict[str, float] = field(default_factory=dict)  # 按攻击类型召回率

    def to_dict(self) -> dict:
        return {
            "total_cases": self.total_cases,
            "detected_cases": self.detected_cases,
            "detection_accuracy": round(self.detection_accuracy, 3),
            "recall": round(self.recall, 3),
            "precision": round(self.precision, 3),
            "category_recall": {k: round(v, 3) for k, v in self.category_recall.items()},
        }


@dataclass
class RedTeamRun:
    """Red Team 运行：攻击生成 → 检测 → 评分 → 持久化。"""

    run_id: str = ""  # RT-RUN-XXXX
    total_cases: int = 0
    cases: list[AttackCase] = field(default_factory=list)
    detection_results: list[DetectionResult] = field(default_factory=list)
    metrics: StressTestMetrics = field(default_factory=StressTestMetrics)
    reliability_score: ReliabilityScore = field(default_factory=ReliabilityScore)
    attack_distribution: dict[str, int] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "total_cases": self.total_cases,
            "cases": [c.to_dict() for c in self.cases],
            "detection_results": [d.to_dict() for d in self.detection_results],
            "metrics": self.metrics.to_dict(),
            "reliability_score": self.reliability_score.to_dict(),
            "attack_distribution": self.attack_distribution,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def risk_level_of(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"


def grade_of(score: float) -> str:
    """FinProof Score → 等级。"""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


__all__ = [
    # 攻击类型
    "ATTACK_NUMERIC_HALLUCINATION",
    "ATTACK_PERIOD_CONFUSION",
    "ATTACK_GROWTH_ERROR",
    "ATTACK_UNSUPPORTED_STRATEGIC",
    "ATTACK_FORECAST_AS_FACT",
    "ATTACK_TYPES",
    "ATTACK_LABELS",
    # 错误类型
    "ERROR_NUMERIC_MISMATCH",
    "ERROR_PERIOD_MISMATCH",
    "ERROR_GROWTH_MISMATCH",
    "ERROR_UNSUPPORTED_CLAIM",
    "ERROR_FORECAST_AS_FACT",
    "ERROR_NONE",
    # 数据类
    "AttackCase",
    "DetectionResult",
    "ReliabilityDimension",
    "ReliabilityScore",
    "StressTestMetrics",
    "RedTeamRun",
    # 工具
    "_now_iso",
    "risk_level_of",
    "grade_of",
]
