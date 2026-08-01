"""FinProof Financial Reasoning Logic Rules（Phase 16，任务书 §3）。

可解释确定性规则：识别指标偷换 / 期间口径偷换 / 相关性写成因果 /
收入贡献写成利润贡献 / 低基数高增长 / 选择性引用证据 /
结论过度跳跃。

所有规则触发后保存触发规则ID和引用证据ID。

约束：不替代 Verification；不输出投资建议；不自动估值或交易。
"""

from __future__ import annotations

import re
from typing import Any

from app.services.financial_reasoning.schemas import (
    REASONING_LABELS,
    RT_BASE_EFFECT_RISK,
    RT_CONCLUSION_OVERREACH,
    RT_CORRELATION_AS_CAUSATION,
    RT_METRIC_SUBSTITUTION,
    RT_PERIOD_SUBSTITUTION,
    RT_REVENUE_PROFIT_CONFUSION,
    RT_SELECTIVE_EVIDENCE,
    STATUS_ASSUMPTION_UNVERIFIED,
    STATUS_LOGICAL_GAP,
    STATUS_MIXED_EVIDENCE,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    ReasoningInput,
    ReasoningResult,
    _now_iso,
)


# ---------------------------------------------------------------------------
# 规则版本与ID
# ---------------------------------------------------------------------------
RULE_VERSION = "r2025-phase16"


