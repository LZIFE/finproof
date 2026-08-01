"""FinProof Financial Reasoning Engine Schemas（Phase 16）。

新增可解释金融推理层：识别多证据之间的逻辑关系、隐含假设和结论跳跃。

不得替代 Verification；不输出投资建议、自动估值或交易功能。

推理类型（任务书 §1）：
- METRIC_SUBSTITUTION          收入增长被写成利润增长
- PERIOD_SUBSTITUTION          Q1/H1/FY 口径偷换
- CORRELATION_AS_CAUSATION     相关性被写成因果
- REVENUE_PROFIT_CONFUSION     收入贡献被写成利润贡献
- GROWTH_QUALITY_RISK          收入增长但利润率/现金流恶化
- BASE_EFFECT_RISK             低基数导致高增长率
- SELECTIVE_EVIDENCE           只引用支持材料，忽略反证
- HIDDEN_ASSUMPTION            结论依赖未披露假设
- CONCLUSION_OVERREACH         证据只能支持弱结论，报告使用强结论
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Reasoning Types（任务书 §1）
# ---------------------------------------------------------------------------
RT_METRIC_SUBSTITUTION = "METRIC_SUBSTITUTION"
RT_PERIOD_SUBSTITUTION = "PERIOD_SUBSTITUTION"
RT_CORRELATION_AS_CAUSATION = "CORRELATION_AS_CAUSATION"
RT_REVENUE_PROFIT_CONFUSION = "REVENUE_PROFIT_CONFUSION"
RT_GROWTH_QUALITY_RISK = "GROWTH_QUALITY_RISK"
RT_BASE_EFFECT_RISK = "BASE_EFFECT_RISK"
RT_SELECTIVE_EVIDENCE = "SELECTIVE_EVIDENCE"
RT_HIDDEN_ASSUMPTION = "HIDDEN_ASSUMPTION"
RT_CONCLUSION_OVERREACH = "CONCLUSION_OVERREACH"

REASONING_TYPES = {
    RT_METRIC_SUBSTITUTION,
    RT_PERIOD_SUBSTITUTION,
    RT_CORRELATION_AS_CAUSATION,
    RT_REVENUE_PROFIT_CONFUSION,
    RT_GROWTH_QUALITY_RISK,
    RT_BASE_EFFECT_RISK,
    RT_SELECTIVE_EVIDENCE,
    RT_HIDDEN_ASSUMPTION,
    RT_CONCLUSION_OVERREACH,
}

REASONING_LABELS = {
    RT_METRIC_SUBSTITUTION: "指标偷换",
    RT_PERIOD_SUBSTITUTION: "期间口径偷换",
    RT_CORRELATION_AS_CAUSATION: "相关性写成因果",
    RT_REVENUE_PROFIT_CONFUSION: "收入贡献写成利润贡献",
    RT_GROWTH_QUALITY_RISK: "增长质量风险",
    RT_BASE_EFFECT_RISK: "低基数高增长",
    RT_SELECTIVE_EVIDENCE: "选择性引用证据",
    RT_HIDDEN_ASSUMPTION: "隐含未披露假设",
    RT_CONCLUSION_OVERREACH: "结论过度跳跃",
}


# ---------------------------------------------------------------------------
# 推理状态（任务书 §3）
# ---------------------------------------------------------------------------
STATUS_OK = "OK"  # 逻辑成立
STATUS_ASSUMPTION_UNVERIFIED = "ASSUMPTION_UNVERIFIED"  # 缺少必要前提
STATUS_MIXED_EVIDENCE = "MIXED_EVIDENCE"  # 同时存在支持证据与反证
STATUS_LOGICAL_GAP = "LOGICAL_GAP"  # 存在逻辑缺口
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # 缺数据，不得强行判断
STATUS_UNSUPPORTED = "UNSUPPORTED"  # 证据不支持该结论

REASONING_STATUS = {
    STATUS_OK,
    STATUS_ASSUMPTION_UNVERIFIED,
    STATUS_MIXED_EVIDENCE,
    STATUS_LOGICAL_GAP,
    STATUS_INSUFFICIENT_DATA,
    STATUS_UNSUPPORTED,
}


# ---------------------------------------------------------------------------
# 增长质量（任务书 §4）
# ---------------------------------------------------------------------------
GQ_HIGH_QUALITY = "HIGH_QUALITY_GROWTH"
GQ_MIXED_QUALITY = "MIXED_QUALITY_GROWTH"
GQ_LOW_QUALITY = "LOW_QUALITY_GROWTH"
GQ_INSUFFICIENT = "INSUFFICIENT_DATA"

GROWTH_QUALITY_LEVELS = {GQ_HIGH_QUALITY, GQ_MIXED_QUALITY, GQ_LOW_QUALITY, GQ_INSUFFICIENT}


# ---------------------------------------------------------------------------
# ReasoningInput（任务书 §2 输入）
# ---------------------------------------------------------------------------
@dataclass
class ReasoningInput:
    """推理输入：claim / verification / evidence / KG facts / risk。"""

    claim_text: str = ""
    claim: dict = field(default_factory=dict)
    verification_result: dict = field(default_factory=dict)
    evidence_candidates: list[dict] = field(default_factory=list)
    knowledge_graph_facts: list[dict] = field(default_factory=list)
    risk_assessment: dict = field(default_factory=dict)
    company: str = ""
    period: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_text": self.claim_text,
            "claim": self.claim,
            "verification_result": self.verification_result,
            "evidence_candidates": self.evidence_candidates,
            "knowledge_graph_facts": self.knowledge_graph_facts,
            "risk_assessment": self.risk_assessment,
            "company": self.company,
            "period": self.period,
        }


# ---------------------------------------------------------------------------
# ReasoningResult（任务书 §2 输出）
# ---------------------------------------------------------------------------
@dataclass
class ReasoningResult:
    """推理结果。

    任务书 §2 必须包含：
    - reasoning_type / status / premises / supporting_evidence / counter_evidence
    - assumptions / logical_gap / confidence / explanation / suggested_safe_wording

    `suggested_safe_wording` 只能降低表达强度，不得生成投资观点。
    """

    result_id: str = ""  # RR-XXXX
    run_id: str = ""  # REASON-RUN-XXXX（关联推理运行）
    reasoning_type: str = ""  # REASONING_TYPES
    status: str = STATUS_OK
    premises: list[str] = field(default_factory=list)  # 已识别前提
    supporting_evidence: list[dict] = field(default_factory=list)  # 支持证据（含 evidence_id）
    counter_evidence: list[dict] = field(default_factory=list)  # 反证
    assumptions: list[str] = field(default_factory=list)  # �隐含假设（未披露）
    logical_gap: str = ""  # 逻辑缺口描述
    confidence: float = 0.0
    explanation: str = ""  # 可解释说明
    suggested_safe_wording: str = ""  # 安全措辞（仅降低强度，不含投资观点）
    triggered_rules: list[str] = field(default_factory=list)  # 触发规则ID
    evidence_ids: list[str] = field(default_factory=list)  # 引用证据ID
    rule_version: str = "r2025-phase16"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "run_id": self.run_id,
            "reasoning_type": self.reasoning_type,
            "status": self.status,
            "premises": self.premises,
            "supporting_evidence": self.supporting_evidence,
            "counter_evidence": self.counter_evidence,
            "assumptions": self.assumptions,
            "logical_gap": self.logical_gap,
            "confidence": round(self.confidence, 3),
            "explanation": self.explanation,
            "suggested_safe_wording": self.suggested_safe_wording,
            "triggered_rules": self.triggered_rules,
            "evidence_ids": self.evidence_ids,
            "rule_version": self.rule_version,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# GrowthQualityResult（任务书 §4）
# ---------------------------------------------------------------------------
@dataclass
class GrowthIndicator:
    """增长类主张单项指标。"""

    name: str  # revenue / net_profit / gross_margin / operating_cash_flow / receivables / inventory
    value: float | None = None
    direction: str = "UNKNOWN"  # UP / DOWN / FLAT / UNKNOWN
    evidence_id: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "direction": self.direction,
            "evidence_id": self.evidence_id,
        }


@dataclass
class GrowthQualityResult:
    """增长质量评估（任务书 §4）。"""

    quality: str = GQ_INSUFFICIENT  # GROWTH_QUALITY_LEVELS
    indicators: list[GrowthIndicator] = field(default_factory=list)
    reason: str = ""
    supporting_evidence: list[dict] = field(default_factory=list)
    counter_evidence: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "quality": self.quality,
            "indicators": [i.to_dict() for i in self.indicators],
            "reason": self.reason,
            "supporting_evidence": self.supporting_evidence,
            "counter_evidence": self.counter_evidence,
        }


# ---------------------------------------------------------------------------
# Contradiction（任务书 §5）
# ---------------------------------------------------------------------------
@dataclass
class Contradiction:
    """冲突：双方 / 来源 / 期间 / 指标 / 原因。"""

    party_a: str = ""
    party_b: str = ""
    source_a: str = ""
    source_b: str = ""
    period_a: str = ""
    period_b: str = ""
    metric: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "party_a": self.party_a,
            "party_b": self.party_b,
            "source_a": self.source_a,
            "source_b": self.source_b,
            "period_a": self.period_a,
            "period_b": self.period_b,
            "metric": self.metric,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# ReasoningRun（任务书 §6）
# ---------------------------------------------------------------------------
@dataclass
class ReasoningRun:
    """推理运行：多结果汇总。"""

    run_id: str = ""  # REASON-RUN-XXXX
    claim_text: str = ""
    input_ref: dict = field(default_factory=dict)  # 输入引用
    results: list[ReasoningResult] = field(default_factory=list)
    rule_version: str = "r2025-phase16"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "claim_text": self.claim_text,
            "input_ref": self.input_ref,
            "results": [r.to_dict() for r in self.results],
            "rule_version": self.rule_version,
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


__all__ = [
    # Reasoning Types
    "RT_METRIC_SUBSTITUTION",
    "RT_PERIOD_SUBSTITUTION",
    "RT_CORRELATION_AS_CAUSATION",
    "RT_REVENUE_PROFIT_CONFUSION",
    "RT_GROWTH_QUALITY_RISK",
    "RT_BASE_EFFECT_RISK",
    "RT_SELECTIVE_EVIDENCE",
    "RT_HIDDEN_ASSUMPTION",
    "RT_CONCLUSION_OVERREACH",
    "REASONING_TYPES",
    "REASONING_LABELS",
    # Status
    "STATUS_OK",
    "STATUS_ASSUMPTION_UNVERIFIED",
    "STATUS_MIXED_EVIDENCE",
    "STATUS_LOGICAL_GAP",
    "STATUS_INSUFFICIENT_DATA",
    "STATUS_UNSUPPORTED",
    "REASONING_STATUS",
    # Growth Quality
    "GQ_HIGH_QUALITY",
    "GQ_MIXED_QUALITY",
    "GQ_LOW_QUALITY",
    "GQ_INSUFFICIENT",
    "GROWTH_QUALITY_LEVELS",
    # Data classes
    "ReasoningInput",
    "ReasoningResult",
    "GrowthIndicator",
    "GrowthQualityResult",
    "Contradiction",
    "ReasoningRun",
    # 工具
    "_now_iso",
    "risk_level_of",
]
