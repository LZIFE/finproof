"""证据检索引擎（Phase 4A Oracle 模式）——纯函数核心。

流程：
Gold Claim → 文档过滤（公司/代码/财报类型/时间） → 文本块候选（指标别名预筛）
→ 结构化匹配（指标/数值换算/期间/主体/文本相似度） → 加权排序 → Top-K

约束：
- 不使用 gold_evidence / gold_verifications 参与排序（评测脚本在检索完成后独立计算 Hit@K）；
- 不引入向量数据库（document_blocks 扫描 + 指标别名预筛，MVP 规模足够）；
- 权重可配置、可解释、持久化（见 evidence_retrieval_configs）。
"""

import re

from app.services.claims.normalizers import METRIC_DICTIONARY, NUMBER_UNIT_RE

# ---------------------------------------------------------------- 数值换算

# 单位 → 亿元 换算系数（人民币金额）
_UNIT_TO_YI = {
    "万亿元": 10000.0,
    "亿元": 1.0,
    "百万元": 0.01,
    "万元": 0.0001,
    "千元": 0.00001,
    "元": 1e-8,
}
# 无需换算的单位（直接按原值比较）
_DIRECT_UNITS = {"%", "PERCENT", "个百分点", "pp", "元/股"}

_VALUE_TOLERANCE = 0.005  # 相对容差 0.5%（Phase 23.7 恢复：收紧到 0.1% 导致负数+千分位回归）


def unit_to_yi(unit: str | None) -> float | None:
    """金额单位 → 亿元系数；百分比/每股类返回 None（直接比较）。"""
    if not unit:
        return None
    if unit in _DIRECT_UNITS:
        return None
    return _UNIT_TO_YI.get(unit)


def _clean_numbers(text: str) -> str:
    """数值预处理：去千分位逗号 + 括号负数转负号（(1,081,776) → -1081776）。"""
    out = re.sub(r"(?<=\d),(?=\d)", "", text)
    out = re.sub(r"\((\d[\d.]*)\)", r"-\1", out)
    return out


def iter_numbers(text: str):
    """遍历文本中所有 '数字+单位' 对，返回 (value, unit, currency, 亿元值)。

    先去除数字千分位逗号与括号负数，保证财务表格数值可解析。
    """
    cleaned = _clean_numbers(text)
    for m in NUMBER_UNIT_RE.finditer(cleaned):
        value = float(m.group(1))
        raw_unit = m.group(2)
        unit = next((norm for raw, norm in _UNIT_NORMS if raw == raw_unit), raw_unit)
        currency = "CNY" if re.search(r"[亿万]?元(?!\/股)|元/股", raw_unit) else None
        yi = value * unit_to_yi(unit) if unit_to_yi(unit) is not None else None
        yield value, unit, currency, yi


# NUMBER_UNIT_RE 中的单位与规范名映射（对齐 normalizers.UNIT_PATTERNS）
_UNIT_NORMS = [("%", "PERCENT"), ("个百分点", "pp")]


def values_compatible(claim_value: float, claim_unit: str | None, block_value: float, block_unit: str | None) -> bool:
    """数值匹配：统一换算到亿元后比较；百分比/每股类按原值比较。"""
    if claim_value is None:
        return False
    cy = unit_to_yi(claim_unit)
    by = unit_to_yi(block_unit)
    if cy is not None and by is not None:
        # 金额：换算到亿元比较（容差 0.5%）
        return abs(claim_value * cy - block_value * by) / max(abs(claim_value * cy), 1.0) <= _VALUE_TOLERANCE
    if cy is None and by is None and (claim_unit in _DIRECT_UNITS or block_unit in _DIRECT_UNITS):
        # 百分比/每股：原值比较
        return abs(claim_value - block_value) / max(abs(claim_value), 1.0) <= _VALUE_TOLERANCE
    return False


