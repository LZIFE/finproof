"""RuleBasedCandidateExtractor：确定性规则候选提取。

职责：
- 读取文档文本块（paragraph），拆分为句子与子句
- 过滤无主张信号的句子（标题/过渡句/元信息/残缺短语）
- 指标词典匹配 + 数字/单位/币种/期间/同比环比提取
- 子句间指标继承（"同比增长12.11%" 继承前一子句的"营业收入"）
- 复合主张拆分（；并且|而且|同时 等连接词）
- 输出结构化主张候选（供 Schema 校验后入库）

规则模式只做候选减少与基础结构化，不负责语义完备性。
"""

import re
from dataclasses import dataclass, field

from app.services.claims.normalizers import (
    CAUSAL_WORDS,
    COMPARISON_WORDS,
    FORECAST_WORDS,
    OPINION_WORDS,
    TREND_WORDS,
    detect_claim_nature,
    detect_claim_type,
    detect_comparison,
    find_metric,
    grade_risk,
    parse_number,
    parse_percent,
    parse_period,
    requires_calculation,
)

SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;]")
# 子句拆分：逗号/顿号/分号 + 连接词（用于复合主张拆分与指标继承）
CLAUSE_SPLIT_RE = re.compile(r"[，,、；;]|并且|而且|同时|且")
META_RE = re.compile(r"^(>|[-*]\s|#|\s*\d+[\.、])")
YEAR_RE = re.compile(r"(20\d{2})")
PERIOD_KEYWORD_RE = re.compile(r"季度|上半年|下半年|年度|全年|H[12]|Q[1-4]")
MIN_CLAIM_LEN = 6
ENTITY_DEFAULT = "美的集团"
STOCK_DEFAULT = "000333"


@dataclass
class ClaimCandidate:
    source_block_id: int | None
    source_page_number: int
    source_text: str
    normalized_claim: str
    claim_type: str
    entity_name: str | None
    stock_code: str | None
    metric: str | None
    metric_code: str | None
    reported_value: float | None
    reported_value_text: str | None
    value_operator: str
    unit: str | None
    currency: str | None
    period: str | None
    period_type: str
    comparison_period: str | None
    comparison_type: str
    scope: str
    claim_nature: str
    risk_level: str
    risk_reason: str
    requires_calculation: bool
    requires_external_evidence: bool
    extraction_method: str = "RULE_BASED"
    confidence: float = 0.9
    # 父句上下文（子句归属）：拆分后的子主张保留父句信息用于评测与证据定位
    parent_block_id: int | None = None
    parent_sentence_text: str | None = None
    clause_index: int | None = None
    source_span_start: int | None = None
    source_span_end: int | None = None
    # 主张组：同一父句拆分出的兄弟主张共享 claim_group_id（前端折叠，评测/核验保留独立）
    claim_group_id: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class RuleExtractionResult:
    candidates: list[ClaimCandidate] = field(default_factory=list)
    candidate_sentence_count: int = 0
    input_block_count: int = 0


def _is_meta(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) < MIN_CLAIM_LEN:
        return True
    if META_RE.match(stripped):
        return True
    if stripped.startswith("**") and len(stripped) < 40:
        return True
    if any(w in stripped for w in ["本报告由AI辅助生成", "仅供演示", "不构成投资建议", "报告日期：", "分析师："]):
        return True
    return False


BUSINESS_FACT_SIGNAL = ["战略", "布局", "收购", "完成", "发布", "披露", "深化", "升级"]

# 高优先级保留信号：任一命中即保留（数字/指标在 _should_keep_clause 中单独判断）
STRONG_SIGNAL_WORDS = [
    "同比", "环比", "增长", "下降", "增速", "降幅", "占比", "过半",
    "超过", "低于", "达到", "高于", "突破", "增至", "降至",
    # 重大事件与披露
    "收购", "出售", "并购", "处罚", "诉讼", "仲裁", "退市", "处分", "回购", "分红", "发行",
    "发布", "披露", "完成", "签署", "中标", "获批",
    # 明确预测
    "预计", "有望", "预测", "目标", "展望", "将突破",
    # 明确因果（含可验证对象）
    "主要由", "主要系", "推动", "导致", "得益于", "核心引擎", "贡献",
]

# 弱信号：需要"可验证对象 + 变化/关系动词"才保留
WEAK_SIGNAL_WORDS = [
    "改善", "优化", "稳步", "加速", "向好", "回暖", "回升", "持续",
    "我们", "认为", "看好", "评级", "建议", "判断",
    "战略", "布局", "深化", "升级", "显现", "兑现",
]

