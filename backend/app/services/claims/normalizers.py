"""Phase 3 确定性规则工具：数字/单位/币种/期间/同比环比/指标词典/风险分级。

全部为纯函数，可单测、可解释；LLM 只负责规则无法覆盖的语义补充。
"""

import re
from dataclasses import dataclass

# ---------------------------------------------------------------- 指标词典

# (中文名, 规范名, 代码)；匹配时按名称长度降序（先匹配长名称）
METRIC_DICTIONARY: list[tuple[str, str, str]] = [
    ("归属于上市公司股东的净利润", "归属于上市公司股东的净利润", "net_profit_attributable"),
    ("归属于母公司股东的净利润", "归属于母公司股东的净利润", "net_profit_attributable"),
    ("经营活动产生的现金流量净额", "经营现金流", "operating_cash_flow"),
    ("经营活动现金流量净额", "经营现金流", "operating_cash_flow"),
    ("经营现金流净额", "经营现金流", "operating_cash_flow"),
    ("扣非归母净利润", "扣非归母净利润", "deducted_net_profit"),
    ("营业总收入", "营业总收入", "total_operating_revenue"),
    ("归母净利润", "归母净利润", "net_profit_attributable"),
    ("营业收入", "营业收入", "revenue"),
    ("营收", "营业收入", "revenue"),
    ("基本每股收益", "基本每股收益", "basic_eps"),
    ("每股收益", "每股收益", "eps"),
    ("毛利率", "毛利率", "gross_margin"),
    ("净利率", "净利率", "net_margin"),
    ("费用率", "费用率", "expense_ratio"),
    ("海外市场收入", "海外市场收入", "overseas_revenue"),
    ("海外收入", "海外收入", "overseas_revenue"),
    ("海外业务", "海外业务", "overseas_business"),
    ("机器人业务", "机器人业务", "robot_business"),
    ("机器人及自动化", "机器人及自动化业务", "robot_business"),
    ("智能家居业务", "智能家居业务", "smart_home_business"),
    ("新能源及工业技术", "新能源及工业技术业务", "energy_industrial_business"),
    ("智能建筑科技", "智能建筑科技业务", "building_tech_business"),
    ("收入增速", "收入增速", "yoy_growth_revenue"),
    ("收入同比增长", "收入同比增长", "yoy_growth_revenue"),
    ("同比增长", "同比增长", "growth_rate"),
    ("环比增长", "环比增长", "growth_rate"),
    ("净利润", "净利润", "net_profit"),
    ("经营现金流", "经营现金流", "operating_cash_flow"),
    ("现金流", "现金流", "cash_flow"),
    ("营业收入占比", "营业收入占比", "revenue_share"),
    ("利润", "利润", "profit"),
    ("收入", "收入", "revenue"),
    ("占比", "占比", "share"),
]


def find_metric(text: str) -> tuple[str, str] | None:
    """返回 (metric, metric_code)；按名称长度降序匹配。"""
    for name, metric, code in sorted(METRIC_DICTIONARY, key=lambda m: -len(m[0])):
        if name in text:
            return metric, code
    return None


# ---------------------------------------------------------------- 单位与币种

UNIT_PATTERNS: list[tuple[str, str]] = [
    ("个百分点", "个百分点"),
    ("万亿元", "万亿元"),
    ("亿元", "亿元"),
    ("万元", "万元"),
    ("千元", "千元"),
    ("百万元", "百万元"),
    ("元/股", "元/股"),
    ("元", "元"),
    ("亿股", "亿股"),
    ("万股", "万股"),
    ("%", "PERCENT"),
]

CURRENCY_PATTERNS: list[tuple[str, str]] = [
    ("人民币", "CNY"),
    ("美元", "USD"),
    ("美金", "USD"),
    ("港币", "HKD"),
    ("港元", "HKD"),
    ("欧元", "EUR"),
]

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
PERCENT_RE = re.compile(r"-?\d+(?:\.\d+)?\s*%")
# "数字 + 单位/百分比"成对匹配：跳过 2025 这类裸年份
NUMBER_UNIT_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*((?:万亿元|亿港元|亿美元|亿欧元|亿元|万元|千元|百万元|元/股|元|亿股|万股|个百分点|%))"
)


@dataclass
class ParsedNumber:
    value: float
    operator: str  # ValueOperator
    unit: str | None
    currency: str | None
    value_text: str


def parse_currency(text: str) -> str | None:
    for word, code in CURRENCY_PATTERNS:
        if word in text:
            return code
    # 无显式币种词但出现人民币金额单位（元/亿元/万元等）→ 默认 CNY
    if re.search(r"[亿万]?元|元/股", text):
        return "CNY"
    return None


def detect_operator(text: str) -> str:
    if re.search(r"不超过|不高于|最多", text):
        return "LESS_THAN_OR_EQUAL"
    if re.search(r"不低于|至少|不少于", text):
        return "GREATER_THAN_OR_EQUAL"
    if re.search(r"超过|高于|大于|多于", text):
        return "GREATER_THAN"
    if re.search(r"低于|不足|小于|少于", text):
        return "LESS_THAN"
    if re.search(r"约|接近|约达|近", text):
        return "APPROXIMATELY"
    if re.search(r"\d+(?:\.\d+)?[~\-至]\d+(?:\.\d+)?", text):
        return "RANGE"
    return "EQUAL"