_COLUMN_UNIT_RE = re.compile(r"万亿元|亿元|百万元|万元|千元|元/股|元")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_PAGE_UNIT_RE = re.compile(r"单位\s*[:：]?\s*(人民币)?\s*(万亿元|亿元|百万元|万元|千元|元)")


def _page_unit_of(text: str) -> str | None:
    """从文本中识别页级单位声明（'单位：人民币千元'）。"""
    m = _PAGE_UNIT_RE.search(text)
    return m.group(2) if m else None


def _block_value_hits(block_text: str, claim_value: float, claim_unit: str | None) -> tuple[bool, str | None]:
    """块级数值匹配：成对单位 / 列头单位 / 页级单位三种布局。

    返回 (是否命中, match_reason)；match_reason 记录换算过程（可解释）。
    """
    if claim_value is None:
        return False, None
    # 1) 成对布局：数字+单位相邻
    for block_value, block_unit, _currency, _yi in iter_numbers(block_text):
        if values_compatible(claim_value, claim_unit, block_value, block_unit):
            yi_desc = f"（{_yi:g}亿）" if _yi is not None else ""
            return True, f"数值匹配: {block_value:g}{block_unit}≈{claim_value:g}{claim_unit or ''}{yi_desc}"
    # 2) 列头单位布局（单位在块内，如"营业收入（千元）456,451,731"）
    cleaned = _clean_numbers(block_text)
    m = _COLUMN_UNIT_RE.search(cleaned)
    if m:
        col_unit = m.group(0)
        for n in re.finditer(r"(?<![0-9])(\d+(?:\.\d+)?)(?![0-9])", cleaned):
            num = float(n.group(1))
            if _YEAR_RE.match(n.group(1)):
                continue
            if values_compatible(claim_value, claim_unit, num, col_unit):
                return True, f"列单位匹配: {num:g}{col_unit}≈{claim_value:g}{claim_unit or ''}"
    # 3) 页级单位声明（"单位：人民币千元" + 裸数字）
    page_unit = _page_unit_of(block_text)
    if page_unit:
        for n in re.finditer(r"(?<![0-9])(\d+(?:\.\d+)?)(?![0-9])", cleaned):
            num = float(n.group(1))
            if _YEAR_RE.match(n.group(1)):
                continue
            if values_compatible(claim_value, claim_unit, num, page_unit):
                return True, f"页单位匹配: {num:g}{page_unit}≈{claim_value:g}{claim_unit or ''}"
    return False, None


# ---------------------------------------------------------------- 指标别名

# 关键指标别名（严格：净利润 ≠ 归母净利润，不合并；Phase 4A.5 扩充）
# Phase 23.12：补充英文别名（Revenue/Sales/Net Income）与增长率别名（YoY/增长幅度），
# 仅用于含英文表头/双语财报的块匹配；中文财报正文不含这些词，不会误匹配。
_METRIC_ALIASES: dict[str, set[str]] = {
    "revenue": {"营业收入", "营业总收入", "主营业务收入", "营收", "收入", "Revenue", "Sales"},
    "total_operating_revenue": {"营业总收入", "营业收入", "主营业务收入", "营收", "收入", "Revenue", "Sales"},
    "net_profit_attributable": {"归属于上市公司股东的净利润", "归属于母公司股东的净利润", "归母净利润", "归母净利"},
    "net_profit": {"净利润", "Net Income"},
    "deducted_net_profit": {
        "扣除非经常性损益的净利润", "归属于上市公司股东的扣除非经常性损益的净利润",
        "扣非归母净利润", "扣非净利润", "扣非",
    },
    "operating_cash_flow": {
        "经营活动产生的现金流量净额", "经营活动现金流量净额", "经营活动现金流净额",
        "经营现金流净额", "经营现金流", "经营活动现金流", "现金流量净额",
    },
    "basic_eps": {"基本每股收益"},
    "eps": {"稀释每股收益", "每股收益"},
    "gross_margin": {"毛利率"},
    "roe": {"加权平均净资产收益率", "净资产收益率", "加权净资产收益率", "ROE"},
    "total_assets": {"总资产"},
    "net_assets": {"归属于上市公司股东的净资产", "净资产"},
    "yoy_growth_revenue": {"营业收入同比增长", "营业总收入同比增长", "收入同比增长", "营收同比增长", "YoY", "增长幅度"},
}
_ALIAS_BY_NAME: dict[str, str] = {}
for _code, _names in _METRIC_ALIASES.items():
    for _n in _names:
        _ALIAS_BY_NAME[_n] = _code


