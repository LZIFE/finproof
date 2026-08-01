"""FinProof Growth Quality Analyzer（Phase 16，任务书 §4）。

对增长类主张组合检查：
- revenue growth       �收增长
- net profit growth    净利润增长
- gross margin         曕利率
- operating cash flow  经营现金流
- receivables/inventory 应收/存货

输出：
- HIGH_QUALITY_GROWTH   �收/利润/毛利率/现金流同步向好
- MIXED_QUALITY_GROWTH  营收增长但部分指标恶化
- LOW_QUALITY_GROWTH    营收增长但利润/现金流/应收明显恶化
- INSUFFICIENT_DATA     缺数据，不得强行判断

约束：不凭缺失数据强行判断。
"""

from __future__ import annotations

import re

from app.services.financial_reasoning.schemas import (
    GQ_HIGH_QUALITY,
    GQ_INSUFFICIENT,
    GQ_LOW_QUALITY,
    GQ_MIXED_QUALITY,
    GrowthIndicator,
    GrowthQualityResult,
    ReasoningInput,
    ReasoningResult,
    RT_GROWTH_QUALITY_RISK,
    STATUS_INSUFFICIENT_DATA,
    STATUS_MIXED_EVIDENCE,
    STATUS_OK,
    _now_iso,
)
from app.services.financial_reasoning.logic_rules import RULE_VERSION


# 指标 → 关键词映射
_INDICATOR_KW = {
    "revenue": ("营收", "营业收入", "收入"),
    "net_profit": ("净利润", "归母净利润"),
    "gross_margin": ("毛利率"),
    "operating_cash_flow": ("经营现金流", "经营活动现金流", "现金流"),
    "receivables": ("应收", "应收账"),
    "inventory": ("存货", "库存"),
}


def analyze_growth_quality(input_: ReasoningInput) -> GrowthQualityResult:
    """组合检查增长质量，返回 GrowthQualityResult。

    不得凭缺失数据强行判断：若关键指标（revenue/net_profit）缺失 → INSUFFICIENT_DATA。
    """
    indicators: list[GrowthIndicator] = []
    for name, kws in _INDICATOR_KW.items():
        ev = _find_indicator_evidence(input_, kws)
        if ev is None:
            indicators.append(GrowthIndicator(name=name, value=None, direction="UNKNOWN"))
        else:
            val = _extract_number(ev.get("text") or "")
            direction = _extract_direction(ev.get("text") or "")
            indicators.append(GrowthIndicator(
                name=name,
                value=val,
                direction=direction,
                evidence_id=str(ev.get("block_id") or ev.get("evidence_id") or ""),
            ))

    # 关键指标必须存在
    revenue = next((i for i in indicators if i.name == "revenue"), None)
    net_profit = next((i for i in indicators if i.name == "net_profit"), None)
    if revenue is None or revenue.direction == "UNKNOWN" or net_profit is None or net_profit.direction == "UNKNOWN":
        return GrowthQualityResult(
            quality=GQ_INSUFFICIENT,
            indicators=indicators,
            reason="营收或净利润数据缺失，不得强行判断增长质量。",
            supporting_evidence=[],
            counter_evidence=[],
        )

    # 收集支持/反证
    supporting = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in _INDICATOR_KW["revenue"])
    ]
    counter = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("现金流下降", "应收上升", "存货增", "毛利率下降", "利润率下降"))
    ]

    # 综合判断
    cash = next((i for i in indicators if i.name == "operating_cash_flow"), None)
    margin = next((i for i in indicators if i.name == "gross_margin"), None)
    recv = next((i for i in indicators if i.name == "receivables"), None)
    inv = next((i for i in indicators if i.name == "inventory"), None)

    revenue_up = revenue.direction == "UP"
    profit_up = net_profit.direction == "UP"
    cash_up = cash is not None and cash.direction == "UP"
    cash_down = cash is not None and cash.direction == "DOWN"
    margin_up = margin is not None and margin.direction == "UP"
    margin_down = margin is not None and margin.direction == "DOWN"
    recv_up = recv is not None and recv.direction == "UP"  # 应收上升为负向
    inv_up = inv is not None and inv.direction == "UP"  # 存货上升为负向

    # HIGH：营收/利润/毛利率/现金流同步向好，应收/存货不上升
    all_good = revenue_up and profit_up and (margin_up or margin is None or margin.direction == "FLAT") and (cash_up or cash is None or cash.direction == "FLAT") and not recv_up and not inv_up
    # LOW：营收增长但利润/现金流/应收明显恶化
    clearly_bad = revenue_up and (profit_up is False or cash_down or margin_down or recv_up or inv_up)
    # MIXED：介于之间
    mixed = revenue_up and not all_good and not clearly_bad

    if all_good:
        quality = GQ_HIGH_QUALITY
        reason = "营收、利润、毛利率、现金流同步向好，应收/存货未上升，构成高质量增长。"
    elif clearly_bad:
        quality = GQ_LOW_QUALITY
        reason = "营收增长但利润/现金流/毛利率/应收/存货存在明显恶化，增长质量低。"
    elif mixed:
        quality = GQ_MIXED_QUALITY
        reason = "营收增长但部分指标未同步或存在恶化迹象，增长质量混合。"
    else:
        quality = GQ_INSUFFICIENT
        reason = "指标组合不明确，数据不足以判断。"

    return GrowthQualityResult(
        quality=quality,
        indicators=indicators,
        reason=reason,
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=_ev_ids(counter),
    )


