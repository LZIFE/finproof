"""Phase 23.15 Step 3/4 — Claim → Section Routing 规则（服务层模块）

被 retrieve_for_claim 调用（Phase 23.15 三级检索第一步）：
claim → route_sections_for_claim → 目标章节类型 → section_index 定位页 → block 检索。

规则（与 scripts/phase23_15_claim_routing.py 同源）：
- Revenue → income_statement, management_discussion
- Profit  → income_statement
- Debt    → balance_sheet
- Cash    → cash_flow
- Growth  → management_discussion + financial statements
- 兜底    → 全部财务章节
"""
from __future__ import annotations

# metric_code 前缀 → 目标章节（带优先级）
METRIC_CODE_SECTIONS: dict[str, tuple[str, ...]] = {
    "revenue": ("income_statement", "management_discussion"),
    "total_operating_revenue": ("income_statement", "management_discussion"),
    "net_profit": ("income_statement",),
    "net_profit_attributable": ("income_statement",),
    "deducted_net_profit": ("income_statement",),
    "gross_margin": ("income_statement",),
    "net_margin": ("income_statement",),
    "eps": ("income_statement",),
    "bps": ("income_statement",),
    "roe": ("income_statement", "management_discussion"),
    "roa": ("income_statement", "management_discussion"),
    "total_assets": ("balance_sheet",),
    "net_assets": ("balance_sheet",),
    "debt_ratio": ("balance_sheet",),
    "operating_cash_flow": ("cash_flow",),
    "yoy_growth_revenue": ("management_discussion", "income_statement"),
    "qoq_growth_revenue": ("management_discussion", "income_statement"),
}

# 中文指标关键词 → 章节
METRIC_TEXT_SECTIONS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("营业收入", "营业总收入", "营收", "收入", "revenue", "sales"), ("income_statement", "management_discussion")),
    (("净利润", "归母净利润", "净利", "net income", "net profit"), ("income_statement",)),
    (("扣非", "扣除非经常性"), ("income_statement",)),
    (("毛利率", "每股收益", "净资产收益率", "roe", "eps"), ("income_statement",)),
    (("总资产", "净资产", "负债", "资产负债率", "debt", "资产总额"), ("balance_sheet",)),
    (("现金流", "经营现金流", "现金流量", "cash flow", "现金及现金等价物"), ("cash_flow",)),
    (("同比", "增长", "增长幅度", "增速", "yoy", "较上年"), ("management_discussion", "income_statement")),
]

DEFAULT_SECTIONS = ("income_statement", "balance_sheet", "cash_flow", "management_discussion", "notes")

# route 类型 → 章节补充
ROUTE_SECTIONS: dict[str, tuple[str, ...]] = {
    "STRUCTURED_NUMERIC": ("income_statement", "balance_sheet", "cash_flow"),
    "TABLE_METRIC": ("income_statement", "balance_sheet"),
    "PERIOD_COMPARISON": ("management_discussion", "income_statement", "financial_highlights"),
    "SCOPE_VALIDATION": ("income_statement", "notes"),
    "NARRATIVE_FACT": ("management_discussion", "business"),
    "CAUSALITY": ("management_discussion",),
    "FORECAST": ("management_discussion", "business"),
    "INSUFFICIENTLY_PARSED": DEFAULT_SECTIONS,
}


def route_sections_for_claim(claim: dict) -> dict:
    """把 claim 路由到目标章节集合，返回 {sections: [...], confidence, rule}。"""
    metric_code = str(claim.get("metric_code") or "").strip() or str(claim.get("metric") or "").strip()
    metric = str(claim.get("metric") or "").strip()
    text = str(claim.get("original_text") or claim.get("claim_text") or "").strip()
    route = str(claim.get("route") or claim.get("claim_type") or "").upper()

    sections: tuple[str, ...] = ()
    rule = "default"

    # 1) metric_code 前缀匹配（含 growth 前缀剥除）
    code = metric_code
    base_code = code
    for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
        if code.startswith(pfx):
            base_code = code[len(pfx):]
            break
    if base_code in METRIC_CODE_SECTIONS:
        sections = METRIC_CODE_SECTIONS[base_code]
        rule = f"metric_code:{base_code}"
    elif code in METRIC_CODE_SECTIONS:
        sections = METRIC_CODE_SECTIONS[code]
        rule = f"metric_code:{code}"

    # 2) metric 文本关键词匹配
    if not sections and metric:
        for kws, secs in METRIC_TEXT_SECTIONS:
            if any(kw in metric for kw in kws):
                sections = secs
                rule = f"metric_text:{metric}"
                break

    # 3) claim 原文关键词匹配
    if not sections and text:
        for kws, secs in METRIC_TEXT_SECTIONS:
            if any(kw in text for kw in kws):
                sections = secs
                rule = "text_keyword"
                break

    # 4) route 类型补充
    if route in ROUTE_SECTIONS:
        route_secs = ROUTE_SECTIONS[route]
        sections = tuple(dict.fromkeys(sections + route_secs)) if sections else route_secs
        rule = f"{rule}+route:{route}" if rule != "default" else f"route:{route}"

    # 5) 兜底
    if not sections:
        sections = DEFAULT_SECTIONS

    return {
        "sections": list(sections),
        "confidence": 0.9 if rule != "default" else 0.6,
        "rule": rule,
    }