def _text_keywords(text: str, limit: int = 6) -> list[str]:
    """语义主张回退：从主张原文提取中文内容词（去停用词/连接词）作为候选检索词。"""
    if not text:
        return []
    stops = {
        "公司", "集团", "我们", "认为", "预计", "实现", "同比", "增长", "下降", "亿元", "报告",
        "根据", "以及", "可以", "进行", "相关", "主要", "其中", "高于", "超过", "达到", "以及",
        "持续", "深化", "重点", "整体", "水平", "程度", "范围",
    }
    # 中文连续段按连接词切分（和/与/及/的/在/以/为/或/已/、），得到有意义的短语
    runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    words: list[str] = []
    for run in runs:
        for seg in re.split(r"[和与及或以在为由的已、]", run):
            seg = seg.strip()
            # 剥离主语/前缀停用词（公司/集团/我们）后的剩余短语
            stripped = seg
            for prefix in ("公司", "集团", "我们", "本"):
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):]
                    break
            for cand in (stripped, seg):
                if len(cand) >= 2 and cand not in stops:
                    words.append(cand)
    seen, out = set(), []
    for w in sorted(words, key=len, reverse=True):
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= limit:
            break
    return out


def normalize_claim(claim: dict) -> dict:
    """主张输入归一化：兼容金标准（metric=代码/value/entity）与 API（metric_code/reported_value/entity_name）。

    输出引擎内部统一格式：entity_name / metric_code / metric(中文) / reported_value / unit / period。
    """
    out = dict(claim)
    out["entity_name"] = claim.get("entity_name") or claim.get("entity")
    if claim.get("reported_value") is None and claim.get("value") is not None:
        out["reported_value"] = claim["value"]
    metric = claim.get("metric")
    code = claim.get("metric_code")
    if code is None and metric and not re.search(r"[\u4e00-\u9fff]", str(metric)):
        code = metric  # metric 字段存的是代码（金标准格式）
    out["metric_code"] = code
    if metric and not re.search(r"[\u4e00-\u9fff]", str(metric)):
        chinese = next((m for _n, m, c in METRIC_DICTIONARY if c == metric), None)
        out["metric"] = chinese or metric
    return out


def metric_aliases(metric_code: str | None, metric: str | None) -> set[str]:
    """主张指标 → 匹配别名集合（含指标词典中的规范名与别名）。

    家族隔离：别名按 metric_code 精确匹配（归母净利润家族不含"净利润"，
    净利润家族不含"归母净利润"），防止跨指标误匹配。
    """
    # metric 字段可能直接存英文代码（金标准格式，如 total_operating_revenue），
    # 此时 metric_code 为空也要查表（Phase 23.9 修复：CLM-002 等英文代码 claim 的 metric_score）
    if metric_code is None and metric and not re.search(r"[\u4e00-\u9fff]", str(metric)):
        metric_code = str(metric)
    names: set[str] = set()
    if metric and re.search(r"[\u4e00-\u9fff]", str(metric)):
        names.add(metric)  # 仅收中文指标名（英文代码走 metric_code 路径）
    if metric_code:
        names |= _METRIC_ALIASES.get(metric_code, set())
        # yoy_growth_* / qoq_growth_* 前缀剥除 → 基础指标族（增长率主张的指标行匹配）
        base = str(metric_code)
        for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
            if base.startswith(pfx):
                base = base[len(pfx):]
                break
        if base != metric_code:
            names |= _METRIC_ALIASES.get(base, set())
            if base == "net_profit":
                names |= _METRIC_ALIASES.get("net_profit_attributable", set())
            if base == "revenue":
                names |= _METRIC_ALIASES.get("total_operating_revenue", set())
    # 指标词典兜底：仅按"相同 metric_code 家族"或"名称完全相等"补充
    for name, metric_name, code in METRIC_DICTIONARY:
        if metric_code and code == metric_code:
            names.add(name)
        elif metric and name == metric:
            names.add(name)
    return {n for n in names if n}


