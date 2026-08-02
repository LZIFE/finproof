"""Autonomous Investigation Planner（Phase 13）。

根据 claim_type / risk_type 自主规划调查路径（任务书 §2）。

规划策略（按 claim_type）：
- FINANCIAL       → retrieve_evidence → verify_claim → assess_risk
- BUSINESS        → get_business_map → retrieve_evidence → verify_claim → assess_risk
- COMPETITIVE     → get_company_profile → retrieve_evidence → detect_conflicts → verify_claim
- GROWTH          → retrieve_evidence → verify_claim → assess_risk
- STRATEGIC       → get_business_map → retrieve_evidence → detect_conflicts → verify_claim → assess_risk
- FORECAST        → retrieve_evidence → detect_conflicts → verify_claim

约束：
- Agent 根据计划选择调用工具；禁止直接生成事实。
- 不输出投资建议；不自动交易；不替代投资经理。
"""

from __future__ import annotations

from app.services.autonomous_agent.schemas import (
    CLAIM_BUSINESS,
    CLAIM_COMPETITIVE,
    CLAIM_FINANCIAL,
    CLAIM_FORECAST,
    CLAIM_GROWTH,
    CLAIM_STRATEGIC,
    ClaimContext,
    InvestigationPlan,
    InvestigationStep,
    TOOL_ASSESS_RISK,
    TOOL_DETECT_CONFLICTS,
    TOOL_GET_BUSINESS_MAP,
    TOOL_GET_COMPANY_PROFILE,
    TOOL_RETRIEVE_EVIDENCE,
    TOOL_VERIFY_CLAIM,
    _now_iso,
)

# 按主张类型的工具序列（任务书 §2 示例）
_PLAN_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    CLAIM_FINANCIAL: [
        (TOOL_RETRIEVE_EVIDENCE, "检索财务证据（数字/指标）"),
        (TOOL_VERIFY_CLAIM, "核验财务数据主张"),
        (TOOL_ASSESS_RISK, "评估风险等级"),
    ],
    CLAIM_BUSINESS: [
        (TOOL_GET_BUSINESS_MAP, "获取业务图谱（分部/产品）"),
        (TOOL_RETRIEVE_EVIDENCE, "检索业务证据"),
        (TOOL_VERIFY_CLAIM, "核验业务主张"),
        (TOOL_ASSESS_RISK, "评估风险等级"),
    ],
    CLAIM_COMPETITIVE: [
        (TOOL_GET_COMPANY_PROFILE, "获取公司画像"),
        (TOOL_RETRIEVE_EVIDENCE, "检索竞争/市场证据"),
        (TOOL_DETECT_CONFLICTS, "检测竞争优势冲突"),
        (TOOL_VERIFY_CLAIM, "核验竞争优势主张"),
    ],
    CLAIM_GROWTH: [
        (TOOL_RETRIEVE_EVIDENCE, "检索增长证据"),
        (TOOL_VERIFY_CLAIM, "核验增长主张"),
        (TOOL_ASSESS_RISK, "评估风险等级"),
    ],
    CLAIM_STRATEGIC: [
        (TOOL_GET_BUSINESS_MAP, "获取业务图谱（识别战略支柱）"),
        (TOOL_RETRIEVE_EVIDENCE, "检索战略主张相关证据"),
        (TOOL_DETECT_CONFLICTS, "检测战略主张与其他事实的冲突"),
        (TOOL_VERIFY_CLAIM, "核验战略主张"),
        (TOOL_ASSESS_RISK, "评估风险等级"),
    ],
    CLAIM_FORECAST: [
        (TOOL_RETRIEVE_EVIDENCE, "检索历史证据（预测支持）"),
        (TOOL_DETECT_CONFLICTS, "检测预测与历史冲突"),
        (TOOL_VERIFY_CLAIM, "核验预测主张"),
    ],
}


def classify_claim_type(claim_text: str, claim: dict | None = None) -> str:
    """根据主张文本启发式分类 claim_type。"""
    text = claim_text or ""
    c = claim or {}

    # 优先使用 claim 元数据
    ctype = (c.get("claim_type") or c.get("type") or "").upper()
    if ctype in _PLAN_TEMPLATES:
        return ctype

    # 关键词启发式
    strategic_kw = ("核心", "支柱", "战略", "驱动", "增长引擎")
    competitive_kw = ("领先", "第一", "龙头", "优势", "市场份额", "市占率")
    growth_kw = ("增长", "同比", "提升", "扩大")
    financial_kw = ("营业收入", "净利润", "毛利率", "现金流", "ROE", "资产")
    forecast_kw = ("预计", "预期", "未来", "将", "有望")

    if any(k in text for k in strategic_kw):
        return CLAIM_STRATEGIC
    if any(k in text for k in competitive_kw):
        return CLAIM_COMPETITIVE
    if any(k in text for k in forecast_kw):
        return CLAIM_FORECAST
    if any(k in text for k in growth_kw):
        return CLAIM_GROWTH
    if any(k in text for k in financial_kw):
        return CLAIM_FINANCIAL
    return CLAIM_BUSINESS


def make_plan(ctx: ClaimContext) -> InvestigationPlan:
    """根据 claim_type / risk_type 生成 InvestigationPlan。"""
    claim_type = ctx.claim_type or CLAIM_BUSINESS
    template = _PLAN_TEMPLATES.get(claim_type, _PLAN_TEMPLATES[CLAIM_BUSINESS])

    objective = _build_objective(ctx, claim_type)
    steps: list[InvestigationStep] = []
    for idx, (tool, purpose) in enumerate(template, start=1):
        steps.append(
            InvestigationStep(
                step=idx,
                tool=tool,
                purpose=purpose,
                status="PENDING",
                timestamp=_now_iso(),
            )
        )
    return InvestigationPlan(
        objective=objective,
        claim_type=claim_type,
        risk_type=ctx.risk_type,
        steps=steps,
    )


def _build_objective(ctx: ClaimContext, claim_type: str) -> str:
    """构造调查目标说明（可解释）。"""
    risk_hint = f" 风险类型={ctx.risk_type}" if ctx.risk_type else ""
    return (
        f"自主调查主张「{ctx.claim_text[:60]}」"
        f"（类型={claim_type}{risk_hint}），"
        f"调用已有工具收集证据并核验，不直接生成事实。"
    )


__all__ = [
    "classify_claim_type",
    "make_plan",
]