VERIFIABLE_OBJECTS = [
    "公司", "集团", "业务", "收入", "利润", "现金流", "占比", "份额",
    "市场", "行业", "毛利率", "净利率", "费用", "负债", "资产", "每股收益",
    "海外", "国内", "机器人", "智能家居", "战略", "模式", "产品", "品牌",
]

CHANGE_VERBS = [
    "增长", "改善", "提升", "下降", "回落", "优化", "加速", "回暖", "回升",
    "向好", "成为", "占据", "推动", "贡献", "持续", "深化", "升级", "显现",
    "兑现", "突破", "扩大", "提升",
]

# 复合句拆分残片：以连接词/介词/引导短语开头、无法独立核验
FRAGMENT_PREFIX_RE = re.compile(
    r"^(但|以及|综合|主要系|展望|而|并且|其中|尤其|另外|同时|因此|所以|"
    r"在[^，。]{0,10}(领域|方面|环节)|从[^，。]{0,10}(看|来看))"
)


def _has_claim_signal(text: str, metric: tuple | None, number) -> bool:
    """保留决策：数字/指标/强信号任一命中即保留；残片先行过滤；弱信号需对象+动词。

    顺序：残片 > 数字/指标 > 强信号 > 弱信号。
    有指标无数字的纯形容词评价（无变化动词/强信号/观点词）默认过滤。
    """
    if FRAGMENT_PREFIX_RE.match(text.strip()):
        return False
    if metric or number:
        if number:
            return True
        # 有指标无数字：需变化动词、强信号或观点词（"现金流整体稳健"这类纯评价过滤）
        return (
            any(v in text for v in CHANGE_VERBS)
            or any(w in text for w in STRONG_SIGNAL_WORDS)
            or any(w in text for w in OPINION_WORDS)
        )
    if any(w in text for w in STRONG_SIGNAL_WORDS):
        return True
    if any(w in text for w in WEAK_SIGNAL_WORDS):
        has_object = any(obj in text for obj in VERIFIABLE_OBJECTS)
        has_verb = any(v in text for v in CHANGE_VERBS)
        return has_object and has_verb
    return False


def _split_sentences(text: str) -> list[str]:
    parts = SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _split_clauses(sentence: str) -> list[str]:
    parts = CLAUSE_SPLIT_RE.split(sentence)
    return [p.strip() for p in parts if p.strip()]


def _inherit_year(text: str, default_year: int | None = None) -> int | None:
    m = YEAR_RE.search(text)
    if m:
        return int(m.group(1))
    return default_year


def _build_normalized(metric: str | None, period: str | None, value, unit, comparison: str, nature: str) -> str:
    parts = []
    if metric:
        parts.append(metric)
    if period:
        parts.append(period)
    if value is not None:
        parts.append(str(value) + (unit or ""))
    if comparison in ("YEAR_OVER_YEAR", "QUARTER_OVER_QUARTER", "PERIOD_OVER_PERIOD"):
        parts.append("同比" if comparison == "YEAR_OVER_YEAR" else "环比" if comparison == "QUARTER_OVER_QUARTER" else "变化")
    if nature == "FORECAST":
        parts.append("（预测）")
    return "".join(parts) if parts else "（未识别）"