def metric_hits(block_text: str, aliases: set[str]) -> list[str]:
    """返回块中命中的指标别名（按名称长度降序，长名优先）。"""
    hits = [a for a in aliases if a and a in block_text]
    return sorted(hits, key=lambda a: -len(a))


def metric_value_adjacency(block_text: str, aliases: set[str]) -> float:
    """指标名后是否紧跟数字（财务数据行特征）：返回命中的指标名数（0 = 无邻接数字）。

    财务数据行：指标名后 N 字符内出现数字 → 数据行；叙述块：指标名后跟文字 → 非数据行。
    """
    if not aliases:
        return 0.0
    cleaned = _clean_numbers(block_text)
    count = 0
    for alias in sorted(aliases, key=lambda a: -len(a)):
        if not alias:
            continue
        idx = 0
        while True:
            pos = cleaned.find(alias, idx)
            if pos < 0:
                break
            tail = cleaned[pos + len(alias):pos + len(alias) + 40]
            if re.search(r"\d", tail):
                count += 1
                break
            idx = pos + 1
    return float(count)


# ---------------------------------------------------------------- 期间匹配

_PERIOD_PATTERNS = {
    "Q1": ["一季度", "第一季度", "2025年第一季度", "年初至报告期末", "1-3月", "1季度", "FY2025Q1", "2025Q1"],
    "H1": ["上半年", "半年度", "中期", "1-6月", "FY2025H1", "2025H1"],
    "FY": ["年度", "全年", "本报告期", "报告期内", "2025年", "FY2025", "2025年度", "本年度", "本年"],
    "2025": ["2025", "FY2025", "2025年度", "2025年"],
}
# 期间类型 → 优先财报类型（文档过滤用）
_PERIOD_TO_DOC_TYPE = {"Q1": "quarter", "H1": "half", "FY": "annual"}


def period_type_of(period: str | None) -> str | None:
    if not period:
        return None
    p = str(period).upper()
    if "Q" in p:
        return "Q1" if p.endswith("Q1") else None
    if "H" in p:
        return "H1" if p.endswith("H1") else None
    if "FY" in p or p.isdigit() or p == "2025":
        return "FY"
    return None


def period_matches(claim_period: str | None, block_text: str, doc_period: str | None = None) -> float:
    """期间匹配分（0/0.5/1）：块内期间关键词 + 文档期间。"""
    ptype = period_type_of(claim_period)
    if not ptype:
        return 0.0
    # 块级：命中期间关键词
    for kw in _PERIOD_PATTERNS[ptype]:
        if kw in block_text:
            return 1.0
    # 文档级：文档报告期间与主张一致（如 H1 主张检索半年报）
    if doc_period:
        dpt = period_type_of(str(doc_period))
        if dpt == ptype:
            return 0.5
    return 0.0


def document_priority(claim_period: str | None, doc_period: str | None) -> int:
    """文档优先级：主张期间类型与文档期间一致 → 0（最优先），否则 1。"""
    cp, dp = period_type_of(claim_period), period_type_of(str(doc_period) if doc_period else None)
    return 0 if cp and dp and cp == dp else 1


# ---------------------------------------------------------------- 主体与文本

