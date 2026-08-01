"""FinProof Assumption Checker（Phase 16，任务书 §1 §3 §9）。

识别结论依赖的隐含假设（HIDDEN_ASSUMPTION），并标记未验证前提 ASSUMPTION_UNVERIFIED。

Demo 案例 3："公司市场份额领先，因此具有长期竞争优势"
→ 排名证据不足以证明长期优势，HIDDEN_ASSUMPTION。

约束：不替代 Verification；不输出投资建议。
"""

from __future__ import annotations

import re

from app.services.financial_reasoning.schemas import (
    RT_HIDDEN_ASSUMPTION,
    STATUS_ASSUMPTION_UNVERIFIED,
    STATUS_OK,
    ReasoningInput,
    ReasoningResult,
    _now_iso,
)
from app.services.financial_reasoning.logic_rules import RULE_VERSION


# ---------------------------------------------------------------------------
# 隐含假设库：强结论 → 必要前提
# ---------------------------------------------------------------------------
_ASSUMPTION_LIBRARY: list[dict] = [
    {
        "conclusion_kw": ("长期优势", "长期竞争优势", "持续领先", "长期领先"),
        "evidence_kw": ("市场份额", "排名第一", "第一", "龙头", "领先"),
        "assumption": "市场份额领先等同于长期竞争优势（未披露：竞争格局稳定性、技术迭代、客户黏性）",
        "gap": "市场份额领先 → 长期竞争优势：缺少竞争格局稳定性/技术迭代/客户黏性前提",
        "safe": "公司当前市场份额领先，长期竞争优势需结合竞争格局稳定性、技术迭代、客户黏性等综合判断。",
        "rule_id": "A001-market-share-not-long-term",
    },
    {
        "conclusion_kw": ("核心", "引擎", "支柱"),
        "evidence_kw": ("增长", "同比", "提升", "扩张"),
        "assumption": "阶段性增长等同于业务核心/引擎/支柱（未披露：业务占比、利润贡献、可持续性）",
        "gap": "阶段性增长 → 业务核心/引擎：缺少业务占比/利润贡献/可持续性前提",
        "safe": "该业务阶段性增长，是否构成核心/引擎需结合业务占比、利润贡献与可持续性综合判断。",
        "rule_id": "A002-growth-not-core",
    },
    {
        "conclusion_kw": ("确定性增长", "持续增长", "趋势确立"),
        "evidence_kw": ("增长", "同比", "提升"),
        "assumption": "单期增长等同于确定性/持续趋势（未披露：多期连续性、行业周期）",
        "gap": "单期增长 → 确定性/持续趋势：缺少多期连续性与行业周期前提",
        "safe": "单期增长数据，确定性/持续趋势需多期连续数据与行业周期综合判断。",
        "rule_id": "A003-single-period-not-trend",
    },
    {
        "conclusion_kw": ("盈利能力改善", "经营质量改善"),
        "evidence_kw": ("营收增长", "收入增长", "营收同比"),
        "assumption": "营收增长等同于盈利能力/经营质量改善（未披露：利润率、现金流、应收）",
        "gap": "营收增长 → 盈利能力/经营质量改善：缺少利润率/现金流/应收前提",
        "safe": "营收增长，盈利能力/经营质量是否改善需结合利润率、现金流、应收等综合判断。",
        "rule_id": "A004-revenue-not-profitability",
    },
    {
        "conclusion_kw": ("利润贡献增长", "利润核心"),
        "evidence_kw": ("收入增长", "营收增长", "海外收入增长"),
        "assumption": "收入增长等同于利润贡献增长（未披露：业务利润率、成本结构）",
        "gap": "收入增长 → 利润贡献增长：缺少业务利润率与成本结构前提",
        "safe": "收入增长，利润贡献是否同步增长需结合业务利润率与成本结构综合判断。",
        "rule_id": "A005-revenue-not-profit-contribution",
    },
]


def check_assumptions(input_: ReasoningInput) -> list[ReasoningResult]:
    """检查隐含假设，返回触发结果列表。"""
    text = input_.claim_text
    results: list[ReasoningResult] = []

    for lib in _ASSUMPTION_LIBRARY:
        has_conclusion = any(k in text for k in lib["conclusion_kw"])
        has_evidence_signal = any(k in text for k in lib["evidence_kw"])
        if not (has_conclusion and has_evidence_signal):
            continue

        # 收集相关支持证据
        supporting = [
            ev for ev in input_.evidence_candidates
            if any(k in (ev.get("text") or "") for k in lib["evidence_kw"])
        ]
        # 反证：含下降/恶化等
        counter = [
            ev for ev in input_.evidence_candidates
            if any(k in (ev.get("text") or "") for k in ("下降", "下滑", "减少", "恶化", "落后", "退步"))
        ]

        explanation = (
            f"结论含「{','.join(lib['conclusion_kw'][:2])}」类强表述，"
            f"但证据仅含「{','.join(lib['evidence_kw'][:2])}」类弱信号，"
            f"结论依赖隐含假设：{lib['assumption']}。该假设未披露亦未验证。"
        )

        results.append(ReasoningResult(
            reasoning_type=RT_HIDDEN_ASSUMPTION,
            status=STATUS_ASSUMPTION_UNVERIFIED,
            premises=[f"证据信号：{','.join(lib['evidence_kw'][:2])}"],
            supporting_evidence=_ev_ids(supporting),
            counter_evidence=_ev_ids(counter),
            assumptions=[lib["assumption"]],
            logical_gap=lib["gap"],
            confidence=0.82,
            explanation=explanation,
            suggested_safe_wording=lib["safe"],
            triggered_rules=[lib["rule_id"]],
            evidence_ids=_collect_ids(supporting, counter),
            rule_version=RULE_VERSION,
            created_at=_now_iso(),
        ))

    return results


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
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


def _collect_ids(supporting: list[dict], counter: list[dict]) -> list[str]:
    ids = []
    for ev in supporting + counter:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("block_id") or ev.get("evidence_id") or ev.get("id")
        if eid and eid not in ids:
            ids.append(str(eid))
    return ids


__all__ = ["check_assumptions", "RULE_VERSION"]
