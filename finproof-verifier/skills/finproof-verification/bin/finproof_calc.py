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

所有子命令以 JSON 输出结果，便于专家逐步核对（对应审计轨迹）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
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
    parts = [Decimal(str(v)) for v in values]
    tot = Decimal(str(total))
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

    sp = sub.add_parser("sum_check", help="总和一致性：分项之和 vs 合计（相对容差 0.1%）")
    sp.add_argument("--values", required=True, help="分项，逗号分隔，如 '117.0,88.9'")
    sp.add_argument("--total", type=float, required=True, help="报告合计值")
    sp.add_argument("--tolerance", type=float, default=VALUE_TOLERANCE)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
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
    elif cmd == "sum_check":
        vals = [v.strip() for v in args.values.split(",") if v.strip()]
        _out(sum_check(vals, args.total, args.tolerance))
    else:
        _out({"error": f"unknown command {cmd}"})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