# Phase 23.12：噪声块降权——纯页码（"1"、"12"）、表格分隔符（"---"、"|"、"===="）、
# 空白/标点块不得作为证据候选提升排名（table awareness 降低项）。
_NOISE_BLOCK_PENALTY = 0.25


def is_noise_block(text: str | None) -> bool:
    """判断文本块是否为噪声（页码/分隔符/纯标点），用于排名降权。"""
    if not text:
        return True
    t = text.strip()
    if not t:
        return True
    # 纯数字页码（1-4 位，可含空格）
    if re.fullmatch(r"\d{1,4}", t):
        return True
    # 分隔符 / 纯标点
    if re.fullmatch(r"[-—–|=_•·。，、；：()（）\s]+", t):
        return True
    # 中文页码（"第 12 页"）
    if re.fullmatch(r"第\s*\d{1,4}\s*页", t):
        return True
    return False


# Phase 23.12：公司实体别名表（全称 → 简称/股票代码/历史名称）。
# 财报正文多为简称或代码（如 "美的"、"000333"），扩展匹配面避免 entity 过滤漏召回。
_ENTITY_ALIASES: dict[str, set[str]] = {
    "美的集团": {"美的集团", "美的", "000333", "Midea", "美的电器"},
    "宜宾五粮液": {"宜宾五粮液", "五粮液", "000858", "Wuliangye"},
    "贵州茅台": {"贵州茅台", "茅台", "600519", "Kweichow Moutai"},
    "格力电器": {"格力电器", "格力", "000651", "Gree"},
    "中国平安": {"中国平安", "平安", "601318", "Ping An"},
}


def entity_matches(block_text: str, entity_name: str | None) -> float:
    if not entity_name:
        return 0.0
    name = entity_name.strip()
    if name in block_text:
        return 1.0
    # 实体别名：简称/股票代码/历史名称（Phase 23.12）
    aliases = _ENTITY_ALIASES.get(name, set())
    for a in aliases:
        if a and a != name and a in block_text:
            return 1.0
    # 简称兜底：取前 2-3 字（美的集团 → 美的；宜宾五粮液 → 五粮液）
    short = name[:2] if len(name) >= 2 else name
    return 1.0 if short in block_text and short not in ("公司", "集团") else 0.0


def _norm_text(s: str) -> str:
    if not s:
        return ""
    out = re.sub(r"\s+", "", s)
    return out.replace("，", ",").replace("。", ".").replace("、", ",").replace("（", "(").replace("）", ")").lower()


def text_similarity(claim_text: str, block_text: str) -> float:
    """文本相似度：主张文本字符被块文本覆盖的比例（字符集重叠 / 主张长度）。"""
    if not claim_text:
        return 0.0
    ct, bt = _norm_text(claim_text), _norm_text(block_text)
    if not bt:
        return 0.0
    covered = sum(1 for ch in ct if ch in bt)
    return round(covered / len(ct), 4)


# ---------------------------------------------------------------- 默认权重

# 基础五分量（Phase 4A 原始方案）+ 阶段2/3/4A.6 新增加成项（page/table/section/evidence_quality，可配置）
DEFAULT_WEIGHTS = {
    "metric": 0.35,
    "value": 0.30,
    "period": 0.15,
    "entity": 0.10,
    "text": 0.10,
    "page": 0.10,
    "table": 0.05,
    "section": 0.10,
    "evidence_quality": 0.10,
}
# 防止"相同数字、不同指标/期间"排名过高：指标未命中但数值命中的候选施加惩罚系数
_METRIC_MISS_VALUE_HIT_PENALTY = 0.5
# period 不兼容时降权但不归零：有期间主张但块+文档都未命中 → 倒扣 penalty（乘 0.3）
_PERIOD_MISS_PENALTY = 0.3


