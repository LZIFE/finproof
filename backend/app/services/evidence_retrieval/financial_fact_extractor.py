"""Phase 23.18 Task 2 — Financial Fact Extractor

从 Evidence Block 原始文本提取结构化财务事实元数据（不删除 raw text）：

- metric       : 指标名（营业收入/净利润/…）
- value        : 数值（含单位换算到亿元展示）
- unit         : 单位（千元/万元/亿元）
- period       : 期间（2025年度/2024年度…）
- table_type   : 表格类型（income_statement/balance_sheet/cash_flow/other）
- row_label    : 行标签（指标行名）
- column_label : 列标签（期间列/合并/公司…）

供 Financial Reranker（Task 3）做 fact-level 匹配。
"""
from __future__ import annotations

import re

from app.services.evidence_retrieval.engine import (
    _METRIC_ALIASES,
    _ALIAS_BY_NAME,
    is_noise_block,
)

# 单位正则（块内列单位，如"（千元）"）
_UNIT_RE = re.compile(r"[（(]?(人民币)?\s*(万亿元|亿元|百万元|万元|千元|元)\s*[）)]?")
# 年份（2023-2025 等）
_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
# 财务数字（千分位）
_FIN_NUM_RE = re.compile(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)")
# 百分比
_PCT_RE = re.compile(r"(?<!\d)\d{1,3}(?:\.\d+)?%")

# 表头关键词（列标签候选）
_COLUMN_KW = ("2025年度", "2024年度", "2023年度", "本期金额", "上期金额", "本年", "上年", "合并", "公司", "期末余额", "年初余额")
# 表格类型关键词
_TABLE_TYPE_KW = {
    "income_statement": ("利润表",),
    "balance_sheet": ("资产负债表",),
    "cash_flow": ("现金流量表",),
    "equity_changes": ("所有者权益变动表", "股东权益变动表"),
}

_ALIAS_BY_NAME = {n: code for code, names in _METRIC_ALIASES.items() for n in names}

# 指标家族等价（revenue≈total_operating_revenue 同族可互匹配；
# 净利润家族严格隔离，不得与归母净利润混同）
_METRIC_FAMILY: dict[str, set[str]] = {
    "revenue": {"revenue", "total_operating_revenue"},
    "total_operating_revenue": {"revenue", "total_operating_revenue"},
    "net_profit": {"net_profit"},
    "net_profit_attributable": {"net_profit_attributable"},
    "deducted_net_profit": {"deducted_net_profit"},
    "operating_cash_flow": {"operating_cash_flow"},
}


def _metric_in(text: str) -> str | None:
    """提取块内指标名（最长命中别名）。"""
    hits = [a for a in _ALIAS_BY_NAME if a and a in text]
    if not hits:
        return None
    hits.sort(key=len, reverse=True)
    return hits[0]


def _unit_in(text: str) -> str:
    m = _UNIT_RE.search(text)
    return m.group(2) if m else ""


def _periods_in(text: str) -> list[str]:
    """提取块内期间标签（年份列/期间词）。"""
    out: list[str] = []
    for y in _YEAR_RE.findall(text):
        out.append(f"{y}年")
    for kw in ("2025年度", "2024年度", "2023年度", "本期金额", "上期金额", "本年度", "上年度"):
        if kw in text:
            out.append(kw)
    return list(dict.fromkeys(out))


def _values_in(text: str) -> list[dict]:
    """提取块内财务数值（千分位数字 + 百分比），记录原始字符串与单位换算提示。"""
    out: list[dict] = []
    for m in _FIN_NUM_RE.finditer(text):
        num_str = m.group(0).replace(",", "")
        try:
            num = float(num_str)
        except ValueError:
            continue
        out.append({"value": num, "raw": m.group(0), "unit_hint": ""})
    for m in _PCT_RE.finditer(text):
        try:
            pct = float(m.group(0).rstrip("%"))
        except ValueError:
            continue
        out.append({"value": pct, "raw": m.group(0), "unit_hint": "%"})
    return out