# ---------------------------------------------------------------------------
# 规则 R001：海外收入增长不能直接推出海外利润贡献增长
# ---------------------------------------------------------------------------
def _rule_revenue_not_profit(input_: ReasoningInput) -> ReasoningResult | None:
    """R001：收入增长 ≠ 利润贡献增长（任务书 §3 + Demo 案例 1）。"""
    text = input_.claim_text
    # 启发：claim 含"收入增长"/"营收增长"且结论含"利润核心/利润贡献/利润增长核心"
    has_revenue_growth = any(k in text for k in ("收入增长", "营收增长", "海外收入增长"))
    has_profit_conclusion = any(k in text for k in ("利润增长核心", "利润贡献", "利润核心", "利润增长引擎"))
    if not (has_revenue_growth and has_profit_conclusion):
        return None

    supporting = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("收入增长", "营收增长", "海外收入"))
    ]
    counter = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("利润率", "毛利率", "净利润", "利润贡献"))
    ]

    safe = "海外收入增长，海外业务对利润的具体贡献需结合利润率/成本结构进一步核验。"
    explanation = (
        "收入增长与利润贡献增长是不同指标：收入增长不直接推出利润贡献增长，"
        "需利润率、成本结构、海外业务利润率等前提。当前证据仅支持收入端，"
        "结论使用利润贡献强表述，构成结论过度跳跃。"
    )
    return ReasoningResult(
        reasoning_type=RT_CONCLUSION_OVERREACH,
        status=STATUS_LOGICAL_GAP,
        premises=["海外收入增长（已识别前提）"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=_ev_ids(counter),
        assumptions=["海外业务利润率不低于整体利润率（未披露）"],
        logical_gap="收入增长 → 利润贡献增长：缺少利润率与成本结构前提",
        confidence=0.85,
        explanation=explanation,
        suggested_safe_wording=safe,
        triggered_rules=["R001-revenue-not-profit"],
        evidence_ids=_collect_ids(supporting, counter),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则 R002：营收增长不能直接推出经营质量改善（Demo 案例 2 的逻辑基础）
# ---------------------------------------------------------------------------
def _rule_revenue_not_quality(input_: ReasoningInput) -> ReasoningResult | None:
    """R002：营收增长 ≠ 经营质量改善。"""
    text = input_.claim_text
    has_rev = any(k in text for k in ("营收增长", "收入增长", "营收同比"))
    has_quality = any(k in text for k in ("经营质量改善", "经营质量提升", "盈利能力改善", "经营改善"))
    if not (has_rev and has_quality):
        return None

    supporting = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("营收", "收入", "营收同比"))
    ]
    counter = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("现金流下降", "应收上升", "应收增", "存货增", "利润率下降"))
    ]
    safe = "营收增长，经营质量是否改善需结合利润率、现金流、应收与存货等综合判断。"
    explanation = (
        "营收增长是单一收入端指标，经营质量改善需利润率、现金流、应收/存货等多维支持。"
        "若现金流下降或应收上升，营收增长可能伴随质量恶化。"
    )
    return ReasoningResult(
        reasoning_type=RT_CONCLUSION_OVERREACH,
        status=STATUS_LOGICAL_GAP,
        premises=["营收增长（已识别前提）"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=_ev_ids(counter),
        assumptions=["营收增长伴随利润率/现金流同步改善（未披露）"],
        logical_gap="营收增长 → 经营质量改善：缺少利润率/现金流/应收前提",
        confidence=0.82,
        explanation=explanation,
        suggested_safe_wording=safe,
        triggered_rules=["R002-revenue-not-quality"],
        evidence_ids=_collect_ids(supporting, counter),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则 R003：指标偷换（收入增长被写成利润增长）
# ---------------------------------------------------------------------------
def _rule_metric_substitution(input_: ReasoningInput) -> ReasoningResult | None:
    """R003：收入增长被写成利润增长（METRIC_SUBSTITUTION）。"""
    text = input_.claim_text
    # claim 文本含"收入增长/营收增长"，但结论动词含"利润增长"
    has_revenue = any(k in text for k in ("收入增长", "营收增长"))
    has_profit = any(k in text for k in ("利润增长", "净利润增长", "盈利增长"))
    if not (has_revenue and has_profit):
        return None
    supporting = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("收入增长", "营收增长"))
    ]
    counter = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("利润率下降", "净利润下降", "毛利率下降"))
    ]
    safe = "收入增长，利润是否同步增长需结合利润率与成本单独核验。"
    return ReasoningResult(
        reasoning_type=RT_METRIC_SUBSTITUTION,
        status=STATUS_LOGICAL_GAP,
        premises=["收入增长"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=_ev_ids(counter),
        assumptions=["收入增长伴随利润同步增长（未披露）"],
        logical_gap="收入增长 → 利润增长：指标偷换",
        confidence=0.80,
        explanation="收入增长与利润增长是不同指标，将收入增长写成利润增长属于指标偷换。",
        suggested_safe_wording=safe,
        triggered_rules=["R003-metric-substitution"],
        evidence_ids=_collect_ids(supporting, counter),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则 R004：期间口径偷换（Q1/H1/FY）
# ---------------------------------------------------------------------------
def _rule_period_substitution(input_: ReasoningInput) -> ReasoningResult | None:
    """R004：期间口径偷换。"""
    text = input_.claim_text
    # claim 含多个期间口径且混用
    periods_found = re.findall(r"(2024|2025|2026)(Q1|Q2|Q3|Q4|H1|H2|FY)", text)
    if len(periods_found) < 2:
        return None
    # 若 claim 含"H1增长"但结论含"Q2"或不同口径
    has_h1 = "H1" in text
    has_q = any(q in text for q in ("Q1", "Q2", "Q3", "Q4"))
    has_fy = "FY" in text or "全年" in text
    if not (has_h1 and (has_q or has_fy)):
        return None
    supporting = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("H1", "上半年"))
    ]
    counter = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("Q1", "Q2", "Q3", "Q4", "一季度", "二季度"))
    ]
    safe = "应统一期间口径比较，H1与单季度口径不可直接等同。"
    return ReasoningResult(
        reasoning_type=RT_PERIOD_SUBSTITUTION,
        status=STATUS_LOGICAL_GAP,
        premises=[f"识别到期间口径：{periods_found}"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=_ev_ids(counter),
        assumptions=["不同期间口径增长率可比（未披露）"],
        logical_gap="H1/Q/FY 口径偷换：不同口径增长率不可直接等同",
        confidence=0.78,
        explanation="H1、单季度、全年口径不同，直接替换期间口径会导致增长率口径偷换。",
        suggested_safe_wording=safe,
        triggered_rules=["R004-period-substitution"],
        evidence_ids=_collect_ids(supporting, counter),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则 R005：相关性被写成因果
# ---------------------------------------------------------------------------
def _rule_correlation_as_causation(input_: ReasoningInput) -> ReasoningResult | None:
    """R005：相关性被写成因果。"""
    text = input_.claim_text
    # claim 含"因此/导致/带动"且涉及两个指标，但无因果证据
    has_causal = any(k in text for k in ("因此", "导致", "带动", "推动", "驱动", "所以"))
    has_two_metrics = sum(1 for k in ("收入", "利润", "毛利率", "现金流", "海外", "研发", "投入") if k in text) >= 2
    if not (has_causal and has_two_metrics):
        return None
    supporting = input_.evidence_candidates[:3]
    safe = "两指标存在相关性，是否构成因果关系需控制变量与时间先后证据。"
    return ReasoningResult(
        reasoning_type=RT_CORRELATION_AS_CAUSATION,
        status=STATUS_ASSUMPTION_UNVERIFIED,
        premises=["两指标存在相关性"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=[],
        assumptions=["相关性即因果（未验证）"],
        logical_gap="相关性 → 因果：缺少控制变量与时间先后证据",
        confidence=0.75,
        explanation="两指标同时变化仅证明相关性，写成因果需控制变量、时间先后等前提。",
        suggested_safe_wording=safe,
        triggered_rules=["R005-correlation-causation"],
        evidence_ids=_collect_ids(supporting, []),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则 R006：收入贡献写成利润贡献（REVENUE_PROFIT_CONFUSION）
# ---------------------------------------------------------------------------
def _rule_revenue_profit_confusion(input_: ReasoningInput) -> ReasoningResult | None:
    """R006：收入贡献写成利润贡献。"""
    text = input_.claim_text
    has_revenue_share = any(k in text for k in ("收入贡献", "收入占比", "营收贡献"))
    has_profit_word = any(k in text for k in ("利润贡献", "利润占比", "利润核心"))
    if not (has_revenue_share and has_profit_word):
        return None
    supporting = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("收入贡献", "收入占比"))
    ]
    counter = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("利润率", "毛利率", "成本"))
    ]
    safe = "收入贡献与利润贡献是不同口径，需结合业务利润率换算。"
    return ReasoningResult(
        reasoning_type=RT_REVENUE_PROFIT_CONFUSION,
        status=STATUS_LOGICAL_GAP,
        premises=["收入贡献占比"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=_ev_ids(counter),
        assumptions=["收入贡献占比等于利润贡献占比（未披露）"],
        logical_gap="收入贡献 → 利润贡献：口径混淆",
        confidence=0.82,
        explanation="收入贡献占比与利润贡献占比需经业务利润率换算，不可直接等同。",
        suggested_safe_wording=safe,
        triggered_rules=["R006-revenue-profit-confusion"],
        evidence_ids=_collect_ids(supporting, counter),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则 R007：低基数导致高增长率（BASE_EFFECT_RISK）
# ---------------------------------------------------------------------------
def _rule_base_effect(input_: ReasoningInput) -> ReasoningResult | None:
    """R007：低基数导致高增长率。"""
    text = input_.claim_text
    # claim 含高增长率且关键词"新业务/初创/低基数/从0起步"
    has_high_growth = bool(re.search(r"(\d+)\s*%", text)) and any(
        int(m.group(1)) >= 50 for m in re.finditer(r"(\d+)\s*%", text) if m.group(1).isdigit()
    )
    has_base_signal = any(k in text for k in ("新业务", "初创", "低基数", "从0", "起步", "基数低"))
    if not (has_high_growth and has_base_signal):
        return None
    supporting = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("增长", "%"))
    ]
    safe = "高增长率源于低基数，可持续性需结合绝对规模与基数判断。"
    return ReasoningResult(
        reasoning_type=RT_BASE_EFFECT_RISK,
        status=STATUS_ASSUMPTION_UNVERIFIED,
        premises=["高增长率", "低基数"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=[],
        assumptions=["高增长率可持续（未验证基数效应）"],
        logical_gap="低基数 → 高增长率：基数效应未披露",
        confidence=0.80,
        explanation="低基数下高增长率可持续性存疑，需结合绝对规模判断。",
        suggested_safe_wording=safe,
        triggered_rules=["R007-base-effect"],
        evidence_ids=_collect_ids(supporting, []),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则 R008：选择性引用证据（SELECTIVE_EVIDENCE）
# ---------------------------------------------------------------------------
def _rule_selective_evidence(input_: ReasoningInput) -> ReasoningResult | None:
    """R008：只引用支持材料，忽略反证。"""
    supporting = [
        ev for ev in input_.evidence_candidates
        if ev.get("supports") is True or ev.get("stance") == "SUPPORT"
    ]
    counter = [
        ev for ev in input_.evidence_candidates
        if ev.get("supports") is False or ev.get("stance") == "COUNTER"
    ]
    # 也用文本启发：反证含"下降/下滑/减少"
    counter_text = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in ("下降", "下滑", "减少", "恶化"))
    ]
    counter_all = counter + counter_text
    if not supporting or not counter_all:
        return None
    safe = "存在反证证据，结论应同时披露支持与反证，避免选择性引用。"
    return ReasoningResult(
        reasoning_type=RT_SELECTIVE_EVIDENCE,
        status=STATUS_MIXED_EVIDENCE,
        premises=["支持证据存在", "反证证据存在但被忽略"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=_ev_ids(counter_all),
        assumptions=["反证证据可忽略（未披露）"],
        logical_gap="选择性引用：忽略反证",
        confidence=0.78,
        explanation="同时存在支持证据与反证，应标记 MIXED_EVIDENCE，避免选择性引用。",
        suggested_safe_wording=safe,
        triggered_rules=["R008-selective-evidence"],
        evidence_ids=_collect_ids(supporting, counter_all),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则 R009：结论过度跳跃（CONCLUSION_OVERREACH）通用兜底
# ---------------------------------------------------------------------------
def _rule_conclusion_overreach_generic(input_: ReasoningInput) -> ReasoningResult | None:
    """R009：证据只能支持弱结论，报告使用强结论（通用兜底）。

    Demo 案例 1："海外收入增长，因此海外业务是利润增长核心"。
    """
    text = input_.claim_text
    strong_kw = ("核心", "引擎", "支柱", "领先", "长期优势", "持续增长", "确定性增长")
    weak_signal = any(k in text for k in ("增长", "同比", "提升"))
    strong_signal = any(k in text for k in strong_kw)
    if not (weak_signal and strong_signal):
        return None
    supporting = input_.evidence_candidates[:3]
    safe = "证据仅支持弱结论（阶段性增长），不宜直接使用强结论表述。"
    return ReasoningResult(
        reasoning_type=RT_CONCLUSION_OVERREACH,
        status=STATUS_LOGICAL_GAP,
        premises=["阶段性增长证据"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=[],
        assumptions=["阶段性增长等同于核心/长期支柱（未披露）"],
        logical_gap="弱证据 → 强结论：结论过度跳跃",
        confidence=0.76,
        explanation="证据仅支持阶段性增长，使用核心/引擎/支柱等强表述构成结论过度跳跃。",
        suggested_safe_wording=safe,
        triggered_rules=["R009-conclusion-overreach-generic"],
        evidence_ids=_collect_ids(supporting, []),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 规则注册表
# ---------------------------------------------------------------------------
_RULES = [
    _rule_revenue_not_profit,        # R001
    _rule_revenue_not_quality,       # R002
    _rule_metric_substitution,       # R003
    _rule_period_substitution,       # R004
    _rule_correlation_as_causation,  # R005
    _rule_revenue_profit_confusion,  # R006
    _rule_base_effect,               # R007
    _rule_selective_evidence,        # R008
    _rule_conclusion_overreach_generic,  # R009
]


def apply_rules(input_: ReasoningInput) -> list[ReasoningResult]:
    """依次应用全部规则，返回触发结果列表。"""
    results: list[ReasoningResult] = []
    for rule in _RULES:
        try:
            r = rule(input_)
        except Exception:  # noqa: BLE001
            r = None
        if r is not None:
            results.append(r)
    return results


# ---------------------------------------------------------------------------
# 内部工具：证据标准化
# ---------------------------------------------------------------------------
def _ev_ids(evidence: list[dict]) -> list[dict]:
    """标准化证据列表（含 evidence_id / 来源 / 文本摘要）。"""
    out = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        out.append({
            "evidence_id": ev.get("block_id") or ev.get("evidence_id") or ev.get("id"),
            "source": ev.get("document_id") or ev.get("source") or "未知",
            "page": ev.get("page_number") or ev.get("page"),
            "text": (ev.get("text") or ev.get("block_text") or "")[:200],
            "stance": ev.get("stance") or ("SUPPORT" if ev.get("supports") else "COUNTER" if ev.get("supports") is False else "NEUTRAL"),
        })
    return out


def _collect_ids(supporting: list[dict], counter: list[dict]) -> list[str]:
    """收集全部证据ID。"""
    ids = []
    for ev in supporting + counter:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("block_id") or ev.get("evidence_id") or ev.get("id")
        if eid and eid not in ids:
            ids.append(str(eid))
    return ids


__all__ = [
    "RULE_VERSION",
    "apply_rules",
]
