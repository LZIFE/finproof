"""Phase 23.8 重构金融数值解析。

Structured FinancialValue：13 字段
- raw_text / normalized_value / scale / currency / unit / percentage_type / sign
- metric / period / source_span / extraction_confidence

支持：
- 1,234.56 与 1234.56（千分位，中英文逗号）
- 亿元/万元/千元/元/百万/十亿/million/billion
- 百分比 / 百分点 / basis points
- 正负号 / 括号负数 (1,081,776)
- 同比增长 / 下降 / 亏损扩大 / 收窄
- 多数字同时出现时的 metric+period+unit+scope+source_span 绑定
- 表格行名/列名与数字的就近绑定

数字匹配同时考虑：metric + period + unit + scope + source_span
不再简单选 Evidence 中第一个数字。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterator


# ---------------------------------------------------------------------------
# 单位与 scale 映射
# ---------------------------------------------------------------------------
# 中文/英文单位到 base-10 scale 的映射（统一换算为元或百分比）
UNIT_SCALE: dict[str, float] = {
    "亿元": 1e8, "万万元": 1e8, "万元": 1e4, "千元": 1e3, "元": 1.0,
    "百万": 1e6, "十亿": 1e9, "百亿": 1e10,
    # 复合中文单位：真实财报写「百万元」「十亿元」，原表只有「百万」「十亿」，
    # 导致 convert 静默按 1 倍处理，差 1e6（2026-10-26 CFR-NumQA 实测发现）
    "十万元": 1e5, "百万元": 1e6, "千万元": 1e7,
    "十亿元": 1e9, "百亿元": 1e10, "千亿元": 1e11, "万亿元": 1e12,
    "万亿": 1e12, "千万": 1e7,
    "million": 1e6, "billion": 1e9, "mb": 1e6, "b": 1e9,
}

# ── 单位归一化（与 skills/finproof-verification/bin/finproof_calc.py 对齐）──
# 原先 `UNIT_SCALE.get(unit, 1.0)` 对「亿美元」「million USD」等写法静默按 1 倍，
# 差 1e4~1e9 且无警告。改为解析量级词 + 货币词，解析不出来就抛错。
_CUR_WORDS = {
    "usd": "USD", "us$": "USD", "$": "USD", "美元": "USD", "美金": "USD",
    "cny": "CNY", "rmb": "CNY", "¥": "CNY", "￥": "CNY", "人民币": "CNY", "元": "CNY",
    "hkd": "HKD", "hk$": "HKD", "港元": "HKD", "港币": "HKD",
    "eur": "EUR", "€": "EUR", "欧元": "EUR",
}
_SCALE_WORDS = [
    ("万亿", 1e12), ("千亿", 1e11), ("百亿", 1e10), ("十亿", 1e9), ("亿", 1e8),
    ("千万", 1e7), ("百万", 1e6), ("十万", 1e5), ("万", 1e4), ("千", 1e3),
    ("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3),
    ("bn", 1e9), ("mn", 1e6), ("mm", 1e6), ("k", 1e3),
]

# 物理计量单位（与技能引擎保持同一集合）。财务报告里的产量/能耗/面积/门店数
# 不能因为不是货币就被丢弃或当作无量纲数。
_PHYSICAL_UNITS = (
    "吨标准煤", "千瓦时", "平方米", "立方米", "平方公里", "平方英尺", "平方千米",
    "千瓦", "兆瓦", "吉瓦", "公顷", "公里", "千米", "加仑", "盎司", "克拉",
    "吨", "桶", "头", "只", "羽", "台", "套", "辆", "架", "艘", "件", "人",
    "户", "家", "座", "条", "亩", "升", "度", "瓦",
)
_PHYS_ALT = "|".join(re.escape(x) for x in _PHYSICAL_UNITS)
_PHYS_RE = re.compile(r"^(?:" + _PHYS_ALT + r")(?:/[年月日人台吨]{1,3})?")


def _physical_unit_of(u: str):
    """识别物理单位（可带量级前缀），返回 (完整单位, scale) 或 None。"""
    pm = _PHYS_RE.fullmatch(u)
    if pm:
        return pm.group(0), 1.0
    for w, s in _SCALE_WORDS:
        if u.startswith(w):
            pm = _PHYS_RE.fullmatch(u[len(w):])
            if pm:
                return w + pm.group(0), s
    return None


def _unit_currency(u_lower: str) -> str | None:
    for k in sorted(_CUR_WORDS, key=len, reverse=True):
        if k in u_lower:
            return _CUR_WORDS[k]
    return None


_RATIO_UNITS = frozenset({"%", "％", "percent", "percentage", "pct",
                          "pp", "percentage_point", "个百分点", "百分点",
                          "bp", "basis point", "basis points"})


def parse_unit(unit):
    """解成 (scale, currency)。未知单位抛 ValueError，不再静默按 1 倍。"""
    if unit is None:
        return 1.0, None
    raw = str(unit).strip()
    if not raw:
        return 1.0, None
    u = raw.lower().replace(" ", "")
    if u in _RATIO_UNITS:
        return 1.0, None
    if raw in UNIT_SCALE:
        return UNIT_SCALE[raw], _unit_currency(u)
    phys = _physical_unit_of(u)
    if phys:
        return phys[1], None
    cur = _unit_currency(u)
    for w, sc in _SCALE_WORDS:
        if w in u:
            return sc, cur
    if cur is not None:
        return 1.0, cur
    raise ValueError(f"未知单位：{raw!r}（不再按 1 倍静默处理）")


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

# Currency 识别（英文单位默认 USD，中文默认 CNY）
USD_UNITS: frozenset[str] = frozenset({"million", "billion", "mb", "b"})

# 百分比类型
PERCENT_TOKENS: tuple[str, ...] = ("%", "百分点", "basis points", "bp", "个百分点")


# ---------------------------------------------------------------------------
# FinancialValue 数据结构
# ---------------------------------------------------------------------------
@dataclass
class FinancialValue:
    """结构化金融数值（13 字段）。"""
    raw_text: str
    normalized_value: float           # 已剥离千分位、未换算单位的原始数值
    scale: float                      # unit 对应的 scale（亿元=1e8, 元=1.0, 无单位=1.0）
    currency: str                     # "CNY" | "USD" | ""
    unit: str                         # 原始单位文本（亿元/万元/千元/元/百万/十亿/million/billion/""）
    percentage_type: str              # "percentage" | "percentage_point" | "basis_point" | ""
    sign: str                         # "positive" | "negative_paren" | "negative_sign" | "yoy_decline" | ""
    metric: str                       # 上下文绑定的指标（revenue/net_profit/...），抽取后由调用方填充
    period: str                       # 上下文绑定的期间（2025FY/2025Q2/...），抽取后由调用方填充
    source_span: tuple[int, int]      # 在原文中的 [start, end) 位置
    extraction_confidence: float     # 0.0-1.0，有单位/明确符号则更高

    @property
    def absolute_value_in_yuan(self) -> float:
        """换算为元的绝对值（含 scale 与 sign）。"""
        base = self.normalized_value * self.scale
        if self.sign in ("negative_paren", "negative_sign", "yoy_decline"):
            return -abs(base)
        return base

    def to_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "normalized_value": round(self.normalized_value, 6),
            "scale": self.scale,
            "currency": self.currency,
            "unit": self.unit,
            "unit_kind": unit_kind(self.unit),
            "percentage_type": self.percentage_type,
            "sign": self.sign,
            "metric": self.metric,
            "period": self.period,
            "source_span": list(self.source_span),
            "extraction_confidence": round(self.extraction_confidence, 3),
            "absolute_value_in_yuan": round(self.absolute_value_in_yuan, 4),
        }


# ---------------------------------------------------------------------------
# 抽取器
# ---------------------------------------------------------------------------
# 千分位分隔：1,234.56 / 1,234,567 / 中文逗号全角､ / 全角逗号，
_COMMA_RE = re.compile(r"[,､，]")
# 千分位字符类（用于数值主体模式内嵌，不剥离，仅匹配）
_COMMA_CLASS = r"[,､，]"

# 数值主体：可选负号 + 数字(含千分位) + 可选小数
# 注意：括号负数单独匹配，避免与普通数值重叠
# 千分位分隔符必须在两个数字之间（前导后随均需 \d），避免逗号被误认为普通分隔
_NUMBER_BODY = r"-?\d+(?:" + _COMMA_CLASS + r"\d+)*(?:\.?\d+)?"
_NUMBER_BODY_PLAIN = r"\d+(?:" + _COMMA_CLASS + r"\d+)*(?:\.?\d+)?"

# 单位（按长度降序匹配，避免"万元"被"元"截断）
_UNITS_SORTED = sorted(UNIT_SCALE.keys(), key=len, reverse=True)
# 注意：从单位列表中移除 "b" 与 "mb" 单独作为单位匹配（会截断 "basis"/"billion"），
# 仅在 _UNIT_PATTERN 中保留，但抽取主循环会优先匹配 basis points/bp 百分比
_UNITS_FOR_PATTERN = [u for u in _UNITS_SORTED if u not in ("b", "mb")]
_UNIT_PATTERN = "|".join(re.escape(u) for u in _UNITS_FOR_PATTERN)

# 百分比 / 百分点 / basis points
# 注意：basis points / bp 可能紧贴数字（50bp）或有空格（25 basis points）
_PERCENT_PATTERN = r"(\.\s*|\s+)?(百分点|个百分点|basis\s*points|bp|%)"

# 括号负数：(1,081,776) 千元 / (456,451,731)
_PAREN_NEG_RE = re.compile(
    r"\((" + _NUMBER_BODY_PLAIN + r")\)\s*(" + _UNIT_PATTERN + r")?",
    re.UNICODE,
)

# 普通数值 + 单位 + 可选百分比/bp
# 顺序：数值 → 单位? → 百分比/bp?
# 百分比/bp 可紧贴数字（50bp, 12.11%）或带空格（25 basis points）
_PLAIN_RE = re.compile(
    r"(" + _NUMBER_BODY + r")\s*(" + _UNIT_PATTERN + r")?[\s　]*((?:百分点|个百分点|basis\s*points|bp|%)|%)?",
    re.UNICODE | re.IGNORECASE,
)
_UNIT_CAND_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z$￥¥€/]{1,8}")


def _complete_physical_unit(unit: str, tail: str) -> str:
    """把「万」+「吨」补成「万吨」；货币单位不参与。"""
    if not unit or _unit_currency(unit):
        return unit
    if unit not in {w for w, _ in _SCALE_WORDS}:
        return unit
    m = _PHYS_RE.match(tail.lstrip())
    return unit + m.group(0) if m else unit


def _resolve_unit(unit: str, tail: str) -> str:
    """无单位时从数字尾部取候选；有量级词时补物理单位。"""
    if not unit:
        m = _UNIT_CAND_RE.match(tail)
        if m and m.group(0) not in ("同比", "环比", "增长", "下降", "提升", "回落", "个百分点"):
            return m.group(0)
        return unit
    return _complete_physical_unit(unit, tail)

# 同比增长/下降/亏损扩大/收窄 等方向词（紧邻数值前，可含尾随空格）
# 注意：用在 prefix 文本末尾搜索，不需 $ 锚点；允许方向词后有空格再接数值
_DIRECTION_RE = re.compile(
    r"(同比增长|同比下降|增长|下降|亏损扩大|亏损收窄|减少|降低|提升|增加)\s*",
    re.UNICODE,
)

# 同比基期：比上年/上年/去年
_YOY_BASE_RE = re.compile(r"(比上年|上年|去年|同比)", re.UNICODE)


def extract_financial_values(
    text: str,
    context_metric: str | None = None,
    context_period: str | None = None,
    context_unit: str | None = None,
) -> list[FinancialValue]:
    """从文本抽取所有 FinancialValue。

    Phase 23.8 重构：不再简单选第一个数字，而是抽取所有候选并标注
    metric/period/unit/scale/sign/source_span。

    Args:
        text: 原始文本（Evidence block 或 claim text）
        context_metric: 上下文指标（claim 的 metric 字段，用于绑定）
        context_period: 上下文期间（claim 的 period 字段）
        context_unit: 上下文单位（claim 的 unit 字段，作为无单位时的回退）

    Returns:
        所有抽取的 FinancialValue 列表（按 source_span 升序）
    """
    if not text:
        return []
    # 归一化：NFKC + 显式将中文顿号、(0x3001)与全角逗号，(0xff0c)转为半角,
    # （NFKC 将全角逗号､(0xff64)转为中文顿号、(0x3001)，不转为半角，需显式替换）
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("、", ",").replace("，", ",")
    results: list[FinancialValue] = []
    occupied: list[tuple[int, int]] = []

    # 1. 先匹配括号负数（优先，避免与普通数值重叠）
    for m in _PAREN_NEG_RE.finditer(normalized):
        raw = m.group(0)
        num_str = _strip_commas(m.group(1))
        try:
            val = float(num_str)
        except ValueError:
            continue
        unit = m.group(2) or context_unit or ""
        unit = _resolve_unit(unit, normalized[m.end():])
        fv = _make_fv(raw, val, unit, "negative_paren", m.span(),
                      context_metric, context_period)
        results.append(fv)
        occupied.append(m.span())

    # 2. 预提取括号内单位（如"营业收入(千元) 456,451,731"），Phase 23.11.4 §7
    # 括号单位出现在数字之前，正则无法捕获（正则只匹配数字后的单位）
    # NFKC 已将全角（）转为半角()
    _PAREN_UNIT_RE = re.compile(r"\((" + _UNIT_PATTERN + r")\)\s*")
    paren_units = {}
    for pu in _PAREN_UNIT_RE.finditer(normalized):
        # Associate this unit with the next number(s) in the text
        # Find the next number occurrence after this unit
        next_num = _PLAIN_RE.search(normalized, pu.end())
        if next_num:
            paren_units[next_num.start()] = pu.group(1)

    # 2. 再匹配普通数值（跳过括号区域）
    for m in _PLAIN_RE.finditer(normalized):
        if any(_overlap(m.span(), r) for r in occupied):
            continue
        raw = m.group(0).strip()
        num_str = _strip_commas(m.group(1))
        try:
            val = float(num_str)
        except ValueError:
            continue
        # Check if a paren-unit was found near this number
        paren_unit = None
        for pos, pu in sorted(paren_units.items()):
            if abs(pos - m.start()) < 20:  # within 20 chars
                paren_unit = pu
                break
        unit = m.group(2) or paren_unit or context_unit or ""
        unit = _resolve_unit(unit, normalized[m.end():])
        pct = m.group(3) or ""
        sign = _detect_sign(normalized, m.span(), val)
        pct_type = _classify_pct(pct)
        # normalized_value 存绝对值（符号由 sign 字段表达，避免 -54.55 与 54.55 被视为不同数值）
        abs_val = abs(val)
        fv = _make_fv(raw, abs_val, unit, sign, m.span(),
                      context_metric, context_period, pct_type=pct_type)
        results.append(fv)

    # 按位置排序
    results.sort(key=lambda fv: fv.source_span[0])
    return results


def _make_fv(raw: str, value: float, unit: str, sign: str,
             span: tuple[int, int], metric: str | None, period: str | None,
             pct_type: str = "") -> FinancialValue:
    """构建 FinancialValue。"""
    try:
        scale, cur = parse_unit(unit)
    except ValueError:
        scale, cur = 1.0, None   # 抽取路径不整体失败，但 currency 留空表示未解析
    currency = cur or ("USD" if unit and unit.lower() in USD_UNITS else ("CNY" if unit else ""))
    confidence = 0.85 if unit else (0.6 if pct_type else 0.5)
    if sign in ("negative_paren", "negative_sign"):
        confidence = max(confidence, 0.9)
    return FinancialValue(
        raw_text=raw,
        normalized_value=value,
        scale=scale,
        currency=currency,
        unit=unit,
        percentage_type=pct_type,
        sign=sign,
        metric=metric or "",
        period=period or "",
        source_span=span,
        extraction_confidence=confidence,
    )


def _strip_commas(s: str) -> str:
    """剥离千分位分隔符（中英文逗号、全角､）。"""
    return _COMMA_RE.sub("", s)


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] <= b[0] or b[1] <= a[0])


def _detect_sign(text: str, span: tuple[int, int], val: float) -> str:
    """检测数值的符号上下文。

    - 负号前缀（-1.08）→ negative_sign
    - 括号负数已在 _PAREN_NEG_RE 处理
    - 同比下降/亏损扩大/减少 → yoy_decline（负方向）
    - 同比增长/提升/增加 → positive（正方向）
    """
    if val < 0:
        return "negative_sign"
    # 检查数值前 20 字符的方向词（取最后一个匹配，即紧邻数值的）
    prefix = text[max(0, span[0] - 20):span[0]]
    matches = list(_DIRECTION_RE.finditer(prefix))
    if matches:
        word = matches[-1].group(1)
        # 下降类：含"下降"/"亏损扩大"/"减少"/"降低"或"同比下降"等复合词
        decline_markers = ("下降", "亏损扩大", "减少", "降低")
        if any(m in word for m in decline_markers):
            return "yoy_decline"
        return "positive"
    return "positive"


def _classify_pct(pct: str) -> str:
    """分类百分比类型。"""
    p = pct.lower().strip()
    if "basis" in p or p == "bp":
        return "basis_point"
    if "百分点" in pct or "个百分点" in pct:
        return "percentage_point"
    if "%" in pct:
        return "percentage"
    return ""


# ---------------------------------------------------------------------------
# 数值匹配（含 metric + period + unit + scope 绑定）
# ---------------------------------------------------------------------------
def values_match(
    claim_value: float,
    claim_unit: str,
    evidence_fv: FinancialValue,
    tolerance: float = 0.005,
    require_unit: bool = True,
) -> tuple[bool, str]:
    """判断 claim 数值与 evidence FinancialValue 是否匹配。

    Args:
        claim_value: claim 的数值（已剥离千分位）
        claim_unit: claim 的单位（亿元/万元/千元/元/...）
        evidence_fv: evidence 抽取的 FinancialValue
        tolerance: 相对容差（默认 0.5%）
        require_unit: 是否要求单位换算后比较（True=换算为元后比较）

    Returns:
        (matched, reason)
    """
    if require_unit:
        # 换算为元后比较
        _sc, _cur = parse_unit(claim_unit)   # 未知单位抛错，不静默
        claim_in_yuan = claim_value * _sc
        ev_in_yuan = evidence_fv.absolute_value_in_yuan
        if claim_in_yuan == 0 and ev_in_yuan == 0:
            return True, "均为 0"
        if claim_in_yuan == 0 or ev_in_yuan == 0:
            return False, f"一方为 0（claim={claim_in_yuan}, ev={ev_in_yuan}）"
        ratio = ev_in_yuan / claim_in_yuan
        if abs(ratio - 1.0) <= tolerance:
            return True, f"换算元后匹配（claim={claim_in_yuan:.2f}, ev={ev_in_yuan:.2f}, ratio={ratio:.4f}）"
        return False, f"换算元后不匹配（claim={claim_in_yuan:.2f}, ev={ev_in_yuan:.2f}, ratio={ratio:.4f}）"
    else:
        # 直接数值比较（百分比/百分点）
        if claim_value == 0 and evidence_fv.normalized_value == 0:
            return True, "均为 0"
        ratio = evidence_fv.normalized_value / claim_value if claim_value != 0 else 0
        if abs(ratio - 1.0) <= tolerance:
            return True, f"数值匹配（claim={claim_value}, ev={evidence_fv.normalized_value}, ratio={ratio:.4f}）"
        return False, f"数值不匹配（claim={claim_value}, ev={evidence_fv.normalized_value}, ratio={ratio:.4f}）"


def find_best_match(
    claim_value: float,
    claim_unit: str,
    claim_metric: str,
    claim_period: str,
    evidence_fvs: list[FinancialValue],
    tolerance: float = 0.005,
) -> tuple[FinancialValue | None, str]:
    """在 evidence FinancialValue 列表中找最佳匹配。

    Phase 23.8 重构：不再选第一个数字，而是按 metric + period + unit + scope 综合评分。
    多数字歧义时优先选 metric/period 匹配的数字。

    Returns:
        (best_match, reason)
    """
    if not evidence_fvs:
        return None, "无 evidence FinancialValue"

    candidates: list[tuple[FinancialValue, float, str]] = []
    for fv in evidence_fvs:
        # 数值匹配
        matched, match_reason = values_match(claim_value, claim_unit, fv, tolerance)
        if not matched:
            continue
        # 综合评分：metric 匹配 + period 匹配 + extraction_confidence
        score = fv.extraction_confidence
        if fv.metric and claim_metric and fv.metric == claim_metric:
            score += 0.3
        if fv.period and claim_period and fv.period == claim_period:
            score += 0.3
        # 有单位的优先于无单位的（更明确）
        if fv.unit:
            score += 0.1
        # 符号明确的优先
        if fv.sign in ("negative_paren", "negative_sign", "yoy_decline"):
            score += 0.05
        candidates.append((fv, score, match_reason))

    if not candidates:
        return None, "无数值匹配的候选"

    # 按 score 降序选最佳
    candidates.sort(key=lambda x: -x[1])
    best = candidates[0]
    return best[0], f"best match: {best[2]} (score={best[1]:.3f})"


__all__ = [
    "FinancialValue",
    "extract_financial_values",
    "values_match",
    "find_best_match",
    "UNIT_SCALE",
    "parse_unit",
    "unit_kind",
]
