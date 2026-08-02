"""Financial AI Benchmark Schemas（Phase 11）。

金融 AI 可信度评测基准：评估 AI 生成金融内容的错误检测能力。

数据结构：
- BenchmarkCase       评测案例（claim/category/gold_evidence/gold_result/risk_type）
- ErrorType            错误类型（FINANCIAL_ERROR/PERIOD_ERROR/GROWTH_ERROR/
                              SEMANTIC_OVERSTATEMENT/COMPETITIVE_CLAIM/CAUSAL_ERROR）
- BenchmarkMetrics     评测指标（Accuracy/Precision/Recall/F1/
                              Evidence Coverage/Risk Detection Rate）
- ModelResult          单模型评测结果
- BenchmarkReport      评测报告（含 FinProof vs Baseline LLM 对比）

设计约束（任务书）：
- 不修改已有核心模块（Verification / Risk / Knowledge Graph / Audit / Committee）；
- Benchmark 作为新增层，调用已有 Verification/Risk 能力进行评测。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Error Type（任务书 §2）：6 类错误
# ---------------------------------------------------------------------------
ERROR_FINANCIAL_ERROR = "FINANCIAL_ERROR"  # 财务数据错误
ERROR_PERIOD_ERROR = "PERIOD_ERROR"  # 期间错误
ERROR_GROWTH_ERROR = "GROWTH_ERROR"  # 增长逻辑错误
ERROR_SEMANTIC_OVERSTATEMENT = "SEMANTIC_OVERSTATEMENT"  # 语义夸大
ERROR_COMPETITIVE_CLAIM = "COMPETITIVE_CLAIM"  # 竞争优势主张缺证据
ERROR_CAUSAL_ERROR = "CAUSAL_ERROR"  # 因果归因错误

ERROR_TYPES = {
    ERROR_FINANCIAL_ERROR,
    ERROR_PERIOD_ERROR,
    ERROR_GROWTH_ERROR,
    ERROR_SEMANTIC_OVERSTATEMENT,
    ERROR_COMPETITIVE_CLAIM,
    ERROR_CAUSAL_ERROR,
}

ERROR_LABELS = {
    ERROR_FINANCIAL_ERROR: "财务数据错误",
    ERROR_PERIOD_ERROR: "期间错误",
    ERROR_GROWTH_ERROR: "增长逻辑错误",
    ERROR_SEMANTIC_OVERSTATEMENT: "语义夸大",
    ERROR_COMPETITIVE_CLAIM: "竞争优势主张",
    ERROR_CAUSAL_ERROR: "因果归因错误",
}

# ---------------------------------------------------------------------------
# Gold Result：金标准核验结论
# ---------------------------------------------------------------------------
GOLD_REFUTED = "REFUTED"  # AI 内容有错，应反驳
GOLD_PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"  # 部分支持（含错）
GOLD_SUPPORTED = "SUPPORTED"  # AI 内容正确，应支持
GOLD_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"  # 证据不足

GOLD_RESULTS = {
    GOLD_REFUTED,
    GOLD_PARTIALLY_SUPPORTED,
    GOLD_SUPPORTED,
    GOLD_INSUFFICIENT,
}

# 错误案例的金标准：REFUTED / PARTIALLY_SUPPORTED 视为"含错"
ERROR_GOLD_RESULTS = {GOLD_REFUTED, GOLD_PARTIALLY_SUPPORTED}


# ---------------------------------------------------------------------------
# BenchmarkCase：评测案例
# ---------------------------------------------------------------------------
@dataclass
class BenchmarkCase:
    """评测案例：AI 生成的金融主张 + 金标准结论。

    字段（任务书 §2）：
    - claim          AI 生成的金融主张文本
    - category       错误类型（ERROR_TYPES）
    - gold_evidence  金标准证据（list[dict]，每条含 source/text/page）
    - gold_result    金标准核验结论（GOLD_RESULTS）
    - risk_type      风险类型（与 Phase 6/7 口径一致）
    """

    case_id: str  # CASE-XXXXX
    claim: str  # AI 生成的金融主张
    category: str  # ERROR_TYPES
    company: str = ""  # 关联公司
    stock_code: str = ""
    report_period: str = ""

    # 金标准字段
    gold_evidence: list[dict] = field(default_factory=list)  # [{source, text, page}]
    gold_result: str = ""  # GOLD_RESULTS
    gold_risk_score: float = 0.0  # 金标准风险分 0-100
    risk_type: str = ""  # 风险类型

    # 题设属性
    is_error_case: bool = True  # 是否含错案例（REFUTED/PARTIALLY）
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "claim": self.claim,
            "category": self.category,
            "company": self.company,
            "stock_code": self.stock_code,
            "report_period": self.report_period,
            "gold_evidence": self.gold_evidence,
            "gold_result": self.gold_result,
            "gold_risk_score": self.gold_risk_score,
            "risk_type": self.risk_type,
            "is_error_case": self.is_error_case,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# CaseResult：单案例评测结果
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    """单案例在某模型下的评测结果。"""

    case_id: str
    model: str  # FINPROOF / BASELINE_LLM
    predicted_result: str = ""  # 模型预测的核验结论
    predicted_risk_score: float = 0.0
    predicted_risk_type: str = ""
    detected_error: bool = False  # 是否检测到错误
    evidence_coverage: float = 0.0  # 0-1，证据覆盖率
    response_text: str = ""  # 模型原始响应
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "model": self.model,
            "predicted_result": self.predicted_result,
            "predicted_risk_score": round(self.predicted_risk_score, 1),
            "predicted_risk_type": self.predicted_risk_type,
            "detected_error": self.detected_error,
            "evidence_coverage": round(self.evidence_coverage, 3),
            "response_text": self.response_text,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# BenchmarkMetrics：评测指标（任务书 §3）
# ---------------------------------------------------------------------------
@dataclass
class BenchmarkMetrics:
    """评测指标：Accuracy/Precision/Recall/F1/Coverage/RiskDetectionRate。"""

    total_cases: int = 0
    # 错误检测指标（以 is_error_case 为金标准）
    accuracy: float = 0.0  # 准确率：正确分类比例
    precision: float = 0.0  # 精确率：检测到的错误中真错误比例
    recall: float = 0.0  # 召回率：真错误中被检测比例
    f1: float = 0.0  # F1 分数
    evidence_coverage: float = 0.0  # 证据覆盖率：平均证据覆盖
    risk_detection_rate: float = 0.0  # 风险检测率：高风险案例被检出比例

    # 分错误类别的召回率（便于前端 Error Distribution）
    recall_by_category: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_cases": self.total_cases,
            "accuracy": round(self.accuracy, 3),
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "evidence_coverage": round(self.evidence_coverage, 3),
            "risk_detection_rate": round(self.risk_detection_rate, 3),
            "recall_by_category": {k: round(v, 3) for k, v in self.recall_by_category.items()},
        }


# ---------------------------------------------------------------------------
# ModelResult：单模型评测结果
# ---------------------------------------------------------------------------
@dataclass
class ModelResult:
    """单模型评测结果：含指标与逐案例结果。"""

    model: str  # FINPROOF / BASELINE_LLM
    metrics: BenchmarkMetrics = field(default_factory=BenchmarkMetrics)
    case_results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "metrics": self.metrics.to_dict(),
            "case_results": [c.to_dict() for c in self.case_results],
        }


# ---------------------------------------------------------------------------
# BenchmarkReport：评测报告（含 FinProof vs Baseline 对比）
# ---------------------------------------------------------------------------
@dataclass
class BenchmarkReport:
    """评测报告：含多模型对比与错误分布。"""

    id: int | None = None
    run_id: str = ""  # RUN-XXXXX
    dataset_name: str = ""
    total_cases: int = 0
    models: list[str] = field(default_factory=list)  #参与评测的模型列表
    model_results: list[ModelResult] = field(default_factory=list)

    # 错误分布
    error_distribution: dict[str, int] = field(default_factory=dict)  # category → case_count

    # 对比摘要
    comparison: dict = field(default_factory=dict)  # FinProof vs Baseline 关键指标差

    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "dataset_name": self.dataset_name,
            "total_cases": self.total_cases,
            "models": self.models,
            "model_results": [m.to_dict() for m in self.model_results],
            "error_distribution": self.error_distribution,
            "comparison": self.comparison,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def risk_level_of(score: float) -> str:
    """风险分 → Level（与 Phase 6/7/8/9/10 阈值一致）。"""
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"


__all__ = [
    # Error Type
    "ERROR_FINANCIAL_ERROR",
    "ERROR_PERIOD_ERROR",
    "ERROR_GROWTH_ERROR",
    "ERROR_SEMANTIC_OVERSTATEMENT",
    "ERROR_COMPETITIVE_CLAIM",
    "ERROR_CAUSAL_ERROR",
    "ERROR_TYPES",
    "ERROR_LABELS",
    # Gold Result
    "GOLD_REFUTED",
    "GOLD_PARTIALLY_SUPPORTED",
    "GOLD_SUPPORTED",
    "GOLD_INSUFFICIENT",
    "GOLD_RESULTS",
    "ERROR_GOLD_RESULTS",
    # 数据类
    "BenchmarkCase",
    "CaseResult",
    "BenchmarkMetrics",
    "ModelResult",
    "BenchmarkReport",
    # 工具
    "_now_iso",
    "risk_level_of",
]
