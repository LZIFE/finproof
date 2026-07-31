"""投资风险摘要（Phase 7）：将核验/风险结果按投资风险分类聚合。

分类（基于 claim_type / verification_type / risk_type / risk_score / evidence_quality）：
- FINANCIAL_RISK：财务数字/增长率/指标类风险（FINANCIAL_ERROR 或数字类核验的风险）
- BUSINESS_RISK：业务事实/战略类风险（SEMANTIC_RISK / BUSINESS_FACT / STRATEGIC）
- COMPETITIVE_RISK：比较类风险（COMPARISON_CHECK / 比较类主张）
- MANAGEMENT_RISK：治理/管理层类风险（治理/管理层/股东/分红/回购相关主张）

生成风险摘要：每条 Key Risk = {category, claim_id, claim, risk_score, risk_level,
verification_status, reason}。
"""

from app.services.investment.schemas import (
    RISK_CATEGORY_BUSINESS,
    RISK_CATEGORY_COMPETITIVE,
    RISK_CATEGORY_FINANCIAL,
    RISK_CATEGORY_MANAGEMENT,
)

# 投资风险分类 → 聚合规则
_MANAGEMENT_KEYWORDS = ("治理", "管理层", "股东", "分红", "回购", "董事会", "管理层变动", "股权激励")

_CATEGORY_LABELS = {
    RISK_CATEGORY_FINANCIAL: "财务风险",
    RISK_CATEGORY_BUSINESS: "业务风险",
    RISK_CATEGORY_COMPETITIVE: "竞争风险",
    RISK_CATEGORY_MANAGEMENT: "治理风险",
}

# 核验类型 → 分类默认映射
_TYPE_TO_CATEGORY = {
    "EXACT_VALUE_CHECK": RISK_CATEGORY_FINANCIAL,
    "GROWTH_RATE_CHECK": RISK_CATEGORY_FINANCIAL,
    "PERIOD_CHECK": RISK_CATEGORY_FINANCIAL,
    "SEMANTIC_SUPPORT_CHECK": RISK_CATEGORY_BUSINESS,
    "SEMANTIC_CHECK": RISK_CATEGORY_BUSINESS,
    "CAUSAL_CHECK": RISK_CATEGORY_BUSINESS,
    "COMPARISON_CHECK": RISK_CATEGORY_COMPETITIVE,
    "MULTI_EVIDENCE_CHECK": RISK_CATEGORY_BUSINESS,
}


def categorize_claim(claim: dict, verification: dict, risk: dict) -> str:
    """单条主张的投资风险分类（可解释：规则优先，关键词兜底）。"""
    claim_text = str(claim.get("original_text") or claim.get("source_text") or "")
    vtype = verification.get("verification_type") or ""
    rtype = risk.get("risk_type") or ""
    ct = (claim.get("claim_type") or "").upper()

    # 比较类主张（COMPARATIVE_CLAIM / COMPARISON_CHECK）→ 竞争风险
    if vtype == "COMPARISON_CHECK" or ct in ("COMPARISON", "COMPARATIVE_CLAIM"):
        return RISK_CATEGORY_COMPETITIVE
    # 治理/管理层类关键词 → 治理风险
    if any(kw in claim_text for kw in _MANAGEMENT_KEYWORDS):
        return RISK_CATEGORY_MANAGEMENT
    # 财务类风险（FINANCIAL_ERROR 或数字类核验）→ 财务风险
    if rtype == "FINANCIAL_ERROR" or vtype in ("EXACT_VALUE_CHECK", "GROWTH_RATE_CHECK", "PERIOD_CHECK"):
        return RISK_CATEGORY_FINANCIAL
    # 其余 → 业务风险
    return RISK_CATEGORY_BUSINESS


def build_risk_summary(
    claims: list[dict],
    verification_results: list[dict],
    risk_assessments: list[dict],
    top_n: int = 12,
) -> dict:
    """生成投资风险摘要：分类聚合 + Key Risks 列表（按 risk_score 排序）。"""
    claim_by_id = {}
    for c in claims:
        claim_by_id[c.get("claim_id") or c.get("claim_uid")] = c
    ver_by_id = {v["claim_id"]: v for v in verification_results}
    risk_by_id = {r["claim_id"]: r for r in risk_assessments}

    categorized: list[dict] = []
    for claim_id, risk in risk_by_id.items():
        claim = claim_by_id.get(claim_id, {})
        verification = ver_by_id.get(claim_id, {})
        category = categorize_claim(claim, verification, risk)
        categorized.append(
            {
                "claim_id": claim_id,
                "category": category,
                "category_label": _CATEGORY_LABELS[category],
                "claim": claim.get("original_text") or claim.get("source_text") or claim_id,
                "risk_score": risk.get("risk_score", 0.0),
                "risk_level": risk.get("risk_level", "LOW"),
                "risk_type": risk.get("risk_type", ""),
                "verification_status": verification.get("verification_status", ""),
                "verification_type": verification.get("verification_type", ""),
                "reason": verification.get("reason", ""),
            }
        )
    # 按风险分数降序
    categorized.sort(key=lambda x: -x["risk_score"])

    # 分类聚合统计（仅风险点）
    distribution = {c: 0 for c in _CATEGORY_LABELS}
    for item in categorized:
        if item["verification_status"] == "SUPPORTED":
            continue
        distribution[item["category"]] = distribution.get(item["category"], 0) + 1

    return {
        "key_risks": categorized[:top_n],
        "distribution": distribution,
        "category_labels": _CATEGORY_LABELS,
    }
