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
  saturation_scan 规模饱和扫：零 token 机械复算全文自洽点（表内加总/占比列/同句同比/引用时序/预测）

所有子命令以 JSON 输出结果，便于专家逐步核对（对应审计轨迹）。
"""

from __future__ import annotations

import argparse
import datetime
import html as html_lib
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from urllib.parse import urlparse
from decimal import Decimal, getcontext

# 高精度，避免浮点误差
getcontext().prec = 28

# ---------------------------------------------------------------------------
# 单位与 scale 映射（与 backend financial_value.UNIT_SCALE 完全一致）
# ---------------------------------------------------------------------------
UNIT_SCALE: dict[str, float] = {
    "亿元": 1e8, "万万元": 1e8, "万元": 1e4, "千元": 1e3, "元": 1.0,
    "百万": 1e6, "十亿": 1e9, "百亿": 1e10,
    # 带「元」的复合中文单位（真实财报写法；CFR-NumQA 540 道抽取题里大量使用，
    # 原表只有「百万」没有「百万元」，导致 convert 静默按 1 倍处理，差 1e6）
    "十万元": 1e5, "百万元": 1e6, "千万元": 1e7,
    "十亿元": 1e9, "百亿元": 1e10, "千亿元": 1e11, "万亿元": 1e12,
    "万亿": 1e12, "千万": 1e7,
    "million": 1e6, "billion": 1e9, "mb": 1e6, "b": 1e9,
}
# 英文单位默认 USD
USD_UNITS = frozenset({"million", "billion", "mb", "b"})

# ── 单位归一化（v2.15.0）──────────────────────────────────────────
# 真实写法远比上表自由：「亿美元」「万元人民币」「million USD」「billion USD」
# 这些原先全部走 get(unit, 1.0) 静默按 1 倍处理——差 1e4~1e9，且无任何警告。
# 现改为「解析量级词 + 货币词」，解析不出来就抛错，不再静默。
_CUR_WORDS = {
    "usd": "USD", "us$": "USD", "$": "USD", "美元": "USD", "美金": "USD",
    "cny": "CNY", "rmb": "CNY", "¥": "CNY", "￥": "CNY", "人民币": "CNY", "元": "CNY",
    "hkd": "HKD", "hk$": "HKD", "港元": "HKD", "港币": "HKD",
    "eur": "EUR", "€": "EUR", "欧元": "EUR",
}
# 量级词按长度降序，防止「亿」截掉「万亿」
_SCALE_WORDS = [
    ("万亿", 1e12), ("千亿", 1e11), ("百亿", 1e10), ("十亿", 1e9), ("亿", 1e8),
    ("千万", 1e7), ("百万", 1e6), ("十万", 1e5), ("万", 1e4), ("千", 1e3),
    ("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3),
    ("bn", 1e9), ("mn", 1e6), ("mm", 1e6), ("k", 1e3),
]
# 物理计量单位：财务报告里也大量出现（产量、能耗、面积、门店数），
# 不能因为不是货币就当成 unknown 丢掉。按长度降序，保证「吨标准煤」先于「吨」。
_PHYSICAL_UNITS = (
    "吨标准煤", "千瓦时", "平方米", "立方米", "平方公里", "平方英尺", "平方千米",
    "千瓦", "兆瓦", "吉瓦", "公顷", "公里", "千米", "加仑", "盎司", "克拉",
    "吨", "桶", "头", "只", "羽", "台", "套", "辆", "架", "艘", "件", "人",
    "户", "家", "座", "条", "亩", "升", "度", "瓦",
)
_PHYS_ALT = "|".join(re.escape(x) for x in _PHYSICAL_UNITS)
# 允许「吨/年」「立方米/日」这类速率单位；只吸收单位后缀，不吸收后面的正文。
_PHYS_RE = re.compile(r"^(?:" + _PHYS_ALT + r")(?:/[年月日人台吨]{1,3})?")
# 「百万/十万/万」等本身可当单位（不含「元」），须先于量级词归一
_UNIT_TO_CUR = {"百万元": "CNY", "千元": "CNY", "万元": "CNY", "亿元": "CNY", "元": "CNY",
                "million": "USD", "billion": "USD", "mb": "USD", "b": "USD",
                "百万元人民币": "CNY", "亿元人民币": "CNY", "万元人民币": "CNY"}


def _unit_currency(u_lower: str):
    """从单位串里解析货币，长词优先（「港元」要先于「元」）。"""
    for k in sorted(_CUR_WORDS, key=len, reverse=True):
        if k in u_lower:
            return _CUR_WORDS[k]
    return None


# 比率类单位：不做金额换算，但必须被识别（否则百分比/百分点会被判为未知单位）
_RATIO_UNITS = frozenset({"%", "％", "percent", "percentage", "pct",
                          "pp", "percentage_point", "个百分点", "百分点",
                          "bp", "basis point", "basis points"})


def _physical_unit_of(u: str):
    """识别物理单位（可带量级前缀），返回 (完整单位, scale) 或 None。"""
    pm = _PHYS_RE.fullmatch(u)
    if pm:
        return pm.group(0), Decimal("1")
    for w, s in _SCALE_WORDS:
        if u.startswith(w):
            pm = _PHYS_RE.fullmatch(u[len(w):])
            if pm:
                return w + pm.group(0), Decimal(str(s))
    return None


def parse_unit(unit):
    """把单位串解成 (scale, currency)。解析不出来就抛 ValueError。

    不再用 get(unit, 1.0) 兜底：那会把「亿美元」当成 1 倍，静默差 1e8。
    物理单位（万吨/亿千瓦时）返回 scale 但 currency=None。
    """
    if unit is None:
        return Decimal("1"), None
    raw = str(unit).strip()
    if not raw:
        return Decimal("1"), None
    u = raw.lower().replace(" ", "")
    if u in _RATIO_UNITS:
        return Decimal("1"), None
    if raw in UNIT_SCALE:
        return Decimal(str(UNIT_SCALE[raw])), _unit_currency(u)

    phys = _physical_unit_of(u)
    if phys:
        return phys[1], None
    cur = _unit_currency(u)
    scale = None
    for w, s in _SCALE_WORDS:
        if w in u:
            scale = s
            break
    if scale is None:
        # 允许纯货币（「USD」、「人民币」）按 1 倍
        if cur is not None:
            return Decimal("1"), cur
        raise ValueError(f"未知单位：{raw!r}（不再按 1 倍静默处理，请换算为元或补全单位）")
    return Decimal(str(scale)), cur


def unit_kind(unit) -> str:
    """单位类别：currency / ratio / physical / scalar / unknown。"""
    if not unit:
        return "scalar"
    u = str(unit).strip().lower().replace(" ", "")
    if u in _RATIO_UNITS:
        return "ratio"
    if _physical_unit_of(u):
        return "physical"
    try:
        _scale, cur = parse_unit(unit)
    except ValueError:
        return "unknown"
    return "currency" if cur else "scalar"


def ratio_subkind(unit) -> str:
    """比率的细分口径：percent / pp / bp；非比率返回空串。"""
    u = str(unit or "").strip().lower().replace(" ", "")
    if "百分点" in u or u == "pp":
        return "pp"
    if "bp" in u or "basis" in u:
        return "bp"
    if "%" in u or "percent" in u or "pct" in u:
        return "percent"
    return ""


def physical_dimension(unit) -> str:
    """物理单位的量纲（去掉量级前缀），如 万吨→吨、亿千瓦时→千瓦时。

    先判完整单位：千瓦/千米本身就是单位，不能被误拆成「千 + 瓦/米」。
    """
    u = str(unit or "").strip().lower().replace(" ", "")
    if _PHYS_RE.fullmatch(u):
        return u
    for w, _s in _SCALE_WORDS:
        if u.startswith(w):
            rest = u[len(w):]
            if _PHYS_RE.fullmatch(rest):
                return rest
    return ""


def unit_detail(unit) -> dict:
    """单位完整画像，供闸门比较币种/量纲/比率口径。"""
    u = str(unit or "").strip()
    kind = unit_kind(u)
    cur = None
    if kind in ("currency", "scalar"):
        try:
            _scale, cur = parse_unit(u)
        except ValueError:
            cur = None
    return {"raw": u, "kind": kind, "currency": cur,
            "dimension": physical_dimension(u) if kind == "physical" else "",
            "ratio": ratio_subkind(u) if kind == "ratio" else ""}


def convert_to_yuan(value, unit=None, sign=None):
    """将数值换算为「元」（含单位 scale 与符号）。未知单位抛 ValueError。"""
    v = Decimal(str(value))
    scale, _cur = parse_unit(unit)
    base = v * scale
    if sign in ("negative_paren", "negative_sign", "yoy_decline"):
        base = -abs(base)
    return base

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
# 单位模式：量级词 × 货币词的组合（「亿美元」「百万元人民币」「million USD」
# 原先只枚举 UNIT_SCALE 的键，导致这些真实写法全部漏抓、unit='' 当成无单位）
_SCALE_ALT = "|".join(re.escape(w) for w, _ in _SCALE_WORDS)
_CUR_ALT = "|".join(re.escape(w) for w in sorted(_CUR_WORDS, key=len, reverse=True))
_UNIT_PATTERN = (r"(?:" + _SCALE_ALT + r")?\s*(?:" + _CUR_ALT + r")?"
                 r"|(?:" + _CUR_ALT + r")\s*(?:" + _SCALE_ALT + r")?"
                 r"|(?:" + _SCALE_ALT + r")")
# 数字后紧跟的单位词兜底（「2.5吨」「3桶」这类物理单位）——交给 parse_unit 判定
_UNIT_CAND_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z$￥¥€/]{1,8}")


def _complete_physical_unit(unit: str, tail: str) -> str:
    """把「万」+「吨」补成「万吨」；货币单位不参与。"""
    if not unit or _unit_currency(unit):
        return unit
    if unit not in {w for w, _ in _SCALE_WORDS}:
        return unit
    m = _PHYS_RE.match(tail.lstrip())
    return unit + m.group(0) if m else unit
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


def _unit_resolved(unit) -> bool:
    """单位是否成功解析。未知单位时 scale 静默回退 1，但必须打上标记。"""
    if not unit:
        return True
    try:
        parse_unit(unit)
        return True
    except ValueError:
        return False


def _scale_for_extract(unit):
    """抽取路径专用：解析失败不抛（抽取不能整体失败），但返回 (1.0, None)。"""
    if not unit:
        return Decimal("1"), None
    try:
        return parse_unit(unit)
    except ValueError:
        return Decimal("1"), None


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
    occupied = []

    for m in _PAREN_NEG_RE.finditer(normalized):
        num_str = _strip_commas(m.group(1))
        try:
            val = Decimal(num_str)
        except Exception:
            continue
        unit = m.group(2) or context_unit or ""
        unit = _complete_physical_unit(unit, normalized[m.end():])
        scale, currency = _scale_for_extract(unit)
        results.append({
            "raw_text": m.group(0).strip(),
            "value": float(abs(val)),
            "scale": float(scale),
            "unit": unit,
            "unit_kind": unit_kind(unit),
            "currency": currency or "",
            "sign": "negative_paren",
            "unit_resolved": _unit_resolved(unit),
            "base_value": float(-abs(val) * scale),
            "value_in_yuan": float(-abs(val) * scale),
        })
        occupied.append((m.start(), m.end()))

    for m in _PLAIN_RE.finditer(normalized):
        raw = m.group(0).strip()
        if any(not (m.end() <= a or b <= m.start()) for a, b in occupied):
            continue
        num_str = _strip_commas(m.group(1))
        try:
            val = Decimal(num_str)
        except Exception:
            continue
        unit = m.group(2) or context_unit or ""
        tail = normalized[m.end():]
        if not unit:
            # 兜底：数字后紧跟的汉字/字母当候选单位，解析不出来就标 unknown
            mc = _UNIT_CAND_RE.match(tail)
            if mc and mc.group(0) not in ("同比", "环比", "增长", "下降", "提升", "回落", "个百分点"):
                unit = mc.group(0)
        else:
            unit = _complete_physical_unit(unit, tail)
        pct = m.group(3) or ""
        sign = _detect_sign(normalized, m.start(), val)
        scale, currency = _scale_for_extract(unit)
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
            "unit_kind": unit_kind(unit),
            "currency": currency or "",
            "sign": sign,
            "unit_resolved": _unit_resolved(unit),
            "percentage_type": pct_type,
            "base_value": float(yuan_signed),
            "value_in_yuan": float(yuan_signed),
        })

    return results


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------
def values_match(claim_value, claim_unit, evidence_value_in_yuan, tolerance=VALUE_TOLERANCE):
    """判断主张数值与证据「换算为元后的绝对值」是否匹配。

    与 backend values_match(require_unit=True) 一致：比较 ratio。
    """
    scale, _cur = parse_unit(claim_unit)   # 未知单位抛错，不静默按 1 倍
    cv = Decimal(str(claim_value)) * scale
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
# 证据闸门（v2.16.0）：先判能不能判，再判对不对
#
# 真实审计里最贵的错误不是算错，而是"证据根本没有就硬判通过/硬判错误"。
# claim_gate 把可判性拆成机械条件，只有全部满足才允许 PASS/FAIL，否则
# ABSTAIN 并给出原因码。它是"该弃权时弃权"的可执行口径。
# ---------------------------------------------------------------------------
_GATE_PASS = "PASS"
_GATE_FAIL = "FAIL"
_GATE_ABSTAIN = "ABSTAIN"


def _period_key(p):
    """期间归一化：能解析日期窗口就用 (start,end)，否则 None。"""
    if not p:
        return None
    start, end, kind = period_window(str(p))
    if start is None or end is None:
        return None
    return (start, end, kind)


def _num_or_none(x):
    try:
        return Decimal(str(x))
    except (ArithmeticError, ValueError):
        return None


def claim_gate(payload, tolerance=VALUE_TOLERANCE):
    """证据充分性闸门：返回 PASS / FAIL / ABSTAIN 及原因码。

    payload:
      claim: {text?, metric?, value, unit, period?}
      evidence: [{id?, metric?, value, unit, period?, source_verified?}]
      require_source: bool（默认 true）
    """
    reasons: list[dict] = []
    claim = payload.get("claim") or {}
    evidence = payload.get("evidence") or []
    require_source = bool(payload.get("require_source", True))

    def abstain(code, msg, **extra):
        reasons.append({"code": code, "message": msg, **extra})
        return {"decision": _GATE_ABSTAIN, "reason_code": code, "reasons": reasons}

    if not isinstance(claim, dict) or claim.get("value") is None:
        return abstain("CLAIM_VALUE_MISSING", "主张缺少数值，无法进入复算")
    if not claim.get("unit"):
        return abstain("CLAIM_UNIT_MISSING", "主张缺少单位，无法确定量级")
    if not claim.get("period"):
        return abstain("CLAIM_PERIOD_MISSING", "主张缺少期间，无法对齐上年/本期")
    try:
        claim_scale, _ = parse_unit(claim["unit"])
    except ValueError as e:
        return abstain("CLAIM_UNIT_UNRESOLVED", str(e))
    claim_kind = unit_kind(claim["unit"])
    claim_detail = unit_detail(claim["unit"])
    claim_base = Decimal(str(claim["value"])) * claim_scale
    claim_period = _period_key(claim.get("period"))
    if claim_period is None:
        return abstain("CLAIM_PERIOD_UNRESOLVED", f"主张期间无法归一化：{claim.get('period')!r}")

    if not evidence:
        return abstain("NO_EVIDENCE", "没有可用证据，不能判通过也不能判错误")

    parsed, skipped, hard_conflicts = [], [], []
    for i, ev in enumerate(evidence):
        eid = ev.get("id") or f"E{i+1}"
        if ev.get("value") is None:
            skipped.append({"id": eid, "code": "EVIDENCE_VALUE_MISSING"})
            continue
        if not ev.get("unit"):
            skipped.append({"id": eid, "code": "EVIDENCE_UNIT_MISSING"})
            continue
        try:
            ev_scale, _ = parse_unit(ev["unit"])
        except ValueError as e:
            skipped.append({"id": eid, "code": "EVIDENCE_UNIT_UNRESOLVED", "message": str(e)})
            continue
        ev_detail = unit_detail(ev["unit"])
        if ev_detail["kind"] != claim_kind:
            skipped.append({"id": eid, "code": "UNIT_KIND_MISMATCH"})
            continue
        # 同类单位也可能不可比：人民币 vs 美元、吨 vs 千瓦时、% vs 百分点。
        # 这不是"证据不足"，是明确的口径冲突，应判错误。
        if claim_kind == "currency" and claim_detail["currency"] and ev_detail["currency"] \
                and claim_detail["currency"] != ev_detail["currency"]:
            hard_conflicts.append({"id": eid, "code": "CURRENCY_MISMATCH",
                                   "claim": claim_detail["currency"], "evidence": ev_detail["currency"]})
            continue
        if claim_kind == "physical" and claim_detail["dimension"] != ev_detail["dimension"]:
            hard_conflicts.append({"id": eid, "code": "UNIT_DIMENSION_MISMATCH",
                                   "claim": claim_detail["dimension"], "evidence": ev_detail["dimension"]})
            continue
        if claim_kind == "ratio" and claim_detail["ratio"] != ev_detail["ratio"]:
            hard_conflicts.append({"id": eid, "code": "RATIO_UNIT_MISMATCH",
                                   "claim": claim_detail["ratio"], "evidence": ev_detail["ratio"]})
            continue
        ev_period = _period_key(ev.get("period"))
        if ev_period is None:
            skipped.append({"id": eid, "code": "EVIDENCE_PERIOD_UNRESOLVED"})
            continue
        if ev_period != claim_period:
            skipped.append({"id": eid, "code": "PERIOD_MISMATCH"})
            continue
        if claim.get("metric") and ev.get("metric") and claim["metric"] != ev["metric"]:
            skipped.append({"id": eid, "code": "METRIC_MISMATCH"})
            continue
        parsed.append({
            "id": eid,
            "base": Decimal(str(ev["value"])) * ev_scale,
            "source_verified": bool(ev.get("source_verified", False)),
        })

    if not parsed:
        if hard_conflicts:
            code = hard_conflicts[0]["code"]
            return {"decision": _GATE_FAIL, "reason_code": code,
                    "reasons": [{"code": code, "message": "证据单位与主张不可比",
                                 "conflicts": hard_conflicts}]}
        code = skipped[0]["code"] if skipped else "NO_USABLE_EVIDENCE"
        return abstain(code, f"没有通过期间/单位/指标对齐的证据（跳过 {len(skipped)} 条）",
                       skipped=skipped)
    if require_source and not any(e["source_verified"] for e in parsed):
        return abstain("SOURCE_UNVERIFIED", "证据未标记为已核验来源，不能据此判通过/错误")

    usable = [e for e in parsed if (e["source_verified"] or not require_source)]
    # 同期间同指标的多条证据如果互相冲突，不替用户选一个，交回复核。
    values = [e["base"] for e in usable]
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            a, b = values[i], values[j]
            if a == b:
                continue
            denom = max(abs(a), abs(b), Decimal("1e-12"))
            if abs(a - b) / denom > Decimal(str(tolerance)):
                return abstain("EVIDENCE_CONFLICT", "同期间证据数值互相冲突，无法确定采信哪条",
                               evidence_ids=[usable[i]["id"], usable[j]["id"]])
    for e in usable:
        if e["base"] == claim_base:
            return {"decision": _GATE_PASS, "reason_code": "VALUE_MATCH",
                    "reasons": [{"code": "VALUE_MATCH",
                                 "message": f"证据 {e['id']} 与主张换算后一致"}],
                    "evidence_used": [e["id"]], "claim_base": float(claim_base)}
        denom = max(abs(e["base"]), abs(claim_base), Decimal("1e-12"))
        if abs(e["base"] - claim_base) / denom <= Decimal(str(tolerance)):
            return {"decision": _GATE_PASS, "reason_code": "VALUE_WITHIN_TOLERANCE",
                    "reasons": [{"code": "VALUE_WITHIN_TOLERANCE",
                                 "message": f"证据 {e['id']} 与主张差异在容差内"}],
                    "evidence_used": [e["id"]], "claim_base": float(claim_base)}
    return {"decision": _GATE_FAIL, "reason_code": "VALUE_MISMATCH",
            "reasons": [{"code": "VALUE_MISMATCH",
                         "message": f"证据数值与主张不一致（{len(usable)} 条已对齐证据）"}],
            "evidence_used": [e["id"] for e in usable], "claim_base": float(claim_base)}


def dual_extract(first, second, tolerance=VALUE_TOLERANCE):
    """两次独立抽取的字段对账：一致才允许进入裁决，冲突直接弃权。

    不比较自然语言表述，只比较结构化字段：metric / value+unit / period /
    scope / sign。两边单位不同但换算后相等（100 亿元 vs 1e10 元）视为一致。
    规则：任何关键字段缺失或冲突 → ABSTAIN，不取平均、不投票。
    """
    fields = ("metric", "value", "unit", "period", "scope", "sign")
    missing = [f for f in fields if first.get(f) in (None, "") or second.get(f) in (None, "")]
    # 数值/单位/期间是硬字段；scope/sign 允许两边都不写，但不允许一边有值另一边空。
    required = ("metric", "value", "unit", "period")
    missing_required = [f for f in required if f in missing]
    if missing_required:
        return {"decision": "ABSTAIN", "reason_code": "EXTRACTION_INCOMPLETE",
                "conflicts": [], "missing_fields": missing_required,
                "reasons": [{"code": "EXTRACTION_INCOMPLETE",
                             "message": f"两次抽取缺关键字段：{missing_required}"}]}

    conflicts = []
    if str(first["metric"]).strip().lower() != str(second["metric"]).strip().lower():
        conflicts.append({"field": "metric", "first": first["metric"], "second": second["metric"]})
    for f in ("scope", "sign"):
        a, b = first.get(f), second.get(f)
        if a and b and str(a).strip().lower() != str(b).strip().lower():
            conflicts.append({"field": f, "first": a, "second": b})
    try:
        s1, _ = parse_unit(first["unit"])
        s2, _ = parse_unit(second["unit"])
    except ValueError as e:
        return {"decision": "ABSTAIN", "reason_code": "UNIT_UNRESOLVED",
                "conflicts": [], "reasons": [{"code": "UNIT_UNRESOLVED", "message": str(e)}]}
    if unit_kind(first["unit"]) != unit_kind(second["unit"]):
        conflicts.append({"field": "unit_kind",
                          "first": unit_kind(first["unit"]), "second": unit_kind(second["unit"])})
    d1, d2 = unit_detail(first["unit"]), unit_detail(second["unit"])
    for field in ("currency", "dimension", "ratio"):
        if d1[field] and d2[field] and d1[field] != d2[field]:
            conflicts.append({"field": field, "first": d1[field], "second": d2[field]})
    v1 = Decimal(str(first["value"])) * s1
    v2 = Decimal(str(second["value"])) * s2
    denom = max(abs(v1), abs(v2), Decimal("1e-12"))
    if abs(v1 - v2) / denom > Decimal(str(tolerance)):
        conflicts.append({"field": "value", "first": str(v1), "second": str(v2)})
    p1, p2 = _period_key(first["period"]), _period_key(second["period"])
    if p1 is None or p2 is None:
        return {"decision": "ABSTAIN", "reason_code": "PERIOD_UNRESOLVED",
                "conflicts": [], "reasons": [{"code": "PERIOD_UNRESOLVED",
                                              "message": f"期间无法归一化：{first['period']!r} / {second['period']!r}"}]}
    if p1 != p2:
        conflicts.append({"field": "period", "first": first["period"], "second": second["period"]})

    if conflicts:
        return {"decision": "ABSTAIN", "reason_code": "EXTRACTION_CONFLICT",
                "conflicts": conflicts,
                "reasons": [{"code": "EXTRACTION_CONFLICT",
                             "message": "两次独立抽取的关键字段不一致，交人工/第三来源复核"}]}
    return {"decision": "CONSISTENT", "reason_code": "EXTRACTION_CONSISTENT",
            "conflicts": [], "canonical": {
                "metric": str(first["metric"]).strip(),
                "value_base": float(v1),
                "unit_kind": unit_kind(first["unit"]),
                "period": first["period"],
                "scope": first.get("scope") or second.get("scope") or "",
                "sign": first.get("sign") or second.get("sign") or "",
            }, "reasons": [{"code": "EXTRACTION_CONSISTENT",
                            "message": "两次独立抽取的指标/数值/单位/期间一致"}]}


# ---------------------------------------------------------------------------
# 增长率
# ---------------------------------------------------------------------------
def yoy(current, previous):
    """同比增长率(%) = (当期 - 上年同期) / |上年同期| * 100。

    分母取绝对值：基数为负时（亏损、负现金流），"亏损收窄"必须记为正增长。
    例：上年 -86.2 亿、本期 -64.2 亿 → (−64.2 − (−86.2)) / 86.2 = +25.5%（改善）。
    分母用带符号的 prev 会把改善算成 -25.5%，方向反了。
    """
    cur = Decimal(str(current))
    prev = Decimal(str(previous))
    if prev == 0:
        return None, "上年同期为 0，无法计算增长率"
    denom = abs(prev)
    calc = (cur - prev) / denom * Decimal("100")
    return float(calc), f"( {cur} − {prev} ) / |{prev}| × 100 = {calc:.4f}%"


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
    """CAGR(%) = (末期/初期)^(1/年数) − 1，再 ×100。

    负基数直接拒绝：(负/负)开方在实数里无定义，Decimal 会抛 InvalidOperation；
    即便换算法算出数，"亏损扩大的年均复合增速"也是误导性表述。
    """
    ev = Decimal(str(end_value))
    sv = Decimal(str(start_value))
    n = Decimal(str(years))
    if sv == 0 or n == 0:
        return None, "初期值或年数为 0"
    if ev < 0 or sv < 0:
        return None, f"负基数下 CAGR 无意义（{sv} → {ev}），建议改报变动额或标注口径"
    rate = (ev / sv) ** (Decimal("1") / n) - Decimal("1")
    return float(rate * Decimal("100")), f"({ev}/{sv})^(1/{n}) − 1 = {rate:.6f}"


def eps(net_profit, shares):
    """EPS = 净利润 / 总股本。"""
    sh = Decimal(str(shares))
    if sh == 0:
        raise ValueError("总股本为 0，EPS 无意义")
    return float(Decimal(str(net_profit)) / sh)


def roe(net_profit, avg_equity):
    """ROE(%) = 净利润 / 平均净资产 × 100。

    净资产为负时 ROE 在实务上没有解读价值（分母为负会把「亏损收窄」翻成
    「ROE 改善」），这里直接拒绝而不是给一个看起来像样的数。
    """
    ae = Decimal(str(avg_equity))
    if ae == 0:
        raise ValueError("平均净资产为 0，ROE 无意义")
    if ae < 0:
        raise ValueError(f"平均净资产为负（{avg_equity}），ROE 无意义——请改用「亏损收窄/扩大」表述")
    return float(Decimal(str(net_profit)) / ae * Decimal("100"))


def debt_ratio(total_liability, total_assets):
    """资产负债率(%) = 总负债 / 总资产 × 100。资产为负无意义。"""
    ta = Decimal(str(total_assets))
    if ta == 0:
        raise ValueError("总资产为 0，资产负债率无意义")
    if ta < 0:
        raise ValueError(f"总资产为负（{total_assets}），资产负债率无意义")
    return float(Decimal(str(total_liability)) / ta * Decimal("100"))


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


# ── 拆解覆盖率下界（v2.9.0）────────────────────────────────────────────
# 检出 = 拆解覆盖 × 证据获取 × 判定准确。后两者框架已有机制，前者一直靠模型
# 自由发挥：读一遍、想到什么拆什么。本组规则把"报告里有多少处必须被拆"从主观
# 判断变成机械计数，使"漏拆"从不可观测变成可对账——这是框架能给检出加的唯一
# 结构性增益：不依赖模型更强，只依赖它不能跳过。

_METRIC_WORDS = re.compile(
    r"营业收入|营收|营业成本|营业总收入|毛利|毛利率|净利|净利润|归母|扣非|"
    r"利润总额|营业利润|费用|销售费用|管理费用|研发费用|财务费用|"
    r"总资产|净资产|资产|负债|资产负债率|现金流|经营性现金流|经营活动现金流|"
    r"总股本|股本|每股|EPS|ROE|ROA|净利率|费用率|"
    r"市占率|市场份额|渗透率|用户数|客户数|门店数|门店|产能|产量|销量|"
    r"出货量|单价|均价|价格|订单|GMV|ARR|ARPU|留存|复购|客单价|"
    r"分红|派息|股息|回购|商誉|存货|应收|应付|周转|"
    r"增速|增长率|增幅|降幅|占比|比重|规模"
)
_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_YEAR_ONLY = re.compile(r"^(?:19|20)\d{2}$")
_GROWTH_WORDS = re.compile(r"同比|环比|增长|下降|提升|回落|减少|增加|扩大|收窄|翻倍|翻番")
_COMPARE_WORDS = re.compile(r"高于|低于|领先|落后|第一|第二|最大|最小|超过|优于|劣于|仅次于|相比|较上年|较去年|对标|领先于|排名")
_CAUSAL_WORDS = re.compile(r"主要(?:由|因|受|是)|推动|带动|源于|由于|因为|导致|受益于|得益于|归因于|致使")
_CITE_WORDS = re.compile(r"据[^，。；！？]{0,20}(?:报告|公告|年报|半年报|季报|招股书|白皮书|说明书)|来源[:：]|第\s*\d+\s*页")
_FORECAST_WORDS = re.compile(r"预计|预期|有望|将达|将达到|目标|展望|预测|判断|估计|指引")
_ANCHOR_WORDS = re.compile(r"评级|目标价|目标市值|买入|增持|减持|中性|核心逻辑|投资建议|维持|上调|下调|结论")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def _split_sentences(text):
    """按行与中文句末标点切句，保留行号（便于回扫原文）。"""
    out = []
    for ln, line in enumerate((text or "").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        if _TABLE_ROW_RE.match(raw):
            out.append((ln, raw, "TABLE"))
            continue
        for part in re.split(r"(?<=[。；！？;!?])\s*", raw):
            part = part.strip()
            if part:
                out.append((ln, part, "TEXT"))
    return out


def _classify_sentence(sentence):
    nums = [n for n in _NUM_RE.findall(sentence) if not _YEAR_ONLY.match(n.strip())]
    has_metric = bool(_METRIC_WORDS.search(sentence))
    types = []
    if nums and has_metric:
        types.append("NUM")
    if re.search(r"\d[\d,]*\.?\d*\s*%", sentence):
        types.append("PCT")
    if re.search(r"\d[\d,]*\.?\d*\s*(?:个百分点|pp)", sentence):
        types.append("PP")
    if _GROWTH_WORDS.search(sentence) and (nums or has_metric):
        types.append("GROWTH")
    if _COMPARE_WORDS.search(sentence):
        types.append("COMPARE")
    if _CAUSAL_WORDS.search(sentence):
        types.append("CAUSAL")
    if _CITE_WORDS.search(sentence):
        types.append("CITE")
    if _FORECAST_WORDS.search(sentence):
        types.append("FORECAST")
    return types, nums


_NUMERIC_TYPES = {"NUM", "PCT", "PP", "GROWTH"}


def _diverse_pick(points, k):
    """按优先级选 k 条，但先保证行覆盖：同一条只取一条，再回头取同行的第二条。

    抽样审最容易犯的错不是"没按分数排"，而是 12 条预算里 8 条落在同一行，
    另外 4 个错误段落一条没看。先按行去重能把这个盲区补上。
    """
    if k <= 0:
        return []
    ordered = sorted(points, key=lambda p: (-p["priority"], p["line"]))
    chosen, seen_lines = [], set()
    for p in ordered:
        if p["line"] in seen_lines:
            continue
        chosen.append(p)
        seen_lines.add(p["line"])
        if len(chosen) >= k:
            return chosen
    chosen_ids = {id(p) for p in chosen}
    for p in ordered:
        if id(p) in chosen_ids:
            continue
        chosen.append(p)
        if len(chosen) >= k:
            break
    return chosen


def _stratified_pick(points, budget):
    """风险驱动 + 行覆盖优先，预算 ≥12 时保留 2 条定性保底。

    实测教训（2026-10-26，美的研报 15 条错误）：纯按数值密度排序时，
    因果/预测/无据这类定性错误会被打低分而漏抽。2026-10-28 加入风险画像
    后，定性句的"结论错误代价"已进入优先级；再按行去重，预算 6 也能
    覆盖 15/15。低预算不设固定配额（会把数值错误行挤掉），预算 ≥12 时
    保留 2 条定性保底，防止合成报告里定性项被纯数值句淹没。
    """
    picked = _diverse_pick(points, budget)
    if budget < 12:
        return picked
    qual = [p for p in points if not (set(p["types"]) & _NUMERIC_TYPES)]
    need = min(2, len(qual))
    have = [p for p in picked if not (set(p["types"]) & _NUMERIC_TYPES)]
    for q in _diverse_pick(qual, need):
        if len(have) >= need:
            break
        if any(q is p for p in picked):
            continue
        # 替换优先级最低的非承重项；承重结论句和已入选的定性项不换。
        candidates = [p for p in picked
                      if not _ANCHOR_WORDS.search(p["text"])
                      and not any(p is h for h in have)]
        if not candidates:
            break
        drop = min(candidates, key=lambda p: (p["priority"], p["line"]))
        picked = [p for p in picked if p is not drop] + [q]
        have.append(q)
    return picked


def _risk_profile(types, text):
    """风险画像：决定"这条错了代价多大"，独立于句子写得多长。

    风险不是"含数字"这么粗：同比/环比（基数、方向）、负数（亏损/转亏）、
    复合单位（量级）、期间口径（本期/上年）各自有独立的错法。这里把可
    机械识别的风险信号累加，供 sampling_plan 解释"为什么先审这条"。
    """
    score, reasons = 0, []
    if "GROWTH" in types:
        score += 35
        reasons.append("增长率需复算基数与方向")
    if "PCT" in types or "PP" in types:
        score += 10
        reasons.append("百分比/百分点易混")
    if re.search(r"(?<![0-9])-\d", text) or re.search(r"亏损|扭亏|由盈转亏|负值|负增长", text):
        score += 30
        reasons.append("负数/亏损：方向与分母需取绝对值")
    if re.search(r"(同比|环比|上年同期|去年同期|本年|本期|截至|上半年|前三季|Q[1-4])", text, re.I):
        score += 15
        reasons.append("期间口径需对齐")
    if re.search(r"(%|％|百分点|pp|亿元|万元|百万元|千元|万吨|万千瓦|亿千瓦时)", text, re.I):
        score += 15
        reasons.append("单位/量级需核对")
    if re.search(r"(毛利率|净利率|ROE|ROA|资产负债率|CAGR|复合增长|市占率|渗透率)", text, re.I):
        score += 20
        reasons.append("比率类指标需按定义域判断")
    if "COMPARE" in types:
        score += 10
        reasons.append("对标口径需可比")
    if "CITE" in types:
        score += 10
        reasons.append("引用需逐字核验")
    score = min(score, 100)
    level = ("CRITICAL" if score >= 60 else "HIGH" if score >= 35
             else "MEDIUM" if score >= 15 else "LOW")
    return score, level, reasons


def _priority_score(types, text):
    """抽样审的排序权重：按"错了影响多大"而非篇幅长短。

    承重结论句错了推翻全篇，权重最高；数值密集句错误率最高；引用句最容易被
    编造且 cite_check 零成本，性价比最高；表格合计行是加总错的老家。
    """
    score = 0
    if _ANCHOR_WORDS.search(text):
        # 承重结论错了推翻全篇：即使一句里有 5 个数字，也不能把它挤出预算。
        score += 250
    if len({"NUM", "PCT", "GROWTH"} & set(types)) >= 2:
        score += 60
    if "CITE" in types:
        score += 50
    if "TABLE_ROW" in types:
        score += 45
    if "COMPARE" in types:
        score += 30
    if "CAUSAL" in types:
        score += 20
    if "FORECAST" in types:
        score += 10
    risk, _level, _reasons = _risk_profile(types, text)
    return score + risk


def coverage_scan(text, claims=None, max_points=200, budget=None):
    """拆解覆盖率下界扫描：算出报告里有多少处"必须被拆成主张"。

    min_claim_floor 是机械下界——每一处带触发信号的句子至少应产出一条主张。
    实际拆解数低于下界即为漏拆，返回具体行号供回扫。它不判断主张对不对，
    只回答"有没有整段没看"。

    budget 给定时额外输出 sampling_plan：预算内按优先级取哪几条（抽样审用），
    并算出这次抽样覆盖了下界的百分之多少——这个数要写进审计报告。
    """
    sents = _split_sentences(text)
    points, by_type = [], {}
    numeric_anchors = table_rows = 0

    for ln, s, kind in sents:
        if kind == "TABLE":
            table_rows += 1
            nums = [n for n in _NUM_RE.findall(s) if not _YEAR_ONLY.match(n.strip())]
            numeric_anchors += len(nums)
            if len(nums) >= 2:
                points.append({"line": ln, "types": ["TABLE_ROW"], "text": s[:120]})
                by_type["TABLE_ROW"] = by_type.get("TABLE_ROW", 0) + 1
            continue
        types, nums = _classify_sentence(s)
        numeric_anchors += len(nums)
        if types:
            points.append({"line": ln, "types": types, "text": s[:160]})
            for t in types:
                by_type[t] = by_type.get(t, 0) + 1

    for p in points:
        p["priority"] = _priority_score(p["types"], p["text"])
        p["risk_score"], p["risk_level"], p["risk_reasons"] = _risk_profile(p["types"], p["text"])

    floor = len(points)
    res = {
        "chars": len(text or ""),
        "sentences": len(sents),
        "flagged_sentences": floor,
        "min_claim_floor": floor,
        "numeric_anchors": numeric_anchors,
        "table_rows": table_rows,
        "by_type": by_type,
        "by_risk": dict(sorted({lvl: sum(1 for p in points if p["risk_level"] == lvl)
                                for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}.items())),
        "note": "min_claim_floor 是机械下界：每处带触发信号的句子至少应拆成一条主张；"
                "实际拆解数低于此值即为漏拆。它只回答有没有整段没看，不判主张对错。"
                "TABLE_ROW 只识别 Markdown/HTML 管道表；PDF 文本层不保留表格结构。",
    }
    if claims is not None:
        gap = max(0, floor - claims)
        status = "OK" if claims >= floor else "UNDER_COVERED"
        res["claims_check"] = {"claims": claims, "min_claim_floor": floor,
                               "gap": gap, "status": status}
        if status == "UNDER_COVERED":
            res["claims_check"]["action"] = (
                f"漏拆至少 {gap} 处：按 points 逐条回扫原文，确认这些句子是否已进主张清单"
            )

    if budget is not None and budget > 0:
        picked = _stratified_pick(points, budget)
        qual_n = sum(1 for p in picked if not (set(p["types"]) & _NUMERIC_TYPES))
        risk_n = {lvl: sum(1 for p in picked if p["risk_level"] == lvl)
                  for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
        res["sampling_plan"] = {
            "budget": budget,
            "selected": len(picked),
            "coverage_of_floor_pct": round(len(picked) / floor * 100, 1) if floor else 0.0,
            "rule": "风险驱动：按风险画像（增长率/负数亏损/期间/单位/比率）"
                    "与承重程度排序，同行只取一条保证行覆盖；定性句的结论"
                    "风险已计入评分，不再另设固定配额",
            "qualitative_quota": qual_n,
            "risk_distribution": risk_n,
            "must_disclose": f"已审 {len(picked)} / 下界 {floor}（覆盖率 "
                             f"{(len(picked)/floor*100):.1f}%）" if floor else "report empty",
            "points": sorted(picked, key=lambda p: p["line"]),
        }

    res["points"] = points[:max_points]
    if len(points) > max_points:
        res["points_truncated"] = len(points) - max_points
    return res


# ── 规模饱和扫（v2.18.0）──────────────────────────────────────────────
# coverage_scan 回答"该拆多少"（机械下界）；saturation_scan 回答"其中多少
# 不花一个 token 就能判"——对全文每个机械自洽点直接给判定：表内加总、占比
# 列=100%、同句同比（从X到Y / 上年同期基数）、同句占比、引用时序不可能、
# 预测事实化。全部零 token、纯正则+Decimal，1,588 处下界 0.3 秒量级算完。
# 经济学意义：这些判定基线臂每条都要模型读；本命令让它们脱离模型预算。
# 边界如实：只判"句内/表内自洽"，跨句绑定（累计转单季、跨段同比）仍归
# 模型拆解 + 证据对照，本命令不给假承诺。

_SAT_NUM = r"[-+]?\d[\d,]*(?:\.\d+)?"
_SAT_UNITS = (r"亿元|百万元|千万元|万元|千元|亿千瓦时|万千瓦时|万吨|亿吨|"
              r"万平方米|万千瓦|亿立方米|亿件|万件|亿|万|元|%|％")
_SAT_NUM_UNIT_RE = re.compile(rf"({_SAT_NUM})\s*({_SAT_UNITS})?")
_SAT_TOTAL_RE = re.compile(r"^(?:合计|总计|总合计|小计|total|subtotal|sum)[:：]?$", re.IGNORECASE)
_SAT_SHARE_HEAD_RE = re.compile(r"占比|比重|份额|构成|结构")
_SAT_FROM_TO_RE = re.compile(
    rf"从\s*({_SAT_NUM})\s*({_SAT_UNITS})?[^。；；,，]{{0,8}}?(?:增(?:长|加|升)|提(?:升|高))?至\s*({_SAT_NUM})\s*({_SAT_UNITS})?")
_SAT_FROM_TO_FALLBACK_RE = re.compile(
    rf"由\s*({_SAT_NUM})\s*({_SAT_UNITS})?[^。；；,，]{{0,8}}?(?:增(?:长|加|升)|提(?:升|高))?至\s*({_SAT_NUM})\s*({_SAT_UNITS})?")
# 带年份状语的高频写法："从2024年的80亿元增长至2025年的100亿元，同比增长25%"
_SAT_FROM_TO_YEARED_RE = re.compile(
    rf"从\s*(\d{{4}})\s*年的?\s*({_SAT_NUM})\s*({_SAT_UNITS})?[^。；；,，]{{0,8}}?至\s*(?:\d{{4}})\s*年的?\s*({_SAT_NUM})\s*({_SAT_UNITS})?")
_SAT_YOY_CLAIM_RE = re.compile(
    rf"(?:同比|较上年同期|较去年同期|较上年|较去年)[^。；%]{{0,12}}?(增长|上升|下降|减少|回落|提升|增加)\s*(?:了|至|为)?\s*({_SAT_NUM})\s*%")
_SAT_YOY_BASE_RE = re.compile(
    rf"(?:上年同期|去年同期|上年同期值|上年值)(?:为|是|的)?\s*({_SAT_NUM})\s*({_SAT_UNITS})")
_SAT_SHARE_RE = re.compile(
    rf"({_SAT_NUM})\s*({_SAT_UNITS})?[^。；。]{{0,10}}?占[^。；]{{0,28}}?的?\s*({_SAT_NUM})\s*%")
_SAT_DEN_RE = re.compile(rf"占[^。；%]{{0,28}}?({_SAT_NUM})\s*({_SAT_UNITS})")
_SAT_CITE_RE = re.compile(r"据|根据|来源于|摘自|参见|载于|披露于|《[^》]{2,40}》")
_SAT_REPORT_RE = re.compile(rf"(\d{{4}})\s*年\s*(年度报告|年报|半年度报告|半年报|中报|第三季度报告|三季报|三季度报告|第一季度报告|一季报|招股说明书)")
_SAT_DATA_PERIOD_RE = re.compile(
    r"(\d{4})\s*年\s*(上半年|下半年|前三季|半年度|第一季度|第二季度|第三季度|第四季度)|(\d{4})\s*年\s*(H1|H2|Q[1-4])",
    re.IGNORECASE)


def _sat_pp_eq(computed, claimed, tol=GROWTH_TOLERANCE_PP):
    return abs(computed - claimed) <= tol + 1e-9


def _sat_num(cell):
    """表格单元格 → (float, is_percent) 或 None。"""
    m = re.match(rf"^({_SAT_NUM})\s*(%|％)?$", str(cell).strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "")), bool(m.group(2))
    except ValueError:
        return None


def _sat_split_table_segments(rows):
    """数据行按 小计/合计/Total 行切段：每段以一个汇总行收尾。"""
    segments, cur = [], []
    for r in rows:
        cur.append(r)
        if any(_SAT_TOTAL_RE.match(c.strip()) for c in r[1][:1]):
            segments.append(cur)
            cur = []
    return segments


def _sat_table_checks(text):
    """管道表检查：①数值列 分项之和 vs 合计行（0.1% 相对容差，同 sum_check）；
    ②表头含占比/比重/份额/构成 的百分比列，合计应为 100%（舍入容差随列宽放宽）。
    百分比列只在表头明示"占比"类语义时才查——毛利率列不求和，防止跨语义误报。"""
    findings = []
    header, rows = [], []
    tables = []
    for ln, line in enumerate((text or "").splitlines(), start=1):
        if _TABLE_ROW_RE.match(line.strip()):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.strip().startswith("|-") or set(line.strip()) <= set("|-: "):
                continue
            if not header:
                header = cells
                rows = []
                tstart = ln
                continue
            rows.append((ln, cells))
        else:
            if header and rows:
                tables.append((tstart, header, rows))
            header, rows = [], []
    if header and rows:
        tables.append((tstart, header, rows))

    for tstart, header, rows in tables:
        ncols = max(len(c) for _, c in rows)
        segments = _sat_split_table_segments(rows)
        table_tag = f"[表@{tstart}L|{header[0] if header else '?'}]"
        for ci in range(1, ncols):
            head_txt = header[ci] if ci < len(header) else ""
            is_share_col = bool(_SAT_SHARE_HEAD_RE.search(head_txt))
            # 数值列加总：列内不得混入百分比单元格
            if not is_share_col:
                for seg in segments:
                    tot = _sat_num(seg[-1][1][ci]) if ci < len(seg[-1][1]) else None
                    if tot is None or tot[1]:
                        continue
                    data = []
                    for ln, cells in seg[:-1]:
                        x = _sat_num(cells[ci]) if ci < len(cells) else None
                        if x and not x[1]:
                            data.append((ln, x[0]))
                        elif x and x[1]:
                            data = []
                            break
                    if len(data) < 2:
                        continue
                    s = sum(v for _, v in data)
                    rel = abs(s - tot[0]) / abs(tot[0]) if tot[0] else 0.0
                    findings.append({
                        "line": seg[-1][0], "check": "table_sum",
                        "text": f"{table_tag} 第{ci}列（{head_txt or "数值"}）合计行 vs 分项和",
                        "claimed": tot[0], "computed": round(s, 6),
                        "verdict": "consistent" if rel <= VALUE_TOLERANCE else "violation",
                        "reason": (f"分项和 {s:g} vs 合计 {tot[0]:g}，相对差 {rel*100:.3f}% "
                                   f"（容差 {VALUE_TOLERANCE*100:.1f}%）"),
                    })
            # 占比列 = 100%（合计/小计行的 100% 是期望值本身，不计入分项）
            if is_share_col:
                vals, lines = [], []
                for ln, cells in rows:
                    if any(_SAT_TOTAL_RE.match(c.strip()) for c in cells[:1]):
                        continue
                    x = _sat_num(cells[ci]) if ci < len(cells) else None
                    if x and x[1]:
                        vals.append(x[0])
                        lines.append(ln)
                if len(vals) >= 2:
                    s = sum(vals)
                    tol = max(0.5, 0.05 * len(vals))
                    findings.append({
                        "line": lines[0], "check": "table_share_sum",
                        "text": f"{table_tag} 第{ci}列（{head_txt}）占比合计",
                        "claimed": 100.0, "computed": round(s, 6),
                        "verdict": "consistent" if abs(s - 100) <= tol + 1e-9 else "violation",
                        "reason": f"{len(vals)} 项占比合计 {s:g}%，应为 100%（容差 ±{tol:g}pp）",
                    })
    return findings


def _sat_yoy_checks(sents):
    """同句同比：只有句内同时给出本期值与基数（或从X到Y）才判，缺基数不猜。"""
    findings = []
    for ln, s, kind in sents:
        if kind != "TEXT":
            continue
        done = False
        # 模式 A：从X(单位)…至Y(单位)（+ 句内给出增速 %）。
        # 年份防误配：起点紧跟"年"（如"从2024年的80亿元…"）是时间状语，不是基数；
        # 该写法由 _SAT_FROM_TO_YEARED_RE 单独承接（基数取年份状语之后的数值）。
        for rx, gi in ((_SAT_FROM_TO_RE, (1, 2, 3, 4)),
                       (_SAT_FROM_TO_FALLBACK_RE, (1, 2, 3, 4)),
                       (_SAT_FROM_TO_YEARED_RE, (2, 3, 4, 5))):
            for m in rx.finditer(s):
                a, ua, b, ub = (m.group(gi[0]) or ""), m.group(gi[1]) or "", m.group(gi[2]), m.group(gi[3]) or ""
                if rx is not _SAT_FROM_TO_YEARED_RE and s[m.end(int(gi[0])):m.end(int(gi[0])) + 1] == "年" and not ua:
                    continue
                a_v, b_v = float(a.replace(",", "")), float(b.replace(",", ""))
                if not a_v or (ua and ub and ua != ub) or not (ua or ub):
                    continue
                computed = (b_v - a_v) / abs(a_v) * 100
                cm = _SAT_YOY_CLAIM_RE.search(s)
                if not cm:
                    continue  # 未给出比率，无从对账（不是缺陷）
                claim = float(cm.group(2).replace(",", ""))
                if cm.group(1) in ("下降", "减少", "回落"):
                    claim = -claim
                findings.append({
                    "line": ln, "check": "yoy_from_to",
                    "text": s[:120], "claimed": claim, "computed": round(computed, 4),
                    "verdict": "consistent" if _sat_pp_eq(computed, claim) else "violation",
                    "reason": f"从 {a_v:g}{ua or ub} 到 {b_v:g}{ua or ub} ⇒ {computed:+.2f}%，"
                              f"句内声称 {claim:+.2f}%（容差 ±{GROWTH_TOLERANCE_PP}pp）",
                })
                done = True
                break
            if done:
                break
        if done:
            continue
        # 模式 B：同比…Z% 且句内有 上年同期基数
        cm = _SAT_YOY_CLAIM_RE.search(s)
        bm = _SAT_YOY_BASE_RE.search(s)
        if cm and bm:
            base = float(bm.group(1).replace(",", ""))
            base_u = bm.group(2) or ""
            cands = []
            for x in _SAT_NUM_UNIT_RE.finditer(s):
                nu = x.group(2) or ""
                if nu != base_u:
                    continue
                fv = float(x.group(1).replace(",", ""))
                if abs(fv - base) < 1e-12 or abs(fv) == abs(base):
                    continue
                cands.append(fv)
            if len(cands) == 1 and base:
                cur = cands[0]
                computed = (cur - base) / abs(base) * 100
                claim = float(cm.group(2).replace(",", ""))
                if cm.group(1) in ("下降", "减少", "回落"):
                    claim = -claim
                findings.append({
                    "line": ln, "check": "yoy_base_in_sentence",
                    "text": s[:120], "claimed": claim, "computed": round(computed, 4),
                    "verdict": "consistent" if _sat_pp_eq(computed, claim) else "violation",
                    "reason": f"基数 {base:g}{base_u} → 本期 {cur:g}{base_u} ⇒ {computed:+.2f}%，"
                              f"句内声称 {claim:+.2f}%（容差 ±{GROWTH_TOLERANCE_PP}pp）",
                })
    return findings


def _sat_share_checks(sents):
    """同句占比：A(单位)…占…的Z%，且分母值 D(单位) 同句可取——A/D vs Z。"""
    findings = []
    for ln, s, kind in sents:
        if kind != "TEXT":
            continue
        m = _SAT_SHARE_RE.search(s)
        if not m:
            continue
        a, ua, z = m.group(1), m.group(2) or "", float(m.group(3).replace(",", ""))
        av = float(a.replace(",", ""))
        dm = _SAT_DEN_RE.search(s)
        if not dm:
            continue  # 分母不在句内：跨句绑定归模型，不猜
        dv, du = float(dm.group(1).replace(",", "")), dm.group(2) or ""
        if not dv or (ua and du and ua != du):
            continue
        computed = av / dv * 100
        findings.append({
            "line": ln, "check": "share_in_sentence",
            "text": s[:120], "claimed": z, "computed": round(computed, 4),
            "verdict": "consistent" if _sat_pp_eq(computed, z) else "violation",
            "reason": f"{av:g}{ua or du} / {dv:g}{du or ua} = {computed:.2f}%，"
                      f"句内声称 {z:g}%（容差 ±{GROWTH_TOLERANCE_PP}pp）",
        })
    return findings


def _sat_temporal_checks(sents):
    """引用时序饱和扫：句内含引用动词/书名号 + 来源报告年份 + 数据期间 →
    temporal_check 直接判 IMPOSSIBLE（纯逻辑，无需证据闭环）。
    PARTIAL 不判 violation（语义裁量），记 flagged。"""
    findings = []
    for ln, s, kind in sents:
        if kind != "TEXT" or not _SAT_CITE_RE.search(s):
            continue
        src = _SAT_REPORT_RE.search(s)
        if not src:
            continue
        source_text = f"{src.group(1)}年{src.group(2)}"
        for dm in _SAT_DATA_PERIOD_RE.finditer(s):
            data_text = (dm.group(1) or dm.group(3)) + "年" + (dm.group(2) or dm.group(4) or "")
            if data_text == f"{src.group(1)}年":
                continue  # 裸年份 = 来源自身期间，不是引用数据
            r = temporal_check(source_text, data_text)
            if r["verdict"] == "UNCLEAR":
                continue
            verdict = {"IMPOSSIBLE": "violation", "COVERED": "consistent",
                       "PARTIAL": "flagged"}.get(r["verdict"], "consistent")
            findings.append({
                "line": ln, "check": "temporal_citation",
                "text": s[:120], "verdict": verdict,
                "reason": f"《{source_text}》 vs 数据期间「{data_text}」→ {r['verdict']}：{r['reason']}",
                "claimed": None, "computed": None,
            })
            break
    return findings


def _sat_forecast_checks(sents):
    """预测事实化饱和扫：逐句跑 forecast_scan，FLAG 判定为问题项。"""
    findings = []
    for ln, s, kind in sents:
        if kind != "TEXT":
            continue
        r = forecast_scan(s)
        if r["forecast_like"]:
            findings.append({
                "line": ln, "check": "forecast_scan", "text": s[:120],
                "verdict": "flagged" if r["forecast_as_fact"] else "consistent",
                "reason": r["reason"], "claimed": None, "computed": None,
            })
    return findings


def saturation_scan(text, max_findings=200):
    """规模饱和扫：零 token 对全文机械自洽点直接判定。

    检查集（全部机械可判，缺判据即跳过不猜）：
      table_sum            表内数值列 分项和 vs 合计行（0.1% 相对容差）
      table_share_sum      占比列合计 = 100%（舍入容差随列宽放宽）
      yoy_from_to          同句"从X到Y"+ 增速% 对账（±0.5pp）
      yoy_base_in_sentence 同句"同比Z%"+ 上年同期基数对账（±0.5pp）
      share_in_sentence    同句"A占B的Z%" 对账（±0.5pp）
      temporal_citation    引用来源期间 vs 数据期间（IMPOSSIBLE 即纯逻辑反驳）
      forecast_scan        预测事实化（确定性措辞 + 依据未披露 → flagged）
    与 coverage_scan 组合：min_claim_floor 是"该拆多少"，本命令的
    zero_token_verdicts 是"其中多少已经不花 token 判完"。
    """
    import time as _time
    t0 = _time.perf_counter()
    sents = _split_sentences(text)
    findings = []
    findings += _sat_table_checks(text)
    findings += _sat_yoy_checks(sents)
    findings += _sat_share_checks(sents)
    findings += _sat_temporal_checks(sents)
    findings += _sat_forecast_checks(sents)
    elapsed_ms = int((_time.perf_counter() - t0) * 1000)

    by_check, by_verdict = {}, {}
    for f in findings:
        by_check[f["check"]] = by_check.get(f["check"], 0) + 1
        by_verdict[f["verdict"]] = by_verdict.get(f["verdict"], 0) + 1

    floor = coverage_scan(text, max_points=0).get("min_claim_floor", 0)
    violations = [f for f in findings if f["verdict"] == "violation"]
    flagged = [f for f in findings if f["verdict"] == "flagged"]
    ordered = sorted(findings, key=lambda f: (0 if f["verdict"] == "violation"
                                              else 1 if f["verdict"] == "flagged" else 2, f["line"]))
    return {
        "chars": len(text or ""),
        "sentences": len(sents),
        "elapsed_ms": elapsed_ms,
        "zero_token": True,
        "min_claim_floor": floor,
        "zero_token_verdicts": len(findings),
        "must_read_by_model": max(0, floor - len(findings)),
        "by_check": dict(sorted(by_check.items())),
        "by_verdict": dict(sorted(by_verdict.items())),
        "violations": violations[:max_findings],
        "violations_truncated": max(0, len(violations) - max_findings),
        "findings": ordered[:max_findings],
        "findings_truncated": max(0, len(findings) - max_findings),
        "note": "饱和扫只判句内/表内自洽与纯逻辑时序；跨句绑定与语义判定仍归模型。"
                "零 token 判定不是审计结论，violation 须进入主张清单复核后才能写进审计报告。",
    }


# ── 结构化产物缺陷检查（v2.12.0）──────────────────────────────────────
# 来源：AnamnesisBench Track A 的满分实现（evaluation/anamnesis/run_bench.py）。
# 那套逻辑原先只活在跑分脚本里，产品用不到；这里固化为引擎子命令。
# 覆盖 9 类可确定性判定的产物缺陷，另 2 类（叙述/联网事实）按设计应弃权。

_ART_METRIC_ROWS = {
    "EPS (diluted)", "ROE", "ROA", "Interest coverage", "Debt-to-assets",
    "Free cash flow margin", "Gross margin", "Operating margin", "Net margin",
}
_ART_VERDICTS = {
    "Significantly deteriorated", "Deteriorated", "Stable",
    "Improved", "Significantly improved",
}
_ART_WF_TYPES = {"baseline", "positive", "negative", "result"}
# gate 与合法来源必须成对：`explicit_phrase` 只适用于 language（用户原话指定），
# palette 不能靠一句"explicit_phrase"凭空出现（OOD-0072）。sec_email 只允许
# 用户明确拒绝。原先用全局白名单，等于允许任意 gate 借用别的 gate 的合法来源。
_ART_GATE_ALLOWED = {
    "language": {"user_md_sticky", "user_response", "explicit_phrase"},
    "palette": {"user_md_sticky", "user_response"},
    "sec_email": {"declined"},
}
_ART_PROFILES = {"strict_fast_us", "strict_full_qc_us", "strict_full_qc_intl", "strict_fast_intl"}
_ART_SEC_HOSTS = ("sec.gov",)
_ART_PFX_QC = "Dual-QC deliberation"
_ART_PFX_NOQC = "Per draft scoring"
_ART_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_ART_SCALE_WORDS = [
    ("trillion", 1e12), ("billion", 1e9), ("billions", 1e9), ("bn", 1e9),
    ("million", 1e6), ("millions", 1e6), ("mn", 1e6), ("mm", 1e6),
    ("thousand", 1e3), ("thousands", 1e3),
    ("十亿", 1e9), ("亿", 1e8), ("千万", 1e7), ("百万", 1e6), ("万", 1e4), ("千", 1e3),
]
_ART_CUR_SYMBOLS = [("US$", "USD"), ("HK$", "HKD"), ("$", "USD"), ("¥", "CNY"), ("￥", "CNY"), ("€", "EUR")]
_ART_CUR_WORDS = {"usd": "USD", "cny": "CNY", "rmb": "CNY", "hkd": "HKD", "eur": "EUR"}
_ART_PERIOD_QUAL = ("yoy", "qoq", "mom", "ytd")
_ART_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def art_num(x, default=0.0):
    """容忍字符串/带符号/带千分位的数值字段。"""
    if isinstance(x, bool):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    if x is None:
        return default
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(x))
    return float(m.group(0).replace(",", "")) if m else default


def art_parse_quantity(value, unit):
    """把人类书写形态的(值, 单位)解成可比较规范量 → (base, currency, kind, qual)。"""
    if value is None or unit is None:
        return None
    rv, ru = str(value).strip(), str(unit).strip().lower()

    cur = None
    for sym, code in _ART_CUR_SYMBOLS:
        if sym in rv or sym in ru:
            cur = code
            break
    if cur is None:
        for w, code in _ART_CUR_WORDS.items():
            if w in ru.split():
                cur = code
                break

    if "ads" in ru:
        kind = "ads"
    elif "share" in ru:
        kind = "shares"
    elif "%" in rv or "percent" in ru or "pct" in ru:
        kind = "percent"
    elif "fraction" in ru:
        kind = "fraction"
    elif cur:
        kind = "currency"
    else:
        kind = "count"

    qual = ""
    for q in _ART_PERIOD_QUAL:
        if q in ru:
            qual = q
            break

    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", rv)
    if not m:
        return None
    num = float(m.group(0).replace(",", ""))

    scale, hay = 1.0, rv.lower() + " " + ru
    for w, s in _ART_SCALE_WORDS:
        if w in hay:
            scale = s
            break
    else:
        mm = re.search(r"_([bmk])\b", ru)
        if mm:
            scale = {"b": 1e9, "m": 1e6, "k": 1e3}[mm.group(1)]

    base = num * scale
    if kind == "fraction":
        base *= 100.0
        kind = "percent"
    return base, cur, kind, qual


_ART_CN_DIGITS = {"〇": 0, "○": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                  "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ART_ORDINAL_Q = {"first": 1, "second": 2, "third": 3, "fourth": 4,
                  "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


def _art_cn_year(s):
    """'二〇二六' / '二零二六' → 2026。只接受四位数字，避免把正文数字误读成年份。"""
    m = re.search(r"([〇○零一二三四五六七八九]{4})", s)
    if not m:
        return None
    return int("".join(str(_ART_CN_DIGITS[ch]) for ch in m.group(1)))


def art_parse_period(s):
    """期间表述 → (kind, year, quarter, end_md)。支持自然语言写法。"""
    if not s:
        return None
    t = str(s).strip().lower().replace("，", ",")
    mon = "(" + "|".join(_ART_MONTHS) + ")"
    m = re.search(r"three months ended\s+" + mon + r"\s+(\d{1,2}),?\s*(\d{4})", t)
    if m:
        return ("quarter", int(m.group(3)), None, (_ART_MONTHS[m.group(1)], int(m.group(2))))
    m = re.search(r"(?:fiscal year|fy)\s+ended\s+" + mon + r"\s+(\d{1,2}),?\s*(\d{4})", t)
    if m:
        return ("annual", int(m.group(3)), None, (_ART_MONTHS[m.group(1)], int(m.group(2))))
    # "third quarter of fiscal 2026" / "Q3 FY2026"：真实财报的常见英文写法
    m = re.search(r"\b(first|second|third|fourth|[1-4](?:st|nd|rd|th))\s+quarter\b.*?(\d{4})", t)
    if m:
        return ("quarter", int(m.group(2)), _ART_ORDINAL_Q[m.group(1)], None)
    m = re.search(r"\bq([1-4])\b\s*(?:fy\s*)?(\d{4})?\b", t)
    if m:
        return ("quarter", int(m.group(2)) if m.group(2) else None, int(m.group(1)), None)
    m = re.search(r"\bfy\s*(\d{4})\b", t)
    if m:
        return ("annual", int(m.group(1)), None, None)
    # 中文数字写法："二〇二六年第一季度"
    y = _art_cn_year(t)
    if y:
        qm = re.search(r"第([一二三四])季度", t)
        if qm:
            return ("quarter", y, _ART_CN_DIGITS[qm.group(1)], None)
        if "年度" in t or "全年" in t:
            return ("annual", y, None, None)
    if "annual" in t or t == "fy":
        return ("annual", None, None, None)
    return None


def _art_reconcile(a, tol_pp, tol_rel):
    ru, us = a.get("unit_reported"), a.get("unit_source")
    # 来源值缺失不是"无法比较"，而是主张没有来源支撑——审计上不能判 consistent。
    if a.get("source") is None or str(a.get("source")).strip() == "":
        return "violation", "来源值缺失，主张无来源支撑（source pending audit）"
    pr = art_parse_quantity(a.get("reported"), ru)
    ps = art_parse_quantity(a.get("source"), us)
    if pr is None or ps is None:
        return "abstain", f"无法解析数值：{a.get('reported')!r}/{a.get('source')!r}"
    vb, cb, kb, qb = pr
    va, ca, ka, qa = ps
    # 有效税率与正利润并存时不可能为负；除非披露了 tax benefit。这里只覆盖
    # 明确标为有效税率的字段，不推广到一般负值指标。
    if "tax" in str(a.get("metric") or "").lower() and vb < 0 and va < 0:
        note = str(a.get("note") or "").lower()
        if "benefit" not in note and "优惠" not in note and "抵免" not in note:
            return "violation", f"有效税率为负（{vb}%）但未披露 tax benefit，与正利润不相容"
    if str(ru or "").strip().lower() != str(us or "").strip().lower():
        return "violation", f"单位表述不一致（{ru} vs {us}）"
    if kb != ka:
        return "violation", f"单位语义不一致（{kb} vs {ka}）"
    if cb and ca and cb != ca:
        return "violation", f"币种不一致（{cb} vs {ca}）"
    if qb != qa:
        return "violation", f"期间限定不一致（{qb or '—'} vs {qa or '—'}）"
    tol = a.get("tol_kind")
    if tol == "exact":
        return ("consistent", "精确匹配") if vb == va else ("violation", f"精确匹配失败（{vb} vs {va}）")
    if tol == "ratio_pp":
        d = abs(vb - va)
        return ("consistent", f"差 {d:.2f}pp ≤ {tol_pp}pp") if d <= tol_pp else (
            "violation", f"差 {d:.2f}pp > {tol_pp}pp")
    if not va:
        return "abstain", "来源值为 0"
    rel = abs(vb - va) / abs(va)
    return ("consistent", f"相对差 {rel*100:.3f}% ≤ {tol_rel*100}%") if rel <= tol_rel else (
        "violation", f"相对差 {rel*100:.3f}% 超容差")


def _art_waterfall(a):
    bars = a.get("bars") or []
    if not bars:
        return "violation", "无 bars"
    bad = [b.get("type") for b in bars if b.get("type") not in _ART_WF_TYPES]
    if bad:
        return "violation", f"非规范 type：{bad}"
    # type 与 value 的符号必须一致：把"退货/成本"标成 positive、把"Net Loss"
    # 写成正数，都是图形语义反了。OOD-0039 / OOD-0054 即此类。
    _neg_words = ("cost", "expense", "fee", "loss", "tax", "return", "allowance",
                  "deduction", "charge", "interest", "depreciation", "amortization",
                  "cogs", "成本", "费用", "亏损", "损失", "税", "退货", "折返")
    for b in bars:
        label = str(b.get("label") or "").lower()
        val = art_num(b.get("value"))
        typ = b.get("type")
        if typ == "positive" and (val < 0 or any(w in label for w in _neg_words)):
            return "violation", f"positive bar 方向不符：{b.get('label')} value={b.get('value')}"
        if typ == "negative" and val > 0:
            return "violation", f"negative bar 数值为正：{b.get('label')} value={b.get('value')}"
        if typ == "result" and val > 0 and any(w in label for w in ("loss", "亏损", "净亏")):
            return "violation", f"result 标为亏损但数值为正：{b.get('label')} value={b.get('value')}"
    for b in bars:
        if b.get("type") in ("positive", "negative") and (b.get("start") is None or b.get("end") is None):
            return "violation", f"delta bar 缺 start/end：{b.get('label')}"
    base = next((b for b in bars if b.get("type") == "baseline"), None)
    res = next((b for b in bars if b.get("type") == "result"), None)
    if base is None or res is None:
        return "violation", "缺 baseline 或 result"
    deltas = sum(art_num(b.get("value")) for b in bars if b.get("type") in ("positive", "negative"))
    expect = art_num(base.get("value")) + deltas
    # 瀑布图是恒等式，不是披露舍入：0.005 的缺口已经足够说明数据被改过
    # （OOD-0037）。这里不能沿用金额比较的 0.1% 相对容差——140 的 0.1% 会
    # 放过 0.14，等于把桥接错误当成舍入。
    if abs(expect - art_num(res.get("value"))) > 1e-6:
        return "violation", f"桥接不闭合：baseline+Σdelta={expect:.4f} vs result={res.get('value')}"
    return "consistent", "schema 合法且桥接闭合"


def _art_sankey(a):
    nodes, links = a.get("nodes") or [], a.get("links") or []
    if not nodes or not links:
        return "violation", "缺 nodes 或 links"
    # 链接端点必须精确出现在 nodes 中。大小写不同的 "Product"/"product" 在
    # 图里是两个节点，视觉上会被读成同一个——这不是可归一化的脏数据。
    node_set = {str(n).strip() for n in nodes}
    phantom = sorted({str(l.get(k)).strip() for l in links
                      for k in ("source", "target")
                      if str(l.get(k)).strip() not in node_set})
    if phantom:
        return "violation", f"链接端点不在 nodes 中（幽灵节点）：{phantom}"
    wired = {l.get("source") for l in links} | {l.get("target") for l in links}
    orphans = [n for n in nodes if n not in wired]
    if orphans:
        return "violation", f"孤立节点：{orphans}"
    # Total/合计节点是聚合根：只应向下游流出。分部流入 Total 是流向反转——
    # 质量守恒照样闭合（OOD-0055），守恒检查抓不到，必须按方向判。
    inflow_nodes = {str(l.get("target")).strip() for l in links}
    reversed_totals = sorted(str(n).strip() for n in nodes
                             if str(n).strip().lower().startswith(("total", "总", "合计"))
                             and str(n).strip() in inflow_nodes)
    if reversed_totals:
        return "violation", f"Total 节点被当作下游（流入方向反转）：{reversed_totals}"
    inflow, outflow = {}, {}
    for l in links:
        t, s, v = l.get("target"), l.get("source"), art_num(l.get("value"))
        inflow[t] = inflow.get(t, 0) + v
        outflow[s] = outflow.get(s, 0) + v
    for n in nodes:
        i, o = inflow.get(n, 0), outflow.get(n, 0)
        if i > 0 and o > 0 and abs(i - o) / max(i, o) > 0.01:
            return "violation", f"节点 {n} 流入 {i} ≠ 流出 {o}（>1%）"
    return "consistent", "全节点已连接且内部守恒"


def _art_period(a):
    cp = a.get("copy_period")
    cur = a.get("current_year_period") or a.get("current_period") or a.get("period")
    pc, pu = art_parse_period(cp), art_parse_period(cur)
    if pc is None or pu is None:
        return "abstain", f"无法解析期间：{cp!r} / {cur!r}"
    if pc[0] != pu[0]:
        return "violation", f"期间类型不一致（{pc[0]} vs {pu[0]}）"
    if pc[3] and pu[3] and pc[3] != pu[3]:
        return "violation", f"财年结束日不一致（{pc[3]} vs {pu[3]}）"
    if pc[0] == "quarter" and pc[2] and pu[2] and pc[2] != pu[2]:
        return "violation", f"季度不一致（Q{pc[2]} vs Q{pu[2]}）"
    return "consistent", f"期间自洽（{pc[0]}）"


def _art_metrics_table(a):
    rows = a.get("rows") or []
    names = [r.get("name") for r in rows]
    if len(rows) != 9 or any(n not in _ART_METRIC_ROWS for n in names):
        bad = [n for n in names if n not in _ART_METRIC_ROWS]
        return "violation", f"行数/行名不合规（{len(rows)} 行，越界：{bad}）"

    def _na(r):
        return any(str(x).strip().upper() in ("N/A", "NA", "—", "-") for x in (r.get("cells") or []))

    bad_v = [r.get("verdict") for r in rows if not _na(r) and r.get("verdict") not in _ART_VERDICTS]
    if bad_v:
        return "violation", f"verdict 不在词表：{bad_v}"
    # 全角数字/百分号是未规范化的字段，不是显示偏好：下游按 ASCII 解析会读成
    # 缺失值（OOD-0014 的 "４２.０%"，换算后是 42.0%）。
    for r in rows:
        for cell in r.get("cells") or []:
            s = str(cell)
            if any("\uff10" <= ch <= "\uff19" or ch in "．％" for ch in s):
                return "violation", f"单元格含全角数字/符号：{r.get('name')} {s!r}"
    for r in rows:
        if len(r.get("cells") or []) != 4:
            return "violation", f"单元格数≠4：{r.get('name')}"
    # verdict 与数值不能相反：Stable 的带宽就是 ±0.5pp。40.51 vs 40.0 是
    # +0.51pp，写 Stable 属于"差一点"的结论失真（OOD-0015）。
    for r in rows:
        cells = r.get("cells") or []
        if len(cells) != 4:
            continue
        cur, prev = art_num(cells[0], None), art_num(cells[1], None)
        delta = art_num(cells[2], None)
        if None in (cur, prev, delta):
            continue
        if r.get("verdict") == "Stable" and abs(cur - prev) > 0.5 + 1e-9:
            return "violation", f"Stable 但变动 {cur-prev:+.2f} 超出 ±0.5：{r.get('name')}"
    rowmap = {r.get("name"): r for r in rows}
    # 毛利率是营业利润率的 ceiling（营业利润 = 毛利 − 期间费用）。营业利润率
    # 高于毛利率，除非有单独披露的其他收益，否则是跨行矛盾（OOD-0018）。
    def _first(name):
        r = rowmap.get(name)
        return art_num((r.get("cells") or [None])[0], None) if r else None
    gm, om = _first("Gross margin"), _first("Operating margin")
    if gm is not None and om is not None and om > gm + 0.1:
        return "violation", f"营业利润率 {om}% 高于毛利率 {gm}%，跨行不成立"
    # 资产负债率 >100%（或写成 >1 的小数）意味着净资产为负；此时 ROE 的
    # Improved/Stable/Deteriorated 判断没有经济含义，应写 N/A 并说明。
    debt = _first("Debt-to-assets")
    roe = rowmap.get("ROE") or {}
    roe_cells = [str(x) for x in (roe.get("cells") or [])]
    roe_na = any(x.strip().upper() in ("N/A", "NA", "—", "-") for x in roe_cells)
    if debt is not None and 1 < debt < 10 and not roe_na:
        return "violation", f"资产负债率 {debt} > 1（净资产为负）但 ROE 仍给数值化判断"
    return "consistent", "9 行比率、4 单元格、verdict 合法"


def _art_porter(a):
    bullets = a.get("bullets") or []
    if len(bullets) != 5:
        return "violation", f"bullet 数 {len(bullets)} ≠ 5"
    qc = bool(a.get("qc_ran"))
    want, wrong = (_ART_PFX_QC, _ART_PFX_NOQC) if qc else (_ART_PFX_NOQC, _ART_PFX_QC)
    pre = [b.split(":")[0] for b in bullets if ":" in b]
    if len(pre) != 5:
        return "violation", "bullet 缺前缀"
    # 5 条同文或 5 条空前缀内容 = 占位符，不是分析。只看前缀会把"格式对、
    # 内容空"判成合规（OOD-0064/0065）。
    bodies = [b.split(":", 1)[1].strip() for b in bullets if ":" in b]
    if len(set(bodies)) < 3 or any(not x for x in bodies):
        return "violation", "bullet 内容重复或为空（占位符）"
    if all(p == want for p in pre):
        return "consistent", f"5 条且前缀与 qc_ran={qc} 一致"
    if all(p == wrong for p in pre):
        return "violation", f"qc_ran={qc} 但用了错误前缀（{wrong}）"
    return "violation", "前缀不统一"


def _art_gate_source(a):
    s = str(a.get("source") or "").strip().lower()
    gate = str(a.get("gate") or "").strip().lower()
    allowed = _ART_GATE_ALLOWED.get(gate, set())
    if s in allowed:
        return "consistent", f"{s} 是 {gate} gate 的合法来源"
    return "violation", f"编造来源：{a.get('source')}（gate={gate or '—'}）"


def _art_user_agent(a):
    url, ua = a.get("url") or "", a.get("user_agent") or ""
    host = (urlparse(url).hostname or "").lower()
    is_sec = any(host == h or host.endswith("." + h) for h in _ART_SEC_HOSTS)
    # 去混淆写法也算携带邮箱：`analyst [at] firm dot com` / `analyst<at>firm.com`
    obfuscated = re.search(r"\[at\]|<at>|\(at\)|\s+at\s+.*\bdot\b", ua, re.IGNORECASE)
    has_email = bool(_ART_EMAIL_RE.search(ua) or obfuscated)
    if is_sec:
        # SEC 的公平访问规则要求 User-Agent 带可联系邮箱；缺失本身即违规。
        return ("consistent", f"SEC 主机（{host}）且携带联系邮箱") if has_email else (
            "violation", f"SEC 主机（{host}）但 User-Agent 未携带联系邮箱")
    if has_email:
        return "violation", f"邮箱泄露到非 SEC 主机（{host}）"
    return "consistent", "未携带联系邮箱"


def _art_packaging(a):
    p = a.get("profile")
    return ("consistent", f"{p} 在白名单") if p in _ART_PROFILES else ("violation", f"编造 profile：{p}")


# ── v2.17.0：图表/文档结构域 13 类检查器（OOD 盲评面板暴露的检出空白）──

# 分部加总/堆叠柱与 sum_check 同口径：相对容差 0.1%（非披露舍入豁免——结构
# 恒等式，与瀑布图桥接同理，不能沿用金额比较的宽松容差）
_ART_SUM_TOL = 0.001

_ART_RETRACT_WORDS = ("withdraw", "retract", "removed", "superseded",
                      "replaced", "taken down", "撤回", "撤销")

_ART_PII_RES = (
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("银行卡号", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),
    ("电话号码", re.compile(r"\b\d{3}-\d{3}-\d{4}\b")),
)


def _art_currency_of(unit):
    """单位字符串 → 币种码；解析不出返回 None。"""
    u = str(unit or "").lower()
    for sym, code in _ART_CUR_SYMBOLS:
        if sym in u:
            return code
    for w, code in _ART_CUR_WORDS.items():
        if w in u.split():
            return code
    return None


def _art_flex_date(s):
    """ISO / MM-DD-YYYY / DD-MM-YYYY / YYYY年M月D日 → date；解析失败返回 None。

    a/b 均 ≤12 时按 MM/DD（美式）读；任一 >12 时由取值唯一确定，两种写法
    （31/12/2025 与 12/31/2025）都能被同一个 case 内一致地解析。
    """
    if not s:
        return None
    t = str(s).strip()
    m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", t)
        if not m:
            return None
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 >= b:
            d, mo = a, b
        else:
            mo, d = a, b
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def _art_cross_section(a):
    """分部截面加总 vs 声明合计（cross_section_mismatch）。

    分部舍入到 0.1 的合计缺口是披露舍入（0.05%），不是截面错——按 0.1%
    相对容差判；超出即截面不一致（把 A 分部的数字挪给了 B）。
    """
    segs = a.get("segments") or []
    total = art_num(a.get("stated_total"), None)
    if not segs or total is None:
        return "abstain", "缺 stated_total 或 segments"
    s = sum(art_num(x.get("value")) for x in segs)
    rel = abs(s - total) / abs(total)
    if rel <= _ART_SUM_TOL:
        return "consistent", f"分部加总 {s:g} ≈ 合计 {total:g}（相对差 {rel * 100:.3f}% ≤ 0.1%）"
    return "violation", f"分部加总 {s:g} ≠ 合计 {total:g}（相对差 {rel * 100:.2f}% > 0.1%）"


def _art_currency_mixing(a):
    """跨币种直接相加而无汇率（currency_mixing）。

    币种检查必须先于加总检查：名义和相等（1000 USD + 500 CNY = 1500）正是
    这类错误的伪装，先比加总会把它判成 consistent。
    """
    comps = a.get("components") or []
    if not comps:
        return "abstain", "缺 components"
    total = a.get("stated_total")
    units = []
    if isinstance(total, dict) and total.get("unit"):
        units.append(total.get("unit"))
    for c in comps:
        if isinstance(c, dict) and c.get("unit"):
            units.append(c.get("unit"))
    curs = {_art_currency_of(u) for u in units}
    curs.discard(None)
    if len(curs) > 1 and not a.get("fx_rate"):
        return "violation", f"跨币种直接相加（{'/'.join(sorted(curs))}）且未提供汇率，量纲不可加"
    # 同币种（或已给汇率）：按分部加总口径核对
    stated_total = art_num(total.get("value") if isinstance(total, dict) else total, None)
    if stated_total is None:
        return "consistent", f"币种单一（{sorted(curs) or '未标注'}），无合计可核对"
    s = sum(art_num(c.get("value")) for c in comps if isinstance(c, dict))
    rel = abs(s - stated_total) / abs(stated_total) if stated_total else 0.0
    if rel <= _ART_SUM_TOL:
        return "consistent", f"币种相容且加总 ≈ 合计（相对差 {rel * 100:.3f}%）"
    return "violation", f"组件加总 {s:g} ≠ 合计 {stated_total:g}（相对差 {rel * 100:.2f}%）"


def _art_duplicate_row(a):
    """表格重复行（duplicate_row）：同名行出现多次即重复计数风险。"""
    rows = a.get("rows") or []
    if not rows:
        return "abstain", "缺 rows"
    names = [str((r.get("name") if isinstance(r, dict) else r) or "").strip().lower()
             for r in rows]
    dups = sorted({n for n in names if names.count(n) > 1})
    if dups:
        return "violation", f"重复行：{dups} 出现多次，存在重复计数/版本残留风险"
    return "consistent", "行名唯一"


def _art_date_inconsistency(a):
    """本期 vs 对比期窗口不一致（date_inconsistency）。

    两条判定线：①对比期必须早于本期期末（时序不可能）；②跨度差 ≤1 天
    （容忍闰年漂移）且期末月-日对齐——对比期被截短几天是典型的窗口错。
    """
    ps, pe = _art_flex_date(a.get("period_start")), _art_flex_date(a.get("period_end"))
    cs, ce = _art_flex_date(a.get("comparative_start")), _art_flex_date(a.get("comparative_end"))
    if None in (ps, pe, cs, ce):
        return "abstain", (f"无法解析日期：{a.get('period_start')}/{a.get('period_end')}"
                           f"/{a.get('comparative_start')}/{a.get('comparative_end')}")
    span_p, span_c = (pe - ps).days + 1, (ce - cs).days + 1
    if cs >= pe:
        return "violation", f"对比期起点 {cs} 不早于本期期末 {pe}（时序不可能）"
    if abs(span_p - span_c) > 1:
        return "violation", f"期间跨度不一致（本期 {span_p} 天 vs 对比期 {span_c} 天）"
    if (pe.month, pe.day) != (ce.month, ce.day):
        return "violation", (f"期末错位（本期 {pe.month}-{pe.day} vs 对比期 {ce.month}-{ce.day}）："
                             "对比窗口被截断或错位")
    return "consistent", f"对比窗口与本期对齐（各 {span_p}/{span_c} 天，含闰年漂移）"


def _art_negative_pie(a):
    """饼图负值切片（negative_value_in_pie）：饼图语义不允许负扇区。"""
    slices = a.get("slices") or []
    if not slices:
        return "abstain", "缺 slices"
    neg = [s.get("label") for s in slices if art_num(s.get("value")) < 0]
    if neg:
        return "violation", f"饼图含负值切片：{neg}（负项应入脚注而非扇区）"
    total = a.get("total")
    if total is not None:
        s = sum(art_num(x.get("value")) for x in slices)
        t = art_num(total)
        if t and abs(s - t) / abs(t) > _ART_SUM_TOL:
            return "violation", f"切片加总 {s:g} ≠ 声明合计 {t:g}（>0.1%）"
    return "consistent", "无负值切片，加总与合计一致"


def _art_axis_scale_of(ax):
    """从 y_axis 的 label/unit 解量级：'$ Billions' / '($M)' / unit='B'。"""
    hay = (str(ax.get("label") or "") + " " + str(ax.get("unit") or "")).lower()
    for w, s in (("billions", 1e9), ("billion", 1e9), ("bn", 1e9),
                 ("millions", 1e6), ("million", 1e6), ("mn", 1e6),
                 ("thousands", 1e3), ("thousand", 1e3)):
        if w in hay:
            return s
    m = re.search(r"[_\s(]([bmk])[\s)]", hay + " ")
    if m:
        return {"b": 1e9, "m": 1e6, "k": 1e3}[m.group(1)]
    return None


def _art_axis_unit(a):
    """轴单位与数值量级错配（axis_unit_mismatch）：以全年披露值作量级锚。

    单点值超过全年披露值（单季不可能大于全年）或序列总和明显超过全年，
    都是轴单位写小了；反之容许部分期间序列小于全年。
    """
    ref = a.get("company_annual_revenue_usd")
    series = a.get("series") or []
    ax = a.get("y_axis") or {}
    if not series or ref is None:
        return "abstain", "缺 series 或全年参照值（无锚不猜）"
    scale = _art_axis_scale_of(ax)
    if scale is None:
        return "abstain", f"无法解析轴单位：{ax.get('label') or ax.get('unit')}"
    vals = [art_num(x.get("value")) * scale for x in series]
    ref = float(ref)
    if max(vals) > ref * 1.2:
        return "violation", (f"单点值 {max(vals):.3g} 超过全年披露值 {ref:.3g}"
                             f"（轴单位低估 {max(vals) / ref:.0f}×）")
    if sum(vals) > ref * 1.5:
        return "violation", f"序列总和 {sum(vals):.3g} 超过全年披露值 {ref:.3g} 的 1.5 倍"
    return "consistent", f"量级与全年披露值相容（总和/全年 = {sum(vals) / ref:.2f}）"


def _art_double_counted_flow(a):
    """聚合+明细双通道重复计数（double_counted_flow）。

    同一节点同时从一条祖先链的两个层级获得流入（Total→A 与 Total→A 的
    子节点并存），A 的量被计了两次——拓扑守恒检查抓不到，必须比对路径。
    """
    nodes, links = a.get("nodes") or [], a.get("links") or []
    if not nodes or not links:
        return "abstain", "缺 nodes 或 links"
    outgoing = {}
    for l in links:
        outgoing.setdefault(l.get("source"), []).append(l.get("target"))

    def _reach(src, dst, seen=None):
        seen = seen or set()
        if src == dst:
            return True
        if src in seen:
            return False
        seen.add(src)
        return any(_reach(t, dst, seen) for t in outgoing.get(src, ()))

    incoming = {}
    for l in links:
        incoming.setdefault(l.get("target"), []).append(l.get("source"))
    for tgt, srcs in incoming.items():
        for i in range(len(srcs)):
            for j in range(i + 1, len(srcs)):
                if _reach(srcs[i], srcs[j]) or _reach(srcs[j], srcs[i]):
                    return "violation", (f"节点 {tgt} 同时从 {srcs[j]} 与其上游 {srcs[i]} "
                                         "获得流入：聚合与明细被重复计入")
    stated = a.get("stated_total_revenue") or a.get("stated_total")
    if stated is not None:
        roots = {n for n in nodes if n not in incoming}
        out_root = sum(art_num(l.get("value")) for l in links if l.get("source") in roots)
        if out_root > art_num(stated) * (1 + _ART_SUM_TOL):
            return "violation", f"根节点流出合计 {out_root:g} 超过声明合计 {art_num(stated):g}（重复计入）"
    return "consistent", "无聚合/明细双通道重复计数"


def _art_stacked_bar(a):
    """堆叠柱分部加总 vs 柱合计（stacked_bar_total_mismatch）。"""
    bars = a.get("bars") or []
    checkable = [b for b in bars if b.get("total") is not None]
    if not checkable:
        return "abstain", "缺 bars 或各柱均无 total"
    for b in checkable:
        s = sum(art_num(x.get("value")) for x in (b.get("segments") or []))
        t = art_num(b.get("total"))
        if t and abs(s - t) / abs(t) > _ART_SUM_TOL:
            return "violation", (f"{b.get('year') if b.get('year') is not None else b.get('label')}: "
                                 f"分部加总 {s:g} ≠ 合计 {t:g}（>0.1%）")
    return "consistent", "各柱分部加总与合计一致"


def _art_dual_axis(a):
    """双轴刻度反转（dual_axis_scale_inversion）：min > max 会把趋势视觉反转。"""
    axes = []
    for k in ("left_axis", "right_axis", "y_axis", "x_axis"):
        ax = a.get(k)
        if isinstance(ax, dict) and ax.get("min") is not None and ax.get("max") is not None:
            axes.append((k, ax))
    if not axes:
        return "abstain", "无带 min/max 的轴"
    for k, ax in axes:
        if art_num(ax.get("min")) > art_num(ax.get("max")):
            return "violation", (f"{k} 刻度反转（min {ax.get('min')} > max {ax.get('max')}）："
                                 "趋势被视觉反转")
    return "consistent", "各轴刻度方向正常"


def _art_retracted_citation(a):
    """引用被撤回/替换（retracted_citation）：撤回状态是硬缺陷。"""
    status = str(a.get("citation_status") or "").strip().lower()
    url = str(a.get("citation") or "").lower()
    if any(w in status for w in _ART_RETRACT_WORDS):
        return "violation", f"引用已被撤回/替换（citation_status={status}）"
    if status in ("", "none", "active", "live", "ok"):
        if any(w in url for w in _ART_RETRACT_WORDS):
            return "violation", f"URL 含撤回信号但状态标为 {status or '未提供'}：{url}"
        return "consistent", f"引用状态正常（{status or '未标注'}）"
    return "abstain", f"未知引用状态：{status}"


def _art_pii_body(a):
    """正文携带个人敏感信息（pii_in_body）：SSN / 银行卡 / 电话形态。"""
    body = str(a.get("body_excerpt") or "")
    if not body.strip():
        return "abstain", "缺 body_excerpt"
    hits = []
    for name, rx in _ART_PII_RES:
        m = rx.search(body)
        if m:
            hits.append(f"{name}({m.group(0).strip()})")
    if hits:
        return "violation", f"正文含个人敏感信息：{'、'.join(dict.fromkeys(hits))}"
    return "consistent", "未检出 SSN/银行卡/电话号码形态"


def _art_license_norm(s):
    t = re.sub(r"[^a-z0-9.]+", "", s.lower())
    return {"apache2": "apache2.0", "gpl3": "gpl3.0", "gpl2": "gpl2.0",
            "agpl3": "agpl3.0", "lgpl3": "lgpl3.0", "mitlicense": "mit"}.get(t, t)


def _art_license(a):
    """许可证声明与实际不符（license_mismatch）：错报本身就是缺陷。"""
    declared = str(a.get("declared_license") or "").strip()
    actual = str(a.get("actual_license") or "").strip()
    if not declared or not actual:
        return "abstain", "缺 declared_license/actual_license"
    if _art_license_norm(declared) == _art_license_norm(actual):
        return "consistent", f"许可一致（{declared}）"
    tag = "，且资产已再分发" if a.get("redistributed") else ""
    return "violation", f"许可声明不符：declared={declared} vs actual={actual}{tag}"


def _art_stale_disclaimer(a):
    """免责声明过时（stale_disclaimer）：声明锚定的年份远早于报告日。"""
    text = str(a.get("disclaimer_text") or "")
    rd = _art_flex_date(a.get("report_date"))
    if not text.strip():
        return "abstain", "缺 disclaimer_text"
    if rd is None:
        return "abstain", f"无法解析报告日：{a.get('report_date')}"
    anchors = {int(y) for y in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)}
    fym = re.search(r"\bfy\s*(\d{4})\b", text.lower())
    if fym:
        anchors.add(int(fym.group(1)))
    if not anchors:
        return "consistent", "声明未锚定具体年份（动态表述，随报告日更新）"
    stale = sorted(y for y in anchors if rd.year - y >= 2)
    if stale:
        return "violation", f"声明锚定 {stale}，报告日 {rd.year}：免责已过时未更新"
    return "consistent", f"声明锚定年份 {sorted(anchors)} 与报告日 {rd.year} 相容"


_ART_AUDITORS = {
    "reconcile": _art_reconcile,
    "waterfall": _art_waterfall,
    "sankey": _art_sankey,
    "period": _art_period,
    "metrics_table": _art_metrics_table,
    "porter_slot": _art_porter,
    "gate_source": _art_gate_source,
    "user_agent": _art_user_agent,
    "packaging_profile": _art_packaging,
    # v2.17.0：图表/文档结构域
    "cross_section_mismatch": _art_cross_section,
    "currency_mixing": _art_currency_mixing,
    "duplicate_row": _art_duplicate_row,
    "date_inconsistency": _art_date_inconsistency,
    "negative_value_in_pie": _art_negative_pie,
    "axis_unit_mismatch": _art_axis_unit,
    "double_counted_flow": _art_double_counted_flow,
    "stacked_bar_total_mismatch": _art_stacked_bar,
    "dual_axis_scale_inversion": _art_dual_axis,
    "retracted_citation": _art_retracted_citation,
    "pii_in_body": _art_pii_body,
    "license_mismatch": _art_license,
    "stale_disclaimer": _art_stale_disclaimer,
}
_ART_ABSTAIN_KINDS = {"narrative", "web_fact"}


def artifact_audit(artifact, tol_pp=0.5, tol_rel=0.005):
    """对结构化产物做确定性缺陷检查。

    返回 verdict ∈ consistent / violation / abstain。
    narrative 与 web_fact 类没有离线判据，按设计返回 abstain（该弃权时要弃权）。
    """
    if not isinstance(artifact, dict):
        return {"verdict": "abstain", "reason": "artifact 不是对象", "kind": None}
    kind = artifact.get("kind")
    if kind in _ART_ABSTAIN_KINDS:
        return {"kind": kind, "verdict": "abstain",
                "reason": f"{kind} 无离线判据，应交人工或联网核验"}
    fn = _ART_AUDITORS.get(kind)
    if fn is None:
        return {"kind": kind, "verdict": "abstain", "reason": f"无对应检查器：{kind}"}
    try:
        if kind == "reconcile":
            verdict, reason = fn(artifact, tol_pp, tol_rel)
        else:
            verdict, reason = fn(artifact)
    except (TypeError, ValueError, KeyError) as e:
        return {"kind": kind, "verdict": "abstain", "reason": f"解析失败：{e}"}
    return {"kind": kind, "verdict": verdict, "reason": reason,
            "tolerances": {"pp": tol_pp, "rel": tol_rel}}


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

    sp = sub.add_parser("dual_extract", help="两次独立抽取对账：一致才裁决，冲突即弃权")
    sp.add_argument("--json", dest="dual_json", default=None, help="first/second JSON 字符串")
    sp.add_argument("--file", default=None, help="first/second JSON 文件")
    sp.add_argument("--tolerance", type=float, default=VALUE_TOLERANCE)

    sp = sub.add_parser("claim_gate", help="证据充分性闸门：PASS/FAIL/ABSTAIN（先判能不能判）")
    sp.add_argument("--json", dest="gate_json", default=None, help="claim/evidence JSON 字符串")
    sp.add_argument("--file", default=None, help="claim/evidence JSON 文件")
    sp.add_argument("--tolerance", type=float, default=VALUE_TOLERANCE)

    sp = sub.add_parser("coverage_scan", help="拆解覆盖率下界扫描：防漏拆（给出必须被拆的最小条数与行号）")
    sp.add_argument("--text", default=None, help="报告文本；与 --file 二选一")
    sp.add_argument("--file", default=None, help="报告文件路径（UTF-8）")
    sp.add_argument("--claims", type=int, default=None, help="已拆解主张数，用于对账（低于下界即报 UNDER_COVERED）")
    sp.add_argument("--budget", type=int, default=None, help="抽样审预算：按优先级给出 top-N 抽样清单与覆盖率")
    sp.add_argument("--max-points", type=int, default=200, help="最多回显多少个应拆解点")

    sp = sub.add_parser("saturation_scan", help="规模饱和扫：零 token 机械复算全文自洽点（表内加总/占比列/同句同比/同句占比/引用时序/预测扫）")
    sp.add_argument("--text", default=None, help="报告文本；与 --file 二选一")
    sp.add_argument("--file", default=None, help="报告文件路径（UTF-8）")
    sp.add_argument("--max-findings", type=int, default=200, help="最多回显多少条 finding")

    sp = sub.add_parser("artifact_audit", help="结构化产物缺陷检查：22 类可判缺陷 + 2 类按设计弃权")
    sp.add_argument("--json", dest="artifact_json", default=None, help="产物 JSON 字符串")
    sp.add_argument("--file", default=None, help="产物 JSON 文件路径（内含 artifact 对象或裸对象）")
    sp.add_argument("--tol-pp", type=float, default=0.5, help="百分点容差（默认 0.5）")
    sp.add_argument("--tol-rel", type=float, default=0.005, help="相对容差（默认 0.005）")

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
    elif cmd == "dual_extract":
        raw = args.dual_json
        if not raw and args.file:
            with open(args.file, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        if not raw:
            _out({"error": "dual_extract 需要 --json 或 --file"})
            return 2
        obj = json.loads(raw)
        _out(dual_extract(obj.get("first") or {}, obj.get("second") or {},
                          tolerance=args.tolerance))
    elif cmd == "claim_gate":
        raw = args.gate_json
        if not raw and args.file:
            with open(args.file, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        if not raw:
            _out({"error": "claim_gate 需要 --json 或 --file"})
            return 2
        _out(claim_gate(json.loads(raw), tolerance=args.tolerance))
    elif cmd == "coverage_scan":
        text = args.text
        if not text and args.file:
            with open(args.file, encoding="utf-8", errors="replace") as f:
                text = f.read()
        if not text:
            _out({"error": "coverage_scan 需要 --text 或 --file"})
            return 2
        _out(coverage_scan(text, claims=args.claims, max_points=args.max_points,
                           budget=args.budget))
    elif cmd == "saturation_scan":
        text = args.text
        if not text and args.file:
            with open(args.file, encoding="utf-8", errors="replace") as f:
                text = f.read()
        if not text:
            _out({"error": "saturation_scan 需要 --text 或 --file"})
            return 2
        _out(saturation_scan(text, max_findings=args.max_findings))
    elif cmd == "artifact_audit":
        raw = args.artifact_json
        if not raw and args.file:
            with open(args.file, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        if not raw:
            _out({"error": "artifact_audit 需要 --json 或 --file"})
            return 2
        obj = json.loads(raw)
        # 兼容两种输入：裸 artifact，或含 artifact 字段的 case
        art = obj.get("artifact", obj) if isinstance(obj, dict) else obj
        _out(artifact_audit(art, tol_pp=args.tol_pp, tol_rel=args.tol_rel))
    else:
        _out({"error": f"unknown command {cmd}"})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
