"""金融事实核验引擎（Phase 4B.1）——基础定义与数值工具。

架构：Deterministic Verification Engine + Agent Explanation Layer。
- 本模块为纯规则/确定性计算核验（不依赖 LLM 自由判断）；
- 数值工具复用证据检索引擎的单位换算能力；
- 禁止读取 gold_verifications / gold 答案作为推理输入。
"""

from dataclasses import dataclass, field

# verification_status 枚举
STATUS_SUPPORTED = "SUPPORTED"
STATUS_REFUTED = "REFUTED"
STATUS_PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
STATUS_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
STATUS_UNABLE = "UNABLE_TO_DETERMINE"

VERIFICATION_STATUSES = {
    STATUS_SUPPORTED,
    STATUS_REFUTED,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_INSUFFICIENT,
    STATUS_UNABLE,
}

# verification_type 枚举
TYPE_EXACT_VALUE = "EXACT_VALUE_CHECK"
TYPE_GROWTH_RATE = "GROWTH_RATE_CHECK"
TYPE_PERIOD = "PERIOD_CHECK"
TYPE_MULTI_EVIDENCE = "MULTI_EVIDENCE_CHECK"
TYPE_SEMANTIC = "SEMANTIC_CHECK"
# Phase 4B.2：语义核验新类型
TYPE_SEMANTIC_SUPPORT = "SEMANTIC_SUPPORT_CHECK"
TYPE_CAUSAL = "CAUSAL_CHECK"
TYPE_COMPARISON = "COMPARISON_CHECK"
TYPE_SUFFICIENCY = "EVIDENCE_SUFFICIENCY_CHECK"

VERIFICATION_TYPES = {
    TYPE_EXACT_VALUE,
    TYPE_GROWTH_RATE,
    TYPE_PERIOD,
    TYPE_MULTI_EVIDENCE,
    TYPE_SEMANTIC,
    TYPE_SEMANTIC_SUPPORT,
    TYPE_CAUSAL,
    TYPE_COMPARISON,
    TYPE_SUFFICIENCY,
}

# 增长率允许误差（±0.5 个百分点）
GROWTH_TOLERANCE_PP = 0.5
# 数值相对容差（对齐证据检索）
VALUE_TOLERANCE = 0.005


@dataclass
class VerificationResult:
    claim_id: str
    verification_status: str
    confidence: float = 0.0
    verification_type: str = TYPE_EXACT_VALUE
    matched_evidence_ids: list = field(default_factory=list)
    calculation_detail: dict | None = None
    reason: str = ""
    # Phase 23.7：结构化诊断字段（诊断脚本依赖，不再从 reason 文本解析）
    rule_id: str | None = None
    calculated_value: float | None = None

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "verification_status": self.verification_status,
            "confidence": round(self.confidence, 4),
            "verification_type": self.verification_type,
            "matched_evidence_ids": self.matched_evidence_ids,
            "calculation_detail": self.calculation_detail,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "calculated_value": self.calculated_value,
        }


def claim_value_of(claim: dict) -> tuple[float | None, str | None]:
    """主张数值与单位（兼容 reported_value/value、unit）。"""
    v = claim.get("reported_value")
    if v is None:
        v = claim.get("value")
    return v, claim.get("unit")


def claim_text_of(claim: dict) -> str:
    return claim.get("original_text") or claim.get("source_text") or ""
