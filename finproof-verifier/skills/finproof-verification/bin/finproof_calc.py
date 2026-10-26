#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinProof 确定性财务计算引擎（可执行版，内嵌于专家自身）。

这是 `references/calc-engine.md` 的可执行实现，供专家在「有 shell」时调用以获得
无误差的十进制计算结果。纯标准库实现，不依赖 backend 任何模块。

设计目标：把 FinProof 后端 `financial_value.py` / `growth_verifier.py` /
`period_verifier.py` / `numeric_verifier.py` / `base.py` / `period_context.py` 的
确定性计算逻辑忠实移植为命令行工具。所有数值用 `decimal` 精确计算，避免浮点误差。

子命令：
  convert      单位/币种换算为「元」
  extract      从文本抽取结构化金融数值
  match        判断主张数值与证据数值是否匹配（容差 0.1%）
  yoy          同比增长率 (%)
  qoq          环比增长率 (%)
  quarter      累计转单季推导（Q2=H1-Q1 / Q4=FY-Q1-Q2-Q3 ...）
  margin       毛利率/净利率/费用率/业务占比
  cagr         CAGR
  eps          EPS
  roe          ROE
  debt         资产负债率
  cashdiff     经营现金流与净利润差异
  period       期间归一化（PeriodContext）
  temporal     引用时序检查：来源覆盖期间 vs 数据所属期间 → IMPOSSIBLE/COVERED/PARTIAL/UNCLEAR
  sum_check    总和一致性：分项之和 vs 合计（SOTP/成本明细/分部收入的确定性核对）
  forecast_scan 预测事实化扫描：确定性措辞 + 依据披露 → FLAG/CLEAN
  cite_check   引用真伪核验：链接可达 / 摘录逐字命中 / 来源日期与数据期间一致

所有子命令以 JSON 输出结果，便于专家逐步核对（对应审计轨迹）。
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from decimal import Decimal, getcontext

# 高精度，避免浮点误差
getcontext().prec = 28

# ---------------------------------------------------------------------------
# 单位与 scale 映射（与 backend financial_value.UNIT_SCALE 完全一致）
# ---------------------------------------------------------------------------
UNIT_SCALE: dict[str, float] = {
    "亿元": 1e8, "万万元": 1e8, "万元": 1e4, "千元": 1e3, "元": 1.0,
    "百万": 1e6, "十亿": 1e9, "百亿": 1e10,
    "million": 1e6, "billion": 1e9, "mb": 1e6, "b": 1e9,
}
# 英文单位默认 USD
USD_UNITS = frozenset({"million", "billion", "mb", "b"})

# 容差（唯一权威口径，全包以此为准）
#
# 修正记录（v2.0.0）：此处原为 0.005（0.5%），与其自身注释「相对容差 0.1%」
# 以及 calc-engine.md 所述「Phase 23.7 由 0.5% 收紧到 0.1% 以消除假阳性支持」
# 相矛盾；backend/app/services/verification/base.py 亦为 0.005，说明该次收紧
# 从未落到代码。0.5% 容差会放过 0.1%~0.5% 区间的小幅偏差并判 SUPPORTED
# （即假阳性支持），与设计意图相悖，故本次对齐设计意图改为 0.1%。
# 合法的「披露舍入」差异由 higher-level 的舍入豁免规则处理（上限 0.5%），
# 不在本常量中放宽。需要临时放宽时显式传 --tolerance。
VALUE_TOLERANCE = 0.001        # 绝对数值 / 累计转单季 / 比率：相对容差 0.1%
GROWTH_TOLERANCE_PP = 0.5      # 增长率：±0.5 个百分点
ROUNDING_EXEMPTION_CAP = 0.005  # 披露舍入豁免上限 0.5%（仅当差异可由声明的舍入精度解释）

_PERCENT_TOKENS = ("%", "百分点", "个百分点", "basis points", "bp")


# ---------------------------------------------------------------------------
# 数值解析工具
# ---------------------------------------------------------------------------
_COMMA_CLASS = r"[,､，、]"
_NUMBER_BODY = r"-?\d+(?:" + _COMMA_CLASS + r"\d+)*(?:\.?\d+)?"
_NUMBER_BODY_PLAIN = r"\d+(?:" + _COMMA_CLASS + r"\d+)*(?:\.?\d+)?"
_UNITS_SORTED = sorted((u for u in UNIT_SCALE if u not in ("b", "mb")), key=len, reverse=True)
_UNIT_PATTERN = "|".join(re.escape(u) for u in _UNITS_SORTED)
_PLAIN_RE = re.compile(
    r"(" + _NUMBER_BODY + r")\s*(" + _UNIT_PATTERN + r")?[\s　]*((?:百分点|个百分点|basis\s*points|bp|%)|%)?",
    re.UNICODE | re.IGNORECASE,
)
_PAREN_NEG_RE = re.compile(
    r"\((" + _NUMBER_BODY_PLAIN + r")\)\s*(" + _UNIT_PATTERN + r")?",
    re.UNICODE,
)
_DIRECTION_RE = re.compile(r"(同比增长|同比下降|增长|下降|亏损扩大|亏损收窄|减少|降低|提升|增加)\s*", re.UNICODE)


