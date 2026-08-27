"""Phase 3 主张提取枚举定义（与 docs/finproof_execution_plan.md 与任务书对齐）。"""

from enum import Enum


class ClaimType(str, Enum):
    ABSOLUTE_FINANCIAL_VALUE = "ABSOLUTE_FINANCIAL_VALUE"
    GROWTH_RATE = "GROWTH_RATE"
    FINANCIAL_RATIO = "FINANCIAL_RATIO"
    BUSINESS_SHARE = "BUSINESS_SHARE"
    COMPARISON = "COMPARISON"
    TREND = "TREND"
    BUSINESS_FACT = "BUSINESS_FACT"
    CAUSAL_CLAIM = "CAUSAL_CLAIM"
    OPINION = "OPINION"
    FORECAST = "FORECAST"
    OTHER_VERIFIABLE = "OTHER_VERIFIABLE"


class ClaimNature(str, Enum):
    FACT = "FACT"
    CALCULATED_FACT = "CALCULATED_FACT"
    CAUSAL_INTERPRETATION = "CAUSAL_INTERPRETATION"
    COMPARATIVE_JUDGMENT = "COMPARATIVE_JUDGMENT"
    OPINION = "OPINION"
    FORECAST = "FORECAST"
    ASSUMPTION = "ASSUMPTION"


class ValueOperator(str, Enum):
    EQUAL = "EQUAL"
    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    APPROXIMATELY = "APPROXIMATELY"
    RANGE = "RANGE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PeriodType(str, Enum):
    DATE = "DATE"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    HALF_YEAR = "HALF_YEAR"
    YEAR = "YEAR"
    YEAR_TO_DATE = "YEAR_TO_DATE"
    MULTI_YEAR = "MULTI_YEAR"
    FUTURE_PERIOD = "FUTURE_PERIOD"
    UNSPECIFIED = "UNSPECIFIED"


class ComparisonType(str, Enum):
    YEAR_OVER_YEAR = "YEAR_OVER_YEAR"
    QUARTER_OVER_QUARTER = "QUARTER_OVER_QUARTER"
    PERIOD_OVER_PERIOD = "PERIOD_OVER_PERIOD"
    PEER_COMPARISON = "PEER_COMPARISON"
    TARGET_COMPARISON = "TARGET_COMPARISON"
    NONE = "NONE"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"


class ExtractionRunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExtractionMode(str, Enum):
    MOCK = "mock"
    RULES = "rules"
    LLM = "llm"
    HYBRID = "hybrid"


class SourceLevel(str, Enum):
    """证据来源可信度分级（回答"这条证据凭什么硬"）。

    等级从高到低：
    - OFFICIAL_DISCLOSURE: 交易所/证监会官方披露（年报、公告、招股书）
    - REGULATORY_DATA: 监管或权威机构数据（统计局、交易所、行业协会）
    - THIRD_PARTY_REPORT: 第三方研究报告（咨询公司、券商研报引用）
    - MEDIA_REPORT: 媒体报道（新闻、财经媒体）
    - CHANNEL_CHECK: 渠道调研/产业链反馈（"据经销商""据调研"）
    - FORECAST: 预测性陈述（"预计""有望""我们认为"——不是已发生事实）
    - NO_SOURCE: 无明确来源
    """

    OFFICIAL_DISCLOSURE = "OFFICIAL_DISCLOSURE"
    REGULATORY_DATA = "REGULATORY_DATA"
    THIRD_PARTY_REPORT = "THIRD_PARTY_REPORT"
    MEDIA_REPORT = "MEDIA_REPORT"
    CHANNEL_CHECK = "CHANNEL_CHECK"
    FORECAST = "FORECAST"
    NO_SOURCE = "NO_SOURCE"


# 来源等级中文标签（前端展示用）
SOURCE_LEVEL_LABELS: dict[str, str] = {
    SourceLevel.OFFICIAL_DISCLOSURE: "官方披露",
    SourceLevel.REGULATORY_DATA: "监管数据",
    SourceLevel.THIRD_PARTY_REPORT: "第三方报告",
    SourceLevel.MEDIA_REPORT: "媒体报道",
    SourceLevel.CHANNEL_CHECK: "渠道调研",
    SourceLevel.FORECAST: "预测陈述",
    SourceLevel.NO_SOURCE: "无明确来源",
}

# 来源等级可信度分值（0-1，越高越硬）
SOURCE_LEVEL_SCORES: dict[str, float] = {
    SourceLevel.OFFICIAL_DISCLOSURE: 1.0,
    SourceLevel.REGULATORY_DATA: 0.9,
    SourceLevel.THIRD_PARTY_REPORT: 0.6,
    SourceLevel.MEDIA_REPORT: 0.4,
    SourceLevel.CHANNEL_CHECK: 0.3,
    SourceLevel.FORECAST: 0.2,
    SourceLevel.NO_SOURCE: 0.0,
}