# 管理层讨论/经营分析章节关键词（无数字语义主张的 document_section_bonus）
SECTION_KEYWORDS = (
    "管理层讨论与分析", "经营情况讨论", "业务回顾", "董事会报告", "经营分析",
    "经营情况", "业务概要", "管理层分析", "报告期经营", "主要经营情况",
)


def section_matches(text: str) -> bool:
    """文本是否处于管理层讨论/经营分析章节（命中关键词）。"""
    return any(kw in text for kw in SECTION_KEYWORDS)


# ---------------------------------------------------------------- 证据类型（Phase 4A.6）

EVIDENCE_TYPE_PRIMARY = "PRIMARY_FINANCIAL_STATEMENT"  # 财务报表主表（利润表/资产负债表/现金流量表）
EVIDENCE_TYPE_NOTE = "FINANCIAL_NOTE"  # 财报附注
EVIDENCE_TYPE_SEGMENT = "BUSINESS_SEGMENT"  # 业务分部数据
EVIDENCE_TYPE_MD = "MANAGEMENT_DISCUSSION"  # 管理层讨论与分析
EVIDENCE_TYPE_NARRATIVE = "NARRATIVE_DISCLOSURE"  # 定性描述
EVIDENCE_TYPE_UNKNOWN = "UNKNOWN"

# 证据质量分值（用于 evidence_quality_score；权重可配置）
EVIDENCE_QUALITY = {
    EVIDENCE_TYPE_PRIMARY: 1.0,
    EVIDENCE_TYPE_NOTE: 0.8,
    EVIDENCE_TYPE_SEGMENT: 0.7,
    EVIDENCE_TYPE_MD: 0.6,
    EVIDENCE_TYPE_NARRATIVE: 0.4,
    EVIDENCE_TYPE_UNKNOWN: 0.3,
}

_STATEMENT_KEYWORDS = (
    "利润表", "合并利润表", "资产负债表", "合并资产负债表", "现金流量表", "合并现金流量表",
    "主要会计数据", "主要财务指标",
)
_NOTE_KEYWORDS = ("附注", "财务报表附注", "注释", "会计政策", "会计估计", "会计科目")
_SEGMENT_KEYWORDS = (
    "分部", "分行业", "分产品", "分地区", "主营业务分", "经营分部", "分业务", "营业收入构成",
)
# 财务报表主表的典型指标行（表格区域 + 指标 → PRIMARY）
_STATEMENT_METRICS = (
    "营业收入", "营业总收入", "营业成本", "净利润", "归属于上市公司股东的净利润",
    "总资产", "总负债", "经营活动产生的现金流量净额", "每股收益",
)


def classify_evidence_type(
    block_text: str,
    is_table_region: bool = False,
    is_management_section: bool = False,
) -> tuple[str, float, str]:
    """证据类型规则分类（优先级：主表 > 附注 > 分部 > 管理层讨论 > 定性 > 未知）。

    返回 (evidence_type, quality_score, rank_reason)。
    """
    text = block_text or ""
    # 1) 财务报表主表：财务表标题，或表格区域内含财务指标行（主要会计数据/利润表行）
    if any(kw in text for kw in _STATEMENT_KEYWORDS):
        return EVIDENCE_TYPE_PRIMARY, EVIDENCE_QUALITY[EVIDENCE_TYPE_PRIMARY], "命中财务报表关键词"
    if is_table_region and any(m in text for m in _STATEMENT_METRICS):
        return EVIDENCE_TYPE_PRIMARY, EVIDENCE_QUALITY[EVIDENCE_TYPE_PRIMARY], "表格区域内财务指标行"
    # 2) 财报附注
    if any(kw in text for kw in _NOTE_KEYWORDS):
        return EVIDENCE_TYPE_NOTE, EVIDENCE_QUALITY[EVIDENCE_TYPE_NOTE], "命中附注/注释关键词"
    # 3) 业务分部
    if any(kw in text for kw in _SEGMENT_KEYWORDS):
        return EVIDENCE_TYPE_SEGMENT, EVIDENCE_QUALITY[EVIDENCE_TYPE_SEGMENT], "命中分部经营关键词"
    # 4) 管理层讨论与经营分析
    if is_management_section or section_matches(text):
        return EVIDENCE_TYPE_MD, EVIDENCE_QUALITY[EVIDENCE_TYPE_MD], "管理层讨论/经营分析章节"
    # 5) 定性描述（有实质内容但无财务结构信号）
    if len(text.strip()) >= 8:
        return EVIDENCE_TYPE_NARRATIVE, EVIDENCE_QUALITY[EVIDENCE_TYPE_NARRATIVE], "定性描述"
    # 6) 未知
    return EVIDENCE_TYPE_UNKNOWN, EVIDENCE_QUALITY[EVIDENCE_TYPE_UNKNOWN], "无法识别证据类型"