class RuleBasedCandidateExtractor:
    """从文档文本块提取主张候选（确定性规则）。"""

    def __init__(
        self,
        entity_name: str = ENTITY_DEFAULT,
        stock_code: str = STOCK_DEFAULT,
        report_year: int | None = None,
    ) -> None:
        self.entity_name = entity_name
        self.stock_code = stock_code
        # 报告基准年：无显式年份的子句继承（演示报告为 2025）
        self.report_year = report_year

    def extract(self, blocks: list) -> RuleExtractionResult:
        result = RuleExtractionResult(input_block_count=len(blocks))
        for block in blocks:
            if getattr(block, "block_type", "paragraph") == "heading":
                continue
            text = (block.text or "").strip()
            if _is_meta(text):
                continue
            last_metric: tuple | None = None
            sentence_seq = 0
            for sentence in _split_sentences(text):
                result.candidate_sentence_count += 1
                sentence_seq += 1
                group_id = f"blk{getattr(block, 'id', 0)}-s{sentence_seq}"
                year = _inherit_year(sentence, self.report_year)
                # 句子级期间：向无显式期间的子句传播（如"2025年上半年，……"）
                sentence_period = parse_period(sentence, year)
                for ci, clause in enumerate(_split_clauses(sentence)):
                    # 子句在父句内的字符跨度（source_span，供评测与证据定位）
                    clause_start = sentence.find(clause)
                    span = (clause_start, clause_start + len(clause)) if clause_start >= 0 else (None, None)
                    candidate = self._build_candidate(
                        clause, block, year, last_metric, sentence_period,
                        parent_block_id=getattr(block, "id", None),
                        parent_sentence_text=sentence,
                        clause_index=ci,
                        source_span_start=span[0],
                        source_span_end=span[1],
                        claim_group_id=group_id,
                    )
                    if candidate is None:
                        continue
                    if candidate.metric:
                        last_metric = (candidate.metric, candidate.metric_code)
                    result.candidates.append(candidate)
        return result

    def _build_candidate(
        self,
        clause: str,
        block,
        year: int | None,
        last_metric: tuple | None,
        sentence_period=None,
        parent_block_id: int | None = None,
        parent_sentence_text: str | None = None,
        clause_index: int | None = None,
        source_span_start: int | None = None,
        source_span_end: int | None = None,
        claim_group_id: str | None = None,
    ) -> ClaimCandidate | None:
        if len(clause) < MIN_CLAIM_LEN:
            return None
        metric = find_metric(clause)
        number = parse_number(clause)
        if not _has_claim_signal(clause, metric, number):
            return None

        metric_name, metric_code = metric if metric else (None, None)
        if metric is None and number and last_metric:
            # 指标继承：增长率子句沿用前一子句指标
            metric_name, metric_code = last_metric

        # 期间：子句自带期间关键词优先，否则继承句子级期间
        if PERIOD_KEYWORD_RE.search(clause):
            parsed_period = parse_period(clause, year)
        elif sentence_period is not None and sentence_period.period:
            parsed_period = sentence_period
        else:
            parsed_period = None
        period = parsed_period.period if parsed_period else None
        period_type = parsed_period.period_type if parsed_period else "UNSPECIFIED"
        comparison_type, comparison_period = detect_comparison(
            clause, period, parsed_period.year if parsed_period else year
        )
        # 通用"同比增长"子句 + 前文指标 → 生成 yoy_<指标> 代码（对齐金标准）
        if metric_code == "growth_rate" and last_metric and comparison_type == "YEAR_OVER_YEAR":
            base = last_metric[1]
            if base == "net_profit_attributable":
                base = "net_profit"
            metric_name = last_metric[0]
            metric_code = f"yoy_growth_{base}"
        # 增长率无归属（通用"同比增长"且无前文指标可继承）不得直接入库
        if metric_code == "growth_rate" and not last_metric:
            return None

        value = number.value if number else None
        unit = number.unit if number else None
        currency = number.currency if number else None
        if value is None:
            value = parse_percent(clause)

        claim_type = detect_claim_type(clause, number, metric_code, comparison_type)
        if claim_type == "ABSOLUTE_FINANCIAL_VALUE" and comparison_type != "NONE" and value is not None:
            claim_type = "GROWTH_RATE"
        nature = detect_claim_nature(clause, claim_type)
        risk_level, risk_reason = grade_risk(clause, claim_type, metric_code)
        calc = requires_calculation(claim_type, clause)
        # 语义/比较/因果类主张需要外部证据
        needs_evidence = claim_type in {
            "BUSINESS_FACT", "CAUSAL_CLAIM", "COMPARISON", "TREND", "OPINION",
        } or metric_code in {"overseas_revenue", "overseas_business", "robot_business"}

        normalized = _build_normalized(
            metric_name, period, value, unit, comparison_type, nature
        )
        if metric_name is None and normalized == "（未识别）":
            return None

        return ClaimCandidate(
            source_block_id=getattr(block, "id", None),
            source_page_number=getattr(block, "page_number", 1) or 1,
            source_text=clause,
            normalized_claim=normalized,
            claim_type=claim_type,
            entity_name=self.entity_name,
            stock_code=self.stock_code,
            metric=metric_name,
            metric_code=metric_code,
            reported_value=value,
            reported_value_text=number.value_text if number else None,
            value_operator=number.operator if number else "NOT_APPLICABLE",
            unit=unit,
            currency=currency,
            period=period,
            period_type=period_type,
            comparison_period=comparison_period,
            comparison_type=comparison_type,
            scope="CONSOLIDATED",
            claim_nature=nature,
            risk_level=risk_level,
            risk_reason=risk_reason,
            requires_calculation=calc,
            requires_external_evidence=needs_evidence,
            confidence=0.9 if value is not None else 0.7,
            parent_block_id=parent_block_id,
            parent_sentence_text=parent_sentence_text,
            clause_index=clause_index,
            source_span_start=source_span_start,
            source_span_end=source_span_end,
            claim_group_id=claim_group_id,
        )