def _strip_commas(s: str) -> str:
    return re.sub(r"[,､，、]", "", s)


def _detect_sign(text: str, start: int, val: Decimal) -> str:
    if val < 0:
        return "negative_sign"
    prefix = text[max(0, start - 20):start]
    matches = list(_DIRECTION_RE.finditer(prefix))
    if matches:
        word = matches[-1].group(1)
        if any(m in word for m in ("下降", "亏损扩大", "减少", "降低")):
            return "yoy_decline"
        return "positive"
    return "positive"


def extract_financial_values(text, context_unit=None):
    """从文本抽取所有结构化数值，返回 list[dict]。

    忠实实现 backend extract_financial_values 的抽取规则（括号负数优先、
    千分位剥离、方向词符号、单位绑定）。
    """
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("、", ",").replace("，", ",")
    results = []

    for m in _PAREN_NEG_RE.finditer(normalized):
        num_str = _strip_commas(m.group(1))
        try:
            val = Decimal(num_str)
        except Exception:
            continue
        unit = m.group(2) or context_unit or ""
        scale = Decimal(str(UNIT_SCALE.get(unit, 1.0))) if unit else Decimal("1.0")
        currency = "USD" if unit.lower() in USD_UNITS else ("CNY" if unit else "")
        results.append({
            "raw_text": m.group(0).strip(),
            "value": float(abs(val)),
            "scale": float(scale),
            "unit": unit,
            "currency": currency,
            "sign": "negative_paren",
            "value_in_yuan": float(-abs(val) * scale),
        })

    for m in _PLAIN_RE.finditer(normalized):
        raw = m.group(0).strip()
        if any(r["raw_text"] and raw and raw in r["raw_text"] for r in results):
            continue
        num_str = _strip_commas(m.group(1))
        try:
            val = Decimal(num_str)
        except Exception:
            continue
        unit = m.group(2) or context_unit or ""
        pct = m.group(3) or ""
        sign = _detect_sign(normalized, m.start(), val)
        scale = Decimal(str(UNIT_SCALE.get(unit, 1.0))) if unit else Decimal("1.0")
        currency = "USD" if unit.lower() in USD_UNITS else ("CNY" if unit else "")
        abs_val = abs(val)
        yuan = abs_val * scale
        yuan_signed = -yuan if sign in ("negative_paren", "negative_sign", "yoy_decline") else yuan
        pct_type = ("basis_point" if ("basis" in pct.lower() or pct == "bp")
                    else "percentage_point" if ("百分点" in pct or "个百分点" in pct)
                    else "percentage" if "%" in pct else "")
        results.append({
            "raw_text": raw,
            "value": float(abs_val),
            "scale": float(scale),
            "unit": unit,
            "currency": currency,
            "sign": sign,
            "percentage_type": pct_type,
            "value_in_yuan": float(yuan_signed),
        })

    return results


def convert_to_yuan(value, unit=None, sign=None):
    """将数值换算为「元」（含单位 scale 与符号）。"""
    v = Decimal(str(value))
    scale = Decimal(str(UNIT_SCALE.get(unit, 1.0))) if unit else Decimal("1.0")
    base = v * scale
    if sign in ("negative_paren", "negative_sign", "yoy_decline"):
        base = -abs(base)
    return base


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------
def values_match(claim_value, claim_unit, evidence_value_in_yuan, tolerance=VALUE_TOLERANCE):
    """判断主张数值与证据「换算为元后的绝对值」是否匹配。

    与 backend values_match(require_unit=True) 一致：比较 ratio。
    """
    cv = Decimal(str(claim_value)) * Decimal(str(UNIT_SCALE.get(claim_unit, 1.0)))
    ev = Decimal(str(evidence_value_in_yuan))
    if cv == 0 and ev == 0:
        return True, "均为 0"
    if cv == 0 or ev == 0:
        return False, f"一方为 0（claim={cv}, ev={ev}）"
    ratio = ev / cv
    if abs(ratio - Decimal("1.0")) <= Decimal(str(tolerance)):
        return True, f"换算元后匹配（claim={cv:.4f}, ev={ev:.4f}, ratio={ratio:.6f}）"
    return False, f"换算元后不匹配（claim={cv:.4f}, ev={ev:.4f}, ratio={ratio:.6f}）"


# ---------------------------------------------------------------------------
# 增长率
# ---------------------------------------------------------------------------
def yoy(current, previous):
    """同比增长率(%) = (当期 - 上年同期) / 上年同期 * 100。"""
    cur = Decimal(str(current))
    prev = Decimal(str(previous))
    if prev == 0:
        return None, "上年同期为 0，无法计算增长率"
    calc = (cur - prev) / prev * Decimal("100")
    return float(calc), f"( {cur} − {prev} ) / {prev} × 100 = {calc:.4f}%"


def qoq(current, previous):
    """环比增长率(%) = (本期 - 上期) / 上期 * 100。"""
    return yoy(current, previous)