def parse_number(text: str) -> ParsedNumber | None:
    """提取与单位/百分比相邻的数字（避免把 2025 年份当作数值）。"""
    m = NUMBER_UNIT_RE.search(text)
    if not m:
        return None
    value = float(m.group(1))
    raw_unit = m.group(2)
    # 归一化单位（"%": -> "PERCENT"，其余保持原文）
    unit = next((norm for raw, norm in UNIT_PATTERNS if raw == raw_unit), raw_unit)
    return ParsedNumber(
        value=value,
        operator=detect_operator(text),
        unit=unit,
        currency=parse_currency(text),
        value_text=m.group(1),
    )


def parse_percent(text: str) -> float | None:
    m = PERCENT_RE.search(text)
    if m:
        return float(m.group(0).rstrip("%").strip())
    return None


def parse_range(text: str) -> tuple[float, float] | None:
    m = re.search(r"(\d+(?:\.\d+)?)[~\-至](\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


# ---------------------------------------------------------------- 期间标准化

YEAR_RE = re.compile(r"(20\d{2})")
QUARTER_CN = {"一": 1, "二": 2, "三": 3, "四": 4}


def _quarter_number(word: str) -> int | None:
    if re.fullmatch(r"[1-4]", word):
        return int(word)
    if word in QUARTER_CN:
        return QUARTER_CN[word]
    return None


@dataclass
class ParsedPeriod:
    period: str | None  # 2025FY / 2025H1 / 2025Q1 / 2025 / 2026FY ...
    period_type: str  # PeriodType
    year: int | None


def parse_period(text: str, default_year: int | None = None) -> ParsedPeriod | None:
    """期间标准化：2025年度/2025年/上半年/第一季度/Q2 等。"""
    year = default_year
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1))

    # 未来期间
    if re.search(r"20\d{2}年|未来|展望|下一年", text) and re.search(r"将|预计|有望|突破|挑战", text):
        fy = year or default_year
        if fy:
            return ParsedPeriod(period=f"{fy}FY", period_type="FUTURE_PERIOD", year=fy)

    # 年度 / 全年
    if re.search(r"年度|全年", text) and year:
        return ParsedPeriod(period=f"{year}FY", period_type="YEAR", year=year)

    # 上半年 / 下半年（先于季度匹配，避免"较一季度"等比较语干扰）
    if re.search(r"上半年|H1", text) and year:
        return ParsedPeriod(period=f"{year}H1", period_type="HALF_YEAR", year=year)
    if re.search(r"下半年|H2", text) and year:
        return ParsedPeriod(period=f"{year}H2", period_type="HALF_YEAR", year=year)

    # 季度：2025年第一季度 / 第一季度 / 2025Q1 / Q1 / 二季度
    q = None
    qm = re.search(r"(?:第)?([一二三四1-4])季度|Q([1-4])", text)
    if qm:
        q = _quarter_number(qm.group(1) or qm.group(2))
        if q and year:
            return ParsedPeriod(period=f"{year}Q{q}", period_type="QUARTER", year=year)

    # 裸年份
    if year:
        return ParsedPeriod(period=str(year), period_type="YEAR", year=year)
    return None


def _shift_period(period: str | None, year: int | None, comparison_type: str) -> str | None:
    if not period or year is None:
        return None
    if comparison_type == "YEAR_OVER_YEAR":
        prev = year - 1
        if period.endswith("FY"):
            return f"{prev}FY"
        if "H1" in period:
            return f"{prev}H1"
        if "H2" in period:
            return f"{prev}H2"
        m = re.search(r"(Q[1-4])$", period)
        if m:
            return f"{prev}{m.group(1)}"
        return str(prev)
    if comparison_type == "QUARTER_OVER_QUARTER":
        m = re.search(r"(\d{4})(Q[1-4])", period or "")
        if m:
            y, q = int(m.group(1)), int(m.group(2)[1])
            if q == 1:
                return f"{y - 1}Q4"
            return f"{y}Q{q - 1}"
    return None


def detect_comparison(text: str, period: str | None, year: int | None) -> tuple[str, str | None]:
    """返回 (comparison_type, comparison_period)。"""
    if re.search(r"同比|较上年同期|比上年同期|YOY", text):
        return "YEAR_OVER_YEAR", _shift_period(period, year, "YEAR_OVER_YEAR")
    if re.search(r"环比|较上季度|QOQ", text):
        return "QUARTER_OVER_QUARTER", _shift_period(period, year, "QUARTER_OVER_QUARTER")
    if re.search(r"高于行业|高于同行业|优于同行|领先同行", text):
        return "PEER_COMPARISON", None
    return "NONE", None


# ---------------------------------------------------------------- 类型与性质

