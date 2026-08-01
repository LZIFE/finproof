"""FinProof Copilot Intent Classifier（Phase 15，任务书 §2）。

启发式识别用户自然语言意图，分派到对应已有工具。

意图 → 工具路由：
- FACT_QUERY             → Evidence Retrieval
- RISK_EXPLANATION       → Risk Engine
- EVIDENCE_QUERY         → Evidence Chain
- COMPARISON_QUERY       → Monitoring Memory
- INVESTIGATION_REQUEST  → Autonomous Investigation Agent

约束：不修改已有核心验证逻辑。
"""

from __future__ import annotations

import re

from app.services.copilot.schemas import (
    INTENT_COMPARISON_QUERY,
    INTENT_EVIDENCE_QUERY,
    INTENT_FACT_QUERY,
    INTENT_INVESTIGATION_REQUEST,
    INTENT_REASONING_EXPLANATION,
    INTENT_RISK_EXPLANATION,
    INTENT_UNKNOWN,
    Intent,
)


# ---------------------------------------------------------------------------
# 关键词分组（启发式意图识别）
# ---------------------------------------------------------------------------
_FACT_KW = ("是多少", "多少亿", "净利润", "营收", "营业收入", "增长率", "毛利率", "现金流", "多少")
_FACT_REGEX = [r"(\d+)\s*亿", r"(\d+\.?\d*)\s*%"]

_RISK_KW = ("风险", "为什么这个观点", "高风险", "为什么高", "风险等级", "风险分", "为什么最高")

_EVIDENCE_KW = ("依据", "证据", "来源", "出处", "根据什么", "从哪", "可信吗", "靠什么")

_COMPARISON_KW = ("去年", "同比", "比", "变化", "趋势", "对比", "是否比", "增加", "减少", "历史")

_INVESTIGATION_KW = ("分析", "调查", "核验", "可靠吗", "是否可靠", "是不是", "是否真的", "是否真的", "可信度")
_REASONING_KW = ("为什么该结论不成立", "为什么不成立", "逻辑风险", "逻辑问题", "逻辑跳跃", "隐含假设", "结论跳跃", "推理解释", "为什么该结论")

_COMPANY_KW = ("美的", "宁德时代", "格力", "海尔", "茅台", "五粮液", "比亚迪")


def classify_intent(query: str) -> Intent:
    """识别用户问题意图。

    Args:
        query: 用户自然语言问题

    Returns:
        Intent（intent_type / confidence / keywords / company / metric）
    """
    if not query or not query.strip():
        return Intent(intent_type=INTENT_UNKNOWN, confidence=0.0)

    text = query.strip()
    keywords: list[str] = []

    # 识别公司
    company = ""
    for c in _COMPANY_KW:
        if c in text:
            company = c
            keywords.append(c)
            break

    # 识别指标
    metric = ""
    metric_kw_map = {
        "净利润": "净利润",
        "营收": "营收",
        "营业收入": "营业收入",
        "毛利率": "毛利率",
        "增长率": "增长率",
        "现金流": "现金流",
        "海外业务": "海外业务",
        "海外收入": "海外收入",
    }
    for kw, metric_name in metric_kw_map.items():
        if kw in text:
            metric = metric_name
            keywords.append(kw)
            break

    # 优先级：INVESTIGATION_REQUEST 含"分析/可靠"等强信号
    if any(k in text for k in _INVESTIGATION_KW):
        keywords.extend([k for k in _INVESTIGATION_KW if k in text])
        return Intent(
            intent_type=INTENT_INVESTIGATION_REQUEST,
            confidence=0.85,
            keywords=keywords,
            company=company,
            metric=metric,
        )

    # REASONING_EXPLANATION：含"为什么该结论不成立/逻辑风险/隐含假设"等
    reasoning_hits = [k for k in _REASONING_KW if k in text]
    if reasoning_hits:
        keywords.extend(reasoning_hits)
        return Intent(
            intent_type=INTENT_REASONING_EXPLANATION,
            confidence=0.86,
            keywords=keywords,
            company=company,
            metric=metric,
        )

    # COMPARISON_QUERY：含"去年/同比/比/变化"
    comp_hits = [k for k in _COMPARISON_KW if k in text]
    if comp_hits:
        keywords.extend(comp_hits)
        return Intent(
            intent_type=INTENT_COMPARISON_QUERY,
            confidence=0.80,
            keywords=keywords,
            company=company,
            metric=metric,
        )

    # EVIDENCE_QUERY：含"依据/证据/可信吗"
    ev_hits = [k for k in _EVIDENCE_KW if k in text]
    if ev_hits:
        keywords.extend(ev_hits)
        return Intent(
            intent_type=INTENT_EVIDENCE_QUERY,
            confidence=0.82,
            keywords=keywords,
            company=company,
            metric=metric,
        )

    # RISK_EXPLANATION：含"风险/为什么这个观点"
    risk_hits = [k for k in _RISK_KW if k in text]
    if risk_hits:
        keywords.extend(risk_hits)
        return Intent(
            intent_type=INTENT_RISK_EXPLANATION,
            confidence=0.83,
            keywords=keywords,
            company=company,
            metric=metric,
        )

    # FACT_QUERY：含数值或事实关键词
    fact_hits = [k for k in _FACT_KW if k in text]
    has_number = any(re.search(rx, text) for rx in _FACT_REGEX)
    if fact_hits or has_number:
        keywords.extend(fact_hits)
        if has_number:
            keywords.append("含数值")
        return Intent(
            intent_type=INTENT_FACT_QUERY,
            confidence=0.78,
            keywords=keywords,
            company=company,
            metric=metric,
        )

    # 兜底：若含"是不是/是否"等，按调查处理
    if any(k in text for k in ("是不是", "是否", "是不是真的")):
        keywords.extend(["是不是", "是否"])
        return Intent(
            intent_type=INTENT_INVESTIGATION_REQUEST,
            confidence=0.60,
            keywords=keywords,
            company=company,
            metric=metric,
        )

    return Intent(
        intent_type=INTENT_UNKNOWN,
        confidence=0.3,
        keywords=keywords,
        company=company,
        metric=metric,
    )


__all__ = ["classify_intent"]