# ---------------------------------------------------------------------------
# 累计转单季
# ---------------------------------------------------------------------------
def derive_quarter(h1=None, q1=None, q2=None, q3=None, q4=None, fy=None):
    """累计转单季推导。

    支持的推导（自动识别已知变量）：
      Q2 = H1 − Q1
      Q3 = 9M(=H1+Q2+Q3) − H1   （此处 9m 直接传入该季末累计，简化为 H1 之后部分）
      Q4 = FY − Q1 − Q2 − Q3
      H1 = Q1 + Q2
      FY = Q1 + Q2 + Q3 + Q4
    返回 (calculated_value_or_None, formula, detail)
    """
    if h1 is not None and q1 is not None:
        res = Decimal(str(h1)) - Decimal(str(q1))
        return float(res), "Q2 = H1 − Q1", {"h1": h1, "q1": q1, "q2": float(res)}
    if h1 is not None and q2 is not None:
        res = Decimal(str(h1)) - Decimal(str(q2))
        return float(res), "Q1 = H1 − Q2", {"h1": h1, "q2": q2, "q1": float(res)}
    if fy is not None and q1 is not None and q2 is not None and q3 is not None:
        res = Decimal(str(fy)) - Decimal(str(q1)) - Decimal(str(q2)) - Decimal(str(q3))
        return float(res), "Q4 = FY − Q1 − Q2 − Q3", {"fy": fy, "q1": q1, "q2": q2, "q3": q3, "q4": float(res)}
    if q1 is not None and q2 is not None:
        res = Decimal(str(q1)) + Decimal(str(q2))
        return float(res), "H1 = Q1 + Q2", {"q1": q1, "q2": q2, "h1": float(res)}
    if q1 is not None and q2 is not None and q3 is not None and q4 is not None:
        res = Decimal(str(q1)) + Decimal(str(q2)) + Decimal(str(q3)) + Decimal(str(q4))
        return float(res), "FY = Q1 + Q2 + Q3 + Q4", {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "fy": float(res)}
    return None, "无法推导：需给定 (H1 与 Q1) 或 (FY 与 Q1,Q2,Q3) 等组合", {}


# ---------------------------------------------------------------------------
# 比率
# ---------------------------------------------------------------------------
def margin(revenue, cost=None, net_profit=None, expense=None, segment_revenue=None):
    """毛利率/净利率/费用率/业务占比。

    仅计算给定参数的比率，返回 dict。
    """
    out = {}
    rev = Decimal(str(revenue)) if revenue is not None else None
    if rev and cost is not None:
        out["gross_margin_pct"] = float((Decimal(str(cost)) and (rev - Decimal(str(cost)))) / rev * Decimal("100"))
    if rev and net_profit is not None:
        out["net_margin_pct"] = float(Decimal(str(net_profit)) / rev * Decimal("100"))
    if rev and expense is not None:
        out["expense_ratio_pct"] = float(Decimal(str(expense)) / rev * Decimal("100"))
    if rev and segment_revenue is not None:
        out["business_share_pct"] = float(Decimal(str(segment_revenue)) / rev * Decimal("100"))
    return out


def cagr(end_value, start_value, years):
    """CAGR(%) = (末期/初期)^(1/年数) − 1，再 ×100。"""
    ev = Decimal(str(end_value))
    sv = Decimal(str(start_value))
    n = Decimal(str(years))
    if sv == 0 or n == 0:
        return None, "初期值或年数为 0"
    rate = (ev / sv) ** (Decimal("1") / n) - Decimal("1")
    return float(rate * Decimal("100")), f"({ev}/{sv})^(1/{n}) − 1 = {rate:.6f}"


def eps(net_profit, shares):
    """EPS = 净利润 / 总股本。"""
    return float(Decimal(str(net_profit)) / Decimal(str(shares)))


def roe(net_profit, avg_equity):
    """ROE(%) = 净利润 / 平均净资产 × 100。"""
    return float(Decimal(str(net_profit)) / Decimal(str(avg_equity)) * Decimal("100"))


def debt_ratio(total_liability, total_assets):
    """资产负债率(%) = 总负债 / 总资产 × 100。"""
    return float(Decimal(str(total_liability)) / Decimal(str(total_assets)) * Decimal("100"))


def cashflow_diff(operating_cashflow, net_profit):
    """经营现金流净额 − 净利润（差异异常需提示）。"""
    diff = Decimal(str(operating_cashflow)) - Decimal(str(net_profit))
    return float(diff), f"{operating_cashflow} − {net_profit} = {diff:.4f}"


# ---------------------------------------------------------------------------
# 期间归一化（简化版 PeriodContext）
# ---------------------------------------------------------------------------
_STD_PERIOD_RE = re.compile(r"(\d{4})(?:FY|Q([1-4])|H([1-2]))", re.IGNORECASE)
_ANNUAL_RE = re.compile(r"(年度|年报|全年|FY|annual)", re.IGNORECASE)
_SEMI_RE = re.compile(r"(半年度|中报|半年报|H1|semi|interim)", re.IGNORECASE)
_QN_RE = {1: re.compile(r"(Q1|第一季度|一季)", re.IGNORECASE),
          3: re.compile(r"(Q3|第三季度|三季)", re.IGNORECASE)}
_YTD_RE = re.compile(r"(年初至今|本报告期|累计|YTD|cumulative)", re.IGNORECASE)
_STANDALONE_RE = re.compile(r"(单季|单季度|standalone|环比)", re.IGNORECASE)
_YOY_BASE_RE = re.compile(r"(上年同期|去年同期|比上年|上年|去年|同比)")