CAUSAL_WORDS = ["主要由", "主要系", "推动", "导致", "由于", "得益于", "核心引擎", "引擎", "拉动", "贡献"]
FORECAST_WORDS = ["将", "预计", "有望", "预测", "未来", "挑战", "目标", "展望", "突破", "维持买入评级"]
TREND_WORDS = [
    "持续增长",
    "持续改善",
    "持续提升",
    "持续优化",
    "改善",
    "优化",
    "稳步",
    "加速",
    "向好",
    "回暖",
    "回升",
]
OPINION_WORDS = ["我们认为", "我们认为", "看好", "评级", "建议", "判断", "不改变", "处于", "匹配度", "我们认为"]
COMPARISON_WORDS = ["高于", "低于", "快于", "慢于", "优于", "超过", "不及", "领先"]
SHARE_WORDS = ["占比", "过半", "一半以上", "份额"]
CALC_WORDS = ["同比", "环比", "增长", "下降", "增速", "增幅", "提升", "率", "占比"]


def detect_claim_type(text: str, parsed_number: ParsedNumber | None, metric_code: str | None, comparison_type: str) -> str:
    if any(w in text for w in FORECAST_WORDS) and re.search(r"将|有望|预计|目标|预测|未来|突破", text):
        return "FORECAST"
    if any(w in text for w in CAUSAL_WORDS):
        return "CAUSAL_CLAIM"
    if any(w in text for w in SHARE_WORDS) and parsed_number and parsed_number.unit == "PERCENT":
        return "BUSINESS_SHARE"
    if comparison_type in ("YEAR_OVER_YEAR", "QUARTER_OVER_QUARTER") and parsed_number and parsed_number.unit == "PERCENT":
        return "GROWTH_RATE"
    if metric_code in {"gross_margin", "net_margin", "expense_ratio", "revenue_share"} and parsed_number:
        return "FINANCIAL_RATIO"
    if any(w in text for w in COMPARISON_WORDS):
        return "COMPARISON"
    if any(w in text for w in TREND_WORDS) and not parsed_number:
        return "TREND"
    if parsed_number:
        if parsed_number.unit == "PERCENT" and metric_code in {"yoy_growth_revenue", "growth_rate"}:
            return "GROWTH_RATE"
        return "ABSOLUTE_FINANCIAL_VALUE"
    if any(w in text for w in OPINION_WORDS):
        return "OPINION"
    return "BUSINESS_FACT"


def detect_claim_nature(text: str, claim_type: str) -> str:
    if claim_type == "FORECAST":
        return "FORECAST"
    if claim_type == "CAUSAL_CLAIM":
        return "CAUSAL_INTERPRETATION"
    if claim_type == "COMPARISON":
        return "COMPARATIVE_JUDGMENT"
    if any(w in text for w in CALC_WORDS):
        return "CALCULATED_FACT"
    if claim_type == "OPINION":
        return "OPINION"
    return "FACT"


def requires_calculation(claim_type: str, text: str) -> bool:
    return claim_type in ("GROWTH_RATE", "FINANCIAL_RATIO", "BUSINESS_SHARE") or any(
        w in text for w in CALC_WORDS
    )


# ---------------------------------------------------------------- 风险分级

CRITICAL_WORDS = ["并购", "收购", "处罚", "诉讼", "偿债", "违约", "退市", "估值", "现金流危机", "重大合同"]
HIGH_METRIC_CODES = {
    "revenue", "total_operating_revenue", "net_profit_attributable", "net_profit",
    "gross_margin", "operating_cash_flow", "yoy_growth_revenue", "growth_rate",
    "revenue_share", "deducted_net_profit", "basic_eps", "eps", "profit",
    "quarterly_revenue", "quarterly_net_profit_attributable", "share",
}
MEDIUM_KEYWORDS = ["趋势", "改善", "战略", "进展", "布局", "行业", "竞争", "比较", "分部", "地区", "海外"]


def grade_risk(text: str, claim_type: str, metric_code: str | None) -> tuple[str, str]:
    """规则风险分级：CRITICAL > HIGH > MEDIUM > LOW，返回 (等级, 理由)。"""
    if any(w in text for w in CRITICAL_WORDS):
        return "CRITICAL", f"涉及关键决策要素关键词: {'/'.join(w for w in CRITICAL_WORDS if w in text)}"
    if claim_type == "CAUSAL_CLAIM":
        return "HIGH", "因果归因主张，风险较高，需外部证据"
    if metric_code in HIGH_METRIC_CODES:
        return "HIGH", f"核心财务指标({metric_code})，直接影响投资判断"
    if claim_type in ("GROWTH_RATE", "FINANCIAL_RATIO", "BUSINESS_SHARE"):
        return "HIGH", f"增长/比率/占比类主张({claim_type})，需计算核验"
    if claim_type == "FORECAST":
        return "MEDIUM", "预测/展望类主张，属观点非事实"
    if any(w in text for w in MEDIUM_KEYWORDS):
        return "MEDIUM", "经营趋势/战略/行业类主张"
    if claim_type == "OPINION":
        return "MEDIUM", "观点/评级类主张"
    return "LOW", "一般性描述，对投资判断影响有限"
