"""风险规则（Phase 6）：风险类型分类、评分区间、调整因子。

规则可解释：risk_reason 由每条触发规则生成。
Evidence First：所有评分仅基于 claim_type / verification_result / evidence_quality /
confidence / calculation_detail，不使用 LLM 自由判断。
"""

from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)

# 风险类型
RISK_FINANCIAL = "FINANCIAL_ERROR"
RISK_EVIDENCE = "EVIDENCE_RISK"
RISK_SEMANTIC = "SEMANTIC_RISK"
RISK_FORECAST = "FORECAST_RISK"

RISK_TYPES = {RISK_FINANCIAL, RISK_EVIDENCE, RISK_SEMANTIC, RISK_FORECAST}

# 风险等级
LEVEL_LOW = "LOW"
LEVEL_MEDIUM = "MEDIUM"
LEVEL_HIGH = "HIGH"

# 各验证状态的基准分区间（[base_min, base_max]）
STATUS_RANGES = {
    STATUS_REFUTED: (80.0, 100.0),
    STATUS_PARTIALLY_SUPPORTED: (40.0, 70.0),
    STATUS_INSUFFICIENT: (60.0, 90.0),
    STATUS_UNABLE: (60.0, 90.0),
    STATUS_SUPPORTED: (0.0, 20.0),
}

# 数字类验证类型（触发 FINANCIAL_ERROR）
FINANCIAL_TYPES = {"EXACT_VALUE_CHECK", "GROWTH_RATE_CHECK", "PERIOD_CHECK"}
# 语义类验证类型（触发 SEMANTIC_RISK）
SEMANTIC_TYPES = {"SEMANTIC_SUPPORT_CHECK", "CAUSAL_CHECK", "COMPARISON_CHECK", "SEMANTIC_CHECK"}
# 预测类指标/类型（触发 FORECAST_RISK）
FORECAST_CODES = ("forecast", "yoy_growth", "growth")
FORECAST_CLAIM_TYPES = ("FORECAST", "FORECAST_CLAIM")

# 主张重要性（claim.risk_level / claim_type 推导）→ 分值调整
IMPORTANCE_ADJUST = {"HIGH": 8.0, "MEDIUM": 4.0, "LOW": 0.0}
# 财务数字类主张（重要性更高）
IMPORTANT_CLAIM_TYPES = ("FINANCIAL_VALUE", "GROWTH_RATE", "PERIOD", "RAW_NUMBER", "CALCULATED_FINANCIAL_METRIC")


def classify_risk_type(claim: dict, verification: dict) -> str:
    """风险类型分类：REFUTED+数字→FINANCIAL；FORECAST→FORECAST；PARTIALLY→SEMANTIC；INSUFFICIENT/UNKNOWN→EVIDENCE。"""
    status = verification.get("verification_status")
    vtype = verification.get("verification_type") or ""
    if status == STATUS_REFUTED and vtype in FINANCIAL_TYPES:
        return RISK_FINANCIAL
    if status == STATUS_PARTIALLY_SUPPORTED:
        return RISK_SEMANTIC
    if status in (STATUS_INSUFFICIENT, STATUS_UNABLE):
        return RISK_EVIDENCE
    if status == STATUS_REFUTED:
        return RISK_SEMANTIC if vtype in SEMANTIC_TYPES else RISK_EVIDENCE
    return RISK_EVIDENCE


def is_forecast_claim(claim: dict) -> bool:
    ct = (claim.get("claim_type") or "").upper()
    code = (claim.get("metric_code") or "").lower()
    if ct in FORECAST_CLAIM_TYPES:
        return True
    return any(f in code for f in ("forecast", "future")) or (
        "预计" in str(claim.get("original_text") or "") or "将" in str(claim.get("original_text") or "")
    )


def claim_importance_of(claim: dict) -> str:
    """主张重要性：显式 risk_level 优先；否则按 claim_type（财务数字类 → HIGH）。"""
    rl = (claim.get("risk_level") or "").upper()
    if rl in ("HIGH", "MEDIUM", "LOW"):
        return rl
    ct = (claim.get("claim_type") or "").upper()
    return "HIGH" if ct in IMPORTANT_CLAIM_TYPES else "MEDIUM"


def base_score(status: str) -> float:
    lo, hi = STATUS_RANGES.get(status, (30.0, 60.0))
    return (lo + hi) / 2.0


def score_range(status: str) -> tuple[float, float]:
    return STATUS_RANGES.get(status, (30.0, 60.0))