def parse_period(period_str):
    """将期间字符串归一化为标准结构（YYYYFY / YYYYH1 / YYYYQn 等）。

    返回 dict：fiscal_year / fiscal_quarter / document_type / standalone_or_cumulative / yoy_base_period。
    """
    if not period_str:
        return {"fiscal_year": None, "fiscal_quarter": None, "document_type": "unknown",
                "standalone_or_cumulative": "unknown", "yoy_base_period": None}
    text = period_str.strip()
    year = None
    quarter = None
    doc_type = "unknown"
    standalone_cumul = "unknown"

    m = _STD_PERIOD_RE.search(text)
    if m:
        year = int(m.group(1))
        if m.group(2):
            quarter = int(m.group(2))
            doc_type = {1: "q1", 3: "q3"}.get(quarter, "unknown")
        elif m.group(3):
            quarter = None
            doc_type = "semi" if int(m.group(3)) == 1 else "annual"

    if year is None:
        ym = re.search(r"(\d{4})", text)
        if ym:
            year = int(ym.group(1))

    if _ANNUAL_RE.search(text):
        doc_type = "annual"
        quarter = None
    elif _SEMI_RE.search(text):
        doc_type = "semi"
        quarter = None
    elif _QN_RE[1].search(text):
        quarter = 1
        doc_type = "q1"
    elif _QN_RE[3].search(text):
        quarter = 3
        doc_type = "q3"

    if _YTD_RE.search(text):
        standalone_cumul = "cumulative" if ("Q" in text or quarter) else "ytd"
    if _STANDALONE_RE.search(text):
        standalone_cumul = "standalone"
    if standalone_cumul == "unknown":
        if doc_type in ("annual", "semi"):
            standalone_cumul = "cumulative"
        elif quarter == 1:
            standalone_cumul = "standalone"
        elif quarter == 3:
            standalone_cumul = "cumulative"

    yoy_base = None
    if _YOY_BASE_RE.search(text) and year:
        yoy_base = f"{year-1}FY" if doc_type == "annual" else f"{year-1}Q{quarter or 1}"

    return {"fiscal_year": year, "fiscal_quarter": quarter, "document_type": doc_type,
            "standalone_or_cumulative": standalone_cumul, "yoy_base_period": yoy_base}


# ---------------------------------------------------------------------------
# 引用时序检查（v2.6.2）：来源覆盖期间 vs 数据所属期间
#
# 背景：SKILL §五-5 的"时序不可能"原为模型语义判定，实测执行一致性不稳
# （第四轮 run1 漏判、run2 命中）。本子命令把该纯逻辑判定收敛为确定性
# 输出——"逻辑判定归程序"，与"数字归程序"同理。
# ---------------------------------------------------------------------------
_FULL_DATE_RE = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})")
_YEAR_MONTH_RE = re.compile(r"(\d{4})[-/年.](\d{1,2})(?![/-]\d)")
_BARE_YEAR_RE = re.compile(r"^\D*(\d{4})\D*$")

# 顺序敏感：先长词/累计口径，后短语/单季口径（"下半年"须先于"半年"，"前三季"先于"第三季"）
_WINDOW_KEYWORDS = [
    ("cumulative_9m", re.compile(r"(前三季|三季报|三季度报告|Q3报告|第三季度报告|9M)", re.IGNORECASE)),
    ("h2",            re.compile(r"(下半年|H2)", re.IGNORECASE)),
    ("h1",            re.compile(r"(上半年|半年|中报|半年度|H1|semi|interim)", re.IGNORECASE)),
    ("annual",        re.compile(r"(年报|年度|全年|FY|annual)", re.IGNORECASE)),
    ("q4",            re.compile(r"(第四季度|Q4)", re.IGNORECASE)),
    ("q3_standalone", re.compile(r"(第三季度|Q3)", re.IGNORECASE)),
    ("q2",            re.compile(r"(第二季度|Q2)", re.IGNORECASE)),
    ("q1",            re.compile(r"(一季报|第一季度|Q1|一季)", re.IGNORECASE)),
]

_WINDOW_RANGES = {  # kind -> (start_md, end_md)
    "annual":        ("01-01", "12-31"),
    "h1":            ("01-01", "06-30"),
    "h2":            ("07-01", "12-31"),
    "cumulative_9m": ("01-01", "09-30"),
    "q1":            ("01-01", "03-31"),
    "q2":            ("04-01", "06-30"),
    "q3_standalone": ("07-01", "09-30"),
    "q4":            ("10-01", "12-31"),
}


def _month_days(year: int, month: int) -> int:
    if month == 2:
        return 29 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 28
    return (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]