def _table_type_in(text: str) -> str:
    for ttype, kws in _TABLE_TYPE_KW.items():
        if any(k in text for k in kws):
            return ttype
    return "other"


def _row_label_in(text: str) -> str:
    """行标签：块首行的指标名（去掉单位括号）。"""
    first_line = (text or "").strip().splitlines()[0] if text else ""
    m = _metric_in(first_line)
    if m:
        return m
    cleaned = re.sub(r"[（(][^）)]*[）)]", "", first_line).strip()
    return cleaned[:40]


def extract_financial_fact(block_text: str, table_type_hint: str = "") -> dict:
    """从 block 原文提取财务事实元数据（不删除原文）。

    返回：
        {
          "metric": str, "metric_code": str, "value": list[dict], "unit": str,
          "periods": list[str], "table_type": str,
          "row_label": str, "column_labels": list[str],
          "has_number": bool, "is_noise": bool
        }
    """
    text = block_text or ""
    noise = is_noise_block(text)
    metric = _metric_in(text)
    metric_code = _ALIAS_BY_NAME.get(metric, "") if metric else ""
    unit = _unit_in(text)
    periods = _periods_in(text)
    values = _values_in(text)
    table_type = _table_type_in(text) if table_type_hint not in ("", "other") else (
        _table_type_in(text) or table_type_hint
    )
    row_label = _row_label_in(text)
    column_labels = [kw for kw in _COLUMN_KW if kw in text]

    return {
        "metric": metric or "",
        "metric_code": metric_code,
        "values": values,
        "unit": unit,
        "periods": periods,
        "table_type": table_type,
        "row_label": row_label,
        "column_labels": column_labels,
        "has_number": bool(values),
        "is_noise": noise,
    }


def fact_match_score(block_text: str, claim: dict, fact: dict | None = None) -> float:
    """Financial Fact Match：claim 结构化字段 vs block 提取事实的匹配分（0-1）。

    fact_match 组合（供 reranker 的 financial_fact_match 分量）：
    - metric_code 一致：0.5
    - 单位一致：0.2
    - period 一致（claim period 年份在 block periods 中）：0.2
    - 行标签语义命中：0.1
    """
    if not block_text or is_noise_block(block_text):
        return 0.0
    fact = fact or extract_financial_fact(block_text)
    score = 0.0

    claim_code = str(claim.get("metric_code") or "").strip()
    if claim_code and fact["metric_code"]:
        # 归一：yoy_growth_revenue → revenue
        cbase = claim_code
        for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
            if cbase.startswith(pfx):
                cbase = cbase[len(pfx):]
                break
        # 家族匹配：revenue≈total_operating_revenue 同族（净利润家族严格隔离）
        family = _METRIC_FAMILY.get(cbase, set())
        if fact["metric_code"] == cbase or (family and fact["metric_code"] in family):
            score += 0.5

    claim_unit = str(claim.get("unit") or "").strip()
    if claim_unit and fact["unit"]:
        if claim_unit in ("亿元", "万元", "千元", "元") and fact["unit"] in ("亿元", "万元", "千元", "元"):
            score += 0.2  # 同族单位（换算由 value 层处理）
        elif claim_unit == fact["unit"]:
            score += 0.2

    claim_period = str(claim.get("period") or "")
    if claim_period:
        year = re.search(r"(19|20)\d{2}", claim_period)
        if year and any(y == f"{year.group(0)}年" for y in fact["periods"]):
            score += 0.2

    if fact["row_label"]:
        # 行标签含 claim 中文指标词（或反之）
        claim_metric = str(claim.get("metric") or "")
        if claim_metric and (claim_metric in fact["row_label"] or fact["row_label"] in claim_metric):
            score += 0.1

    return round(min(score, 1.0), 4)