def score_block(
    block_text: str,
    claim: dict,
    doc_period: str | None = None,
    weights: dict | None = None,
    section_bonus: float = 0.0,
    evidence_quality: float = 0.0,
) -> dict:
    """对单个文本块计算解释性分数。返回组件分 + 总分 + 命中项。

    权重让 metric/value 主导；period 不兼容时降权但不归零（rerank penalty 原则）。
    """
    # Phase 23.12：噪声块（页码/分隔符/纯标点）直接低分，不参与候选排名竞争
    if is_noise_block(block_text):
        return {
            "final_score": 0.0,
            "metric_score": 0.0,
            "value_score": 0.0,
            "period_score": 0.0,
            "entity_score": 0.0,
            "text_score": 0.0,
            "matched_terms": [],
            "matched_metrics": [],
            "value_match_reason": "noise_block",
            "is_noise_block": True,
        }
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))
    hits = metric_hits(block_text, aliases)
    metric_score = 1.0 if hits else 0.0

    value_score = 0.0
    value_match_reason = None
    claim_value = claim.get("reported_value")
    claim_unit = claim.get("unit")
    if claim_value is not None:
        hit, reason = _block_value_hits(block_text, claim_value, claim_unit)
        if hit:
            value_score = 1.0
            value_match_reason = reason

    period_score = period_matches(claim.get("period"), block_text, doc_period)
    entity_score = entity_matches(block_text, claim.get("entity_name"))
    text_score = text_similarity(claim.get("original_text", ""), block_text)

    final = (
        w["metric"] * metric_score
        + w["value"] * value_score
        + w["period"] * period_score
        + w["entity"] * entity_score
        + w["text"] * text_score
    )
    # metric+value 同时命中时给协同加成（财务数据行简洁命中 > 叙述块冗余命中）
    if metric_score == 1.0 and value_score == 1.0:
        final += w.get("metric_value_synergy", 0.45)
    # period 不兼容时降权但不归零：有期间主张但块+文档都未命中 → 倒扣 penalty
    claim_period = claim.get("period")
    if claim_period and period_score == 0.0:
        final *= _PERIOD_MISS_PENALTY
    # 无数字语义主张：管理层讨论/经营分析章节加分（document_section_bonus）
    if claim_value is None and section_bonus > 0:
        final += w.get("section", 0.10) * section_bonus
    # 证据质量加分（evidence_quality_score，Phase 4A.6；由 service 层在证据分类后注入）
    if evidence_quality > 0:
        final += w.get("evidence_quality", 0.10) * evidence_quality
    # 防错匹配：数值相同但指标未命中（如收入 vs 净利润同数）→ 总分惩罚
    if metric_score == 0 and value_score == 1:
        final *= _METRIC_MISS_VALUE_HIT_PENALTY

    return {
        "final_score": round(final, 4),
        "metric_score": metric_score,
        "value_score": value_score,
        "period_score": period_score,
        "entity_score": entity_score,
        "text_score": text_score,
        "matched_terms": hits[:5],
        "matched_metrics": hits,
        "value_match_reason": value_match_reason,
    }