def growth_to_reasoning_result(
    input_: ReasoningInput,
    gq: GrowthQualityResult,
) -> ReasoningResult:
    """将 GrowthQualityResult 转为 ReasoningResult（便于统一展示与持久化）。"""
    if gq.quality == GQ_INSUFFICIENT:
        status = STATUS_INSUFFICIENT_DATA
        confidence = 0.5
    elif gq.quality == GQ_HIGH_QUALITY:
        status = STATUS_OK
        confidence = 0.85
    elif gq.quality == GQ_MIXED_QUALITY:
        status = STATUS_MIXED_EVIDENCE
        confidence = 0.75
    else:  # LOW
        status = STATUS_MIXED_EVIDENCE
        confidence = 0.80

    safe = {
        GQ_HIGH_QUALITY: "多项指标同步向好，增长质量较高。",
        GQ_MIXED_QUALITY: "营收增长但部分指标未同步，增长质量混合，不宜直接表述为经营质量改善。",
        GQ_LOW_QUALITY: "营收增长但利润/现金流/应收/存货存在恶化，增长质量低，不宜表述为经营质量改善。",
        GQ_INSUFFICIENT: "数据不足以判断增长质量，需补充利润/现金流/应收/存货等指标。",
    }.get(gq.quality, "")

    return ReasoningResult(
        reasoning_type=RT_GROWTH_QUALITY_RISK,
        status=status,
        premises=[f"指标 {i.name} 方向 {i.direction}" for i in gq.indicators],
        supporting_evidence=gq.supporting_evidence,
        counter_evidence=gq.counter_evidence,
        assumptions=[],
        logical_gap=gq.reason,
        confidence=confidence,
        explanation=gq.reason,
        suggested_safe_wording=safe,
        triggered_rules=["Q001-growth-quality"],
        evidence_ids=[i.evidence_id for i in gq.indicators if i.evidence_id],
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _find_indicator_evidence(input_: ReasoningInput, kws: tuple[str, ...]) -> dict | None:
    """从 evidence_candidates / KG facts 中找到首个含指标关键词的证据。"""
    for ev in input_.evidence_candidates + input_.knowledge_graph_facts:
        text = ev.get("text") or ev.get("block_text") or ""
        if any(k in text for k in kws):
            return ev
    return None


def _extract_number(text: str) -> float | None:
    match = re.search(r"(\d+\.?\d*)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _extract_direction(text: str) -> str:
    pos = any(k in text for k in ("增长", "上升", "提升", "扩大", "改善", "增加", "上行"))
    neg = any(k in text for k in ("下降", "下滑", "减少", "收缩", "恶化", "回落", "降低"))
    if pos and not neg:
        return "UP"
    if neg and not pos:
        return "DOWN"
    if pos and neg:
        return "MIXED"
    return "FLAT"


def _ev_ids(evidence: list[dict]) -> list[dict]:
    out = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        out.append({
            "evidence_id": ev.get("block_id") or ev.get("evidence_id") or ev.get("id"),
            "source": ev.get("document_id") or ev.get("source") or "未知",
            "page": ev.get("page_number") or ev.get("page"),
            "text": (ev.get("text") or ev.get("block_text") or "")[:200],
            "stance": ev.get("stance") or "NEUTRAL",
        })
    return out


__all__ = [
    "analyze_growth_quality",
    "growth_to_reasoning_result",
    "RULE_VERSION",
]