def period_window(text):
    """把期间/来源描述解析为日期窗口。

    返回 (start_iso, end_iso, kind)；无法解析返回 (None, None, "unclear")。
    kind ∈ annual/h1/h2/cumulative_9m/q1/q2/q3_standalone/q4/month/day/year_only。
    ISO 日期字符串可按字典序直接比较。
    """
    if not text or not text.strip():
        return None, None, "unclear"
    t = text.strip()

    m = _FULL_DATE_RE.search(t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        iso = f"{y:04d}-{mo:02d}-{d:02d}"
        return iso, iso, "day"

    m = _YEAR_MONTH_RE.search(t)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return (f"{y:04d}-{mo:02d}-01", f"{y:04d}-{mo:02d}-{_month_days(y, mo):02d}", "month")

    ym = re.search(r"(\d{4})", t)
    if ym:
        y = int(ym.group(1))
        for kind, rx in _WINDOW_KEYWORDS:
            if rx.search(t):
                s_md, e_md = _WINDOW_RANGES[kind]
                return f"{y:04d}-{s_md}", f"{y:04d}-{e_md}", kind
        m2 = _BARE_YEAR_RE.match(t)
        if m2:
            return f"{y:04d}-01-01", f"{y:04d}-12-31", "year_only"

    return None, None, "unclear"


def temporal_check(source, data):
    """引用时序检查：来源覆盖期间 vs 数据所属期间。

    verdict：
      IMPOSSIBLE — 来源覆盖期完全早于数据所属期（来源在逻辑上不可能包含该数据）
                   → 引用一致性·时序不可能，直接反驳，无需证据闭环（G1 不得收容）
      COVERED    — 数据所属期完全落在来源覆盖期内（时序可行）
      PARTIAL    — 数据所属期部分超出来源覆盖期（超出部分不可能来自该来源，
                   语义层裁量部分支持/反驳）
      UNCLEAR    — 期间无法解析，引擎不猜，退回模型语义判定
    """
    ss, se, sk = period_window(source)
    ds, de, dk = period_window(data)
    out = {
        "source": {"text": source, "window": (ss, se), "kind": sk},
        "data": {"text": data, "window": (ds, de), "kind": dk},
    }
    if ss is None or ds is None:
        bad = "来源" if ss is None else ("数据" if ds is None else "来源与数据")
        out["verdict"] = "UNCLEAR"
        out["reason"] = f"{bad}期间无法解析为日期窗口，引擎不猜——退回模型语义判定（引用三对齐人工核）"
        return out
    if se < ds:
        out["verdict"] = "IMPOSSIBLE"
        out["reason"] = (f"来源覆盖 {ss}~{se}，数据所属 {ds}~{de}：来源期间早于数据期间，"
                         f"逻辑上不可能包含该数据 → 引用一致性·时序不可能，直接反驳，无需证据闭环（G1 不得收容）")
    elif ds >= ss and de <= se:
        out["verdict"] = "COVERED"
        out["reason"] = f"来源覆盖 {ss}~{se} ⊇ 数据所属 {ds}~{de}：时序可行"
    else:
        out["verdict"] = "PARTIAL"
        out["reason"] = (f"数据所属 {ds}~{de} 部分超出来源覆盖 {ss}~{se}："
                         f"超出部分不可能来自该来源，语义层裁量（部分支持/反驳）")
    return out


def sum_check(values, total, tolerance=VALUE_TOLERANCE):
    """总和一致性检查：分项之和 vs 合计（通用数值复算的确定性实现）。

    values: 分项列表（数字或字符串）；total: 报告合计值。
    返回 dict：sum / total / abs_diff / rel_diff_pct / matched（相对容差 0.1%）。
    典型用途：SOTP 分项 vs 合计、成本明细 vs 总成本、分部收入 vs 总收入。
    """
    parts = []
    for v in values:
        try:
            parts.append(Decimal(str(v)))
        except (ArithmeticError, ValueError):
            raise ValueError(f"分项含非数字：{v!r}（应为逗号分隔的数字列表，如 '117.0,88.9'）")
    try:
        tot = Decimal(str(total))
    except (ArithmeticError, ValueError):
        raise ValueError(f"合计值非数字：{total!r}")
    calc = sum(parts, Decimal("0"))
    diff = calc - tot
    rel = abs(diff) / abs(tot) if tot != 0 else (Decimal("0") if diff == 0 else None)
    matched = rel is not None and rel <= Decimal(str(tolerance))
    return {
        "sum": float(calc),
        "total": float(tot),
        "abs_diff": float(diff),
        "rel_diff_pct": float(rel * 100) if rel is not None else None,
        "tolerance": tolerance,
        "matched": matched,
        "parts": [float(p) for p in parts],
        "reason": (f"分项之和 {calc} vs 合计 {tot}，相对差 {rel*100:.4f}% ≤ {tolerance*100:.1f}% → 一致"
                   if matched else
                   f"分项之和 {calc} vs 合计 {tot}，相对差 {rel*100:.4f}% > {tolerance*100:.1f}% → 不一致（超容差）"),
    }


# ---------------------------------------------------------------------------
# 预测事实化扫描（v2.8.1）：确定性措辞 + 依据披露
#
# 背景：SKILL 要求"带确定性措辞的预测进问题项"，但实测执行不一致——第一轮
# 鉴融 15/18 vs 基线 17/18，丢分点正是 E7："已无悬念"未按自身规则点出"依据
# 未披露"。本子命令把该判定收敛为确定性输出，不依赖模型自觉。
# ---------------------------------------------------------------------------
_STRONG_CERTAINTY = (
    "已无悬念", "毫无悬念", "板上钉钉", "毫无疑问", "毋庸置疑", "不容置疑",
    "必将", "必然", "必定", "铁定", "锁定", "确保", "将达", "将达到", "笃定",
)
_WEAK_CERTAINTY = ("一定", "肯定", "确定", "稳了", "保证")
_FORECAST_HINTS = (
    "预计", "预测", "有望", "展望", "目标", "指引", "未来", "明年", "后年",
    "计划", "将", "估算", "测算",
)
# 否定/限定语境：先遮蔽，避免"不一定/一定程度上/不确定"被误报
_MASK_PHRASES = (
    "不一定", "不确定", "未确定", "无法确定", "尚不确定", "难以确定", "难以保证",
    "无法确保", "不能确保", "一定程度上", "某种程度上", "未必", "难说",
)


def _mask(text: str) -> str:
    t = text or ""
    for ph in _MASK_PHRASES:
        t = t.replace(ph, "□" * len(ph))
    return t


def forecast_scan(text, evidence_ids=None, has_method=False):
    """预测事实化扫描。

    判定：预测语境 + 确定性措辞 + 依据未披露 → forecast_as_fact。
    依据披露 = 显式给出证据编号（[E##]）或报告披露了测算方法/假设。
    """
    masked = _mask(text)
    strong = [w for w in _STRONG_CERTAINTY if w in masked]
    weak = [w for w in _WEAK_CERTAINTY if w in masked]
    forecast_like = any(h in masked for h in _FORECAST_HINTS) or bool(strong)
    basis = bool(evidence_ids) or bool(has_method)
    flagged = forecast_like and bool(strong or weak) and not basis
    if flagged:
        reason = (f"预测语境 + 确定性措辞（{'、'.join(strong + weak)}）+ 依据未披露"
                  f" → 预测事实化，进审计结论问题项（结论仍为观点或预测，不判真假）")
    elif forecast_like and (strong or weak) and basis:
        reason = "预测语境 + 确定性措辞，但依据已披露（证据编号/测算方法）→ 不判预测事实化"
    elif forecast_like:
        reason = "预测语境，未见确定性措辞 → 常规观点或预测条目"
    else:
        reason = "非预测语境 → 不适用预测事实化规则"
    return {
        "text": text,
        "strong_hits": strong,
        "weak_hits": weak,
        "forecast_like": forecast_like,
        "basis_disclosed": basis,
        "forecast_as_fact": flagged,
        "verdict": "FLAG" if flagged else "CLEAN",
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# 引用真伪核验（v2.8.1）：链接可达 / 摘录逐字命中 / 来源日期与数据期间一致
#
# 背景：编造引用与张冠李戴是 AI 报告最典型的失效模式，而裸提示结构上不会去
# 点链接、比对摘录。SKILL 原有"链接复验"流程要求，但没有确定性工具、没有
# 强制门——第四轮 E5（引用期间错配）十轮全灭正是这个缺口。
# ---------------------------------------------------------------------------
_UA = "Mozilla/5.0 (compatible; FinProof/2.8.1; citation-audit)"
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_QUOTE_MAP = str.maketrans({
    "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
    "\u2014": "-", "\u2013": "-", "\u2026": "...",
})


def _html_to_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return html_lib.unescape(s)


def _normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(_QUOTE_MAP)
    s = _ZERO_WIDTH_RE.sub("", s)
    return re.sub(r"\s+", "", s).lower()


def _excerpt_parts(excerpt: str):
    """逐字摘录允许用 … 省略中间：每段都必须命中。"""
    return [p for p in (_normalize_text(x) for x in re.split(r"\.\.\.|\u2026", excerpt or "")) if p]


def _load_source(url=None, file=None, timeout=10.0):
    """返回 (reachable, status, final_url, page_text, error)。file 优先（离线快照）。"""
    if file:
        if not os.path.exists(file):
            return False, None, f"file://{file}", "", "本地快照不存在（离线模拟不可达）"
        try:
            raw = open(file, encoding="utf-8", errors="replace").read()
        except OSError as e:
            return False, None, f"file://{file}", "", f"快照读取失败：{e}"
        text = _html_to_text(raw) if file.lower().endswith((".html", ".htm")) else raw
        return True, 200, f"file://{file}", text, ""
    if not url:
        return False, None, "", "", "未提供 url 或 file"
    target = url.strip()
    if re.match(r"^10\.\d{4,9}/", target):        # DOI → https://doi.org/
        target = "https://doi.org/" + target
    if not re.match(r"^https?://", target, re.IGNORECASE):
        return False, None, target, "", f"不支持的 URL 协议：{target[:40]}"
    try:
        req = urllib.request.Request(target, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            final = resp.geturl()
            raw = resp.read(2_000_000).decode("utf-8", errors="replace")
        return True, status, final, _html_to_text(raw), ""
    except urllib.error.HTTPError as e:
        return False, e.code, target, "", f"HTTP {e.code}"
    except Exception as e:  # URLError / timeout / SSL ...
        return False, None, target, "", f"不可达（{type(e).__name__}: {e}）"


def cite_check(url=None, excerpt=None, source_date=None, period=None,
               file=None, timeout=10.0):
    """引用真伪核验。

    verdict：PASS = 可达 + 摘录逐字命中 + 时序可行；
             FAIL = 任一项不通过（不可达 / 摘录未命中 / 时序不可能）。
    未提供的检查项记 None，不参与判定（但报告须说明为何未检）。
    """
    reachable, status, final_url, page_text, err = _load_source(url=url, file=file, timeout=timeout)

    excerpt_found = None
    if excerpt and reachable:
        norm = _normalize_text(page_text)
        parts = _excerpt_parts(excerpt)
        excerpt_found = bool(parts) and all(p in norm for p in parts)

    date_ok, date_reason, window = None, "", None
    if source_date and period:
        m = _FULL_DATE_RE.search(source_date)
        ds, de, dk = period_window(period)
        window = (ds, de, dk)
        if not m or ds is None:
            date_reason = "来源日期或数据期间无法解析，引擎不猜（退回人工核）"
        else:
            sd = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            if sd < de:
                date_ok = False
                date_reason = (f"来源发布日期 {sd} 早于数据期间结束 {de}"
                               f"（数据期间 {ds}~{de}）→ 时序不可能，该来源无法支撑该数据")
            else:
                date_ok = True
                date_reason = f"来源发布日期 {sd} ≥ 数据期间结束 {de} → 时序可行"

    fails = []
    if not reachable:
        fails.append("不可达")
    if excerpt_found is False:
        fails.append("摘录未命中")
    if date_ok is False:
        fails.append("时序不可能")
    verdict = "FAIL" if fails else "PASS"

    if not reachable:
        reason = f"FAIL·不可达：{err}"
    elif excerpt_found is False:
        reason = "FAIL·摘录未命中：页面可达，但逐字摘录未出现（疑似张冠李戴或编造引文）"
    elif date_ok is False:
        reason = f"FAIL·时序不可能：{date_reason}"
    else:
        bits = [f"链接可达（HTTP {status}）"]
        if excerpt_found:
            bits.append("摘录逐字命中")
        if date_ok:
            bits.append("时序可行")
        missing = [n for n, v in (("摘录", excerpt_found), ("时序", date_ok)) if v is None]
        if missing:
            bits.append("未检：" + "、".join(missing))
        reason = "PASS：" + "；".join(bits)

    return {
        "url": url,
        "source": final_url,
        "reachable": reachable,
        "status": status,
        "excerpt": excerpt,
        "excerpt_found": excerpt_found,
        "source_date": source_date,
        "period": period,
        "period_window": window,
        "date_ok": date_ok,
        "date_reason": date_reason,
        "verdict": verdict,
        "fails": fails,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _f(x):
    return float(x) if x is not None else None


def build_parser():
    p = argparse.ArgumentParser(description="FinProof 确定性财务计算引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("convert", help="单位/币种换算为元")
    sp.add_argument("--value", type=float, required=True)
    sp.add_argument("--unit", default="")
    sp.add_argument("--sign", default="")

    sp = sub.add_parser("extract", help="从文本抽取结构化数值")
    sp.add_argument("--text", required=True)
    sp.add_argument("--unit", default="")

    sp = sub.add_parser("match", help="主张数值 vs 证据数值匹配")
    sp.add_argument("--claim", type=float, required=True)
    sp.add_argument("--claim-unit", default="")
    sp.add_argument("--evidence-yuan", type=float, required=True)
    sp.add_argument("--tolerance", type=float, default=VALUE_TOLERANCE)

    sp = sub.add_parser("yoy", help="同比增长率")
    sp.add_argument("--current", type=float, required=True)
    sp.add_argument("--previous", type=float, required=True)

    sp = sub.add_parser("qoq", help="环比增长率")
    sp.add_argument("--current", type=float, required=True)
    sp.add_argument("--previous", type=float, required=True)

    sp = sub.add_parser("quarter", help="累计转单季推导")
    sp.add_argument("--h1", type=float, default=None)
    sp.add_argument("--q1", type=float, default=None)
    sp.add_argument("--q2", type=float, default=None)
    sp.add_argument("--q3", type=float, default=None)
    sp.add_argument("--q4", type=float, default=None)
    sp.add_argument("--fy", type=float, default=None)

    sp = sub.add_parser("margin", help="毛利率/净利率/费用率/业务占比")
    sp.add_argument("--revenue", type=float, required=True)
    sp.add_argument("--cost", type=float, default=None)
    sp.add_argument("--net-profit", type=float, default=None)
    sp.add_argument("--expense", type=float, default=None)
    sp.add_argument("--segment-revenue", type=float, default=None)

    sp = sub.add_parser("cagr", help="CAGR")
    sp.add_argument("--end", type=float, required=True)
    sp.add_argument("--start", type=float, required=True)
    sp.add_argument("--years", type=float, required=True)

    sp = sub.add_parser("eps", help="EPS")
    sp.add_argument("--net-profit", type=float, required=True)
    sp.add_argument("--shares", type=float, required=True)

    sp = sub.add_parser("roe", help="ROE")
    sp.add_argument("--net-profit", type=float, required=True)
    sp.add_argument("--avg-equity", type=float, required=True)

    sp = sub.add_parser("debt", help="资产负债率")
    sp.add_argument("--liability", type=float, required=True)
    sp.add_argument("--assets", type=float, required=True)

    sp = sub.add_parser("cashdiff", help="经营现金流−净利润")
    sp.add_argument("--ocf", type=float, required=True)
    sp.add_argument("--net-profit", type=float, required=True)

    sp = sub.add_parser("period", help="期间归一化")
    sp.add_argument("--period", required=True)

    sp = sub.add_parser("temporal", help="引用时序检查：来源覆盖期间 vs 数据所属期间（IMPOSSIBLE/COVERED/PARTIAL/UNCLEAR）")
    sp.add_argument("--source", required=True, help="来源描述，如 '2025年年度报告' / '2026-06-30'")
    sp.add_argument("--data", required=True, help="数据所属期间，如 '2026年上半年' / '2026Q1'")

    # 注意：argparse 会对 help 串做 % 格式化，字面百分号必须写成 %%
    sp = sub.add_parser("forecast_scan", help="预测事实化扫描：确定性措辞 + 依据披露 → FLAG/CLEAN")
    sp.add_argument("--text", required=True, help="主张原文")
    sp.add_argument("--evidence-ids", default="", help="已挂证据编号，逗号分隔（如 'E01,E02'）")
    sp.add_argument("--has-method", action="store_true", help="报告披露了测算方法/假设")

    sp = sub.add_parser("cite_check", help="引用真伪核验：链接可达 / 摘录命中 / 日期-期间一致")
    sp.add_argument("--url", default=None, help="证据链接或 DOI")
    sp.add_argument("--file", default=None, help="离线快照文件（优先于 --url，用于归档/测试）")
    sp.add_argument("--excerpt", default=None, help="逐字摘录（可用 … 省略中间）")
    sp.add_argument("--source-date", default=None, help="来源发布日期，如 2026-04-24")
    sp.add_argument("--period", default=None, help="数据所属期间，如 2026Q1 / 2026年上半年")
    sp.add_argument("--timeout", type=float, default=10.0)

    sp = sub.add_parser("sum_check", help="总和一致性：分项之和 vs 合计（相对容差 0.1%%）")

    sp.add_argument("--values", required=True, help="分项，逗号分隔，如 '117.0,88.9'")
    sp.add_argument("--total", type=float, required=True, help="报告合计值")
    sp.add_argument("--tolerance", type=float, default=VALUE_TOLERANCE)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (ValueError, ArithmeticError) as e:
        # 引擎契约：任何输入错误都以 JSON 返回并退出码 2，不抛裸 traceback
        _out({"error": str(e)})
        return 2


def _dispatch(args):
    cmd = args.cmd

    if cmd == "convert":
        yuan = convert_to_yuan(args.value, args.unit or None, args.sign or None)
        _out({"value": args.value, "unit": args.unit, "currency":
              ("USD" if (args.unit or "").lower() in USD_UNITS else ("CNY" if args.unit else "")),
              "value_in_yuan": float(yuan)})
    elif cmd == "extract":
        _out({"values": extract_financial_values(args.text, args.unit or None)})
    elif cmd == "match":
        ok, reason = values_match(args.claim, args.claim_unit, args.evidence_yuan, args.tolerance)
        _out({"matched": ok, "reason": reason, "tolerance": args.tolerance})
    elif cmd == "yoy":
        val, detail = yoy(args.current, args.previous)
        _out({"yoy_pct": val, "detail": detail})
    elif cmd == "qoq":
        val, detail = qoq(args.current, args.previous)
        _out({"qoq_pct": val, "detail": detail})
    elif cmd == "quarter":
        val, formula, detail = derive_quarter(args.h1, args.q1, args.q2, args.q3, args.q4, args.fy)
        _out({"result": val, "formula": formula, "detail": detail})
    elif cmd == "margin":
        _out({"margins": margin(args.revenue, args.cost, args.net_profit, args.expense, args.segment_revenue)})
    elif cmd == "cagr":
        val, detail = cagr(args.end, args.start, args.years)
        _out({"cagr_pct": val, "detail": detail})
    elif cmd == "eps":
        _out({"eps": eps(args.net_profit, args.shares)})
    elif cmd == "roe":
        _out({"roe_pct": roe(args.net_profit, args.avg_equity)})
    elif cmd == "debt":
        _out({"debt_ratio_pct": debt_ratio(args.liability, args.assets)})
    elif cmd == "cashdiff":
        val, detail = cashflow_diff(args.ocf, args.net_profit)
        _out({"diff": val, "detail": detail})
    elif cmd == "period":
        _out(parse_period(args.period))
    elif cmd == "temporal":
        _out(temporal_check(args.source, args.data))
    elif cmd == "forecast_scan":
        ids = [x.strip() for x in args.evidence_ids.split(",") if x.strip()]
        _out(forecast_scan(args.text, evidence_ids=ids, has_method=args.has_method))
    elif cmd == "cite_check":
        _out(cite_check(url=args.url, excerpt=args.excerpt, source_date=args.source_date,
                        period=args.period, file=args.file, timeout=args.timeout))
    elif cmd == "sum_check":
        vals = [v.strip() for v in args.values.split(",") if v.strip()]
        _out(sum_check(vals, args.total, args.tolerance))
    else:
        _out({"error": f"unknown command {cmd}"})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
