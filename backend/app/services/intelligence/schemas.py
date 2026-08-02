"""Investment Intelligence Schemas（Phase 8）。

Evidence First 原则：每条 Company Fact 必须包含 source / evidence / timestamp /
confidence，不凭空捏造。

数据结构：
- CompanyFact          外部事实（公司基本面/财务/市场/产品/竞争）
- ConflictFinding      Investment Claim vs External Fact 冲突/支持结论
- IntelligenceReport   投资情报报告（Company Profile + Verified Facts +
                        Conflicts + Risk Findings + Evidence Chain）

设计约束（任务书）：
- 不开发自动投资建议；
- 不进行股票推荐；
- 不替代投资经理决策。
"""

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Fact 来源类型（Evidence First：每条 Fact 必须可追溯）
# ---------------------------------------------------------------------------
FACT_SOURCE_FINANCIAL_REPORT = "FINANCIAL_REPORT"  # 财报
FACT_SOURCE_ANNOUNCEMENT = "ANNOUNCEMENT"  # 公告
FACT_SOURCE_NEWS = "NEWS"  # 新闻
FACT_SOURCE_OFFICIAL_SITE = "OFFICIAL_SITE"  # 官网

FACT_SOURCES = {
    FACT_SOURCE_FINANCIAL_REPORT,
    FACT_SOURCE_ANNOUNCEMENT,
    FACT_SOURCE_NEWS,
    FACT_SOURCE_OFFICIAL_SITE,
}

# ---------------------------------------------------------------------------
# Fact 维度（用于 Company Profile 与冲突比对）
# ---------------------------------------------------------------------------
FACT_DIM_COMPANY = "COMPANY"  # 公司名称/基本信息
FACT_DIM_BUSINESS = "BUSINESS"  # 业务领域
FACT_DIM_FINANCIAL = "FINANCIAL"  # 财务指标
FACT_DIM_MARKET = "MARKET"  # 市场扩张
FACT_DIM_PRODUCT = "PRODUCT"  # 产品信息
FACT_DIM_COMPETITION = "COMPETITION"  # 竞争信息

FACT_DIMENSIONS = {
    FACT_DIM_COMPANY,
    FACT_DIM_BUSINESS,
    FACT_DIM_FINANCIAL,
    FACT_DIM_MARKET,
    FACT_DIM_PRODUCT,
    FACT_DIM_COMPETITION,
}

# ---------------------------------------------------------------------------
# Conflict 类型（任务书 §3：发现四类问题）
# ---------------------------------------------------------------------------
CONFLICT_FINANCIAL_DATA = "FINANCIAL_DATA_CONFLICT"  # 财务数据冲突
CONFLICT_BUSINESS_DESC = "BUSINESS_DESC_CONFLICT"  # 业务描述冲突
CONFLICT_GROWTH_LOGIC = "GROWTH_LOGIC_INSUFFICIENT"  # 增长逻辑不足
CONFLICT_COMPETITIVE_EVIDENCE = "COMPETITIVE_EVIDENCE_MISSING"  # 竞争优势缺证据
CONFLICT_NO_OPPOSITION = "NO_OPPOSITION"  # 外部事实支持/不冲突

CONFLICT_TYPES = {
    CONFLICT_FINANCIAL_DATA,
    CONFLICT_BUSINESS_DESC,
    CONFLICT_GROWTH_LOGIC,
    CONFLICT_COMPETITIVE_EVIDENCE,
    CONFLICT_NO_OPPOSITION,
}

# 冲突类型 → 风险类型映射（与 Phase 7 风险分类保持一致口径）
CONFLICT_RISK_TYPE = {
    CONFLICT_FINANCIAL_DATA: "FINANCIAL_ERROR",
    CONFLICT_BUSINESS_DESC: "SEMANTIC_RISK",
    CONFLICT_GROWTH_LOGIC: "EVIDENCE_RISK",
    CONFLICT_COMPETITIVE_EVIDENCE: "EVIDENCE_RISK",
    CONFLICT_NO_OPPOSITION: "NONE",
}

# 冲突类型 → 默认风险分数（NO_OPPOSITION 为 0；其余按严重度阶梯）
CONFLICT_BASE_SCORE = {
    CONFLICT_FINANCIAL_DATA: 85.0,
    CONFLICT_BUSINESS_DESC: 70.0,
    CONFLICT_GROWTH_LOGIC: 60.0,
    CONFLICT_COMPETITIVE_EVIDENCE: 55.0,
    CONFLICT_NO_OPPOSITION: 0.0,
}


# ---------------------------------------------------------------------------
# Company Fact：外部事实（Evidence First）
# ---------------------------------------------------------------------------
@dataclass
class CompanyFact:
    """外部事实：来源于财报/公告/新闻/官网的可追溯事实。

    Evidence First：source / evidence / timestamp / confidence 必填，
    无证据不记录事实。
    """

    fact_id: str  # FACT-XXXXX
    dimension: str  # COMPANY/BUSINESS/FINANCIAL/MARKET/PRODUCT/COMPETITION
    subject: str  # 主体（公司名/业务线/产品/竞争对手）
    statement: str  # 事实陈述
    value: Any = None  # 数值/指标（可选，便于数字类比对）
    unit: str = ""  # 单位（亿元 / % / ...）
    period: str = ""  # 口径期间（2025FY / 2025Q1 / ...）

    # Evidence First 字段
    source: str = ""  # FINANCIAL_REPORT / ANNOUNCEMENT / NEWS / OFFICIAL_SITE
    source_label: str = ""  # 人类可读来源名（如"美的集团 2025 年年度报告"）
    evidence: str = ""  # 原始证据文本/摘要
    page_number: int | None = None  # 财报页码（可选）
    timestamp: str = ""  # 事实发生/披露时间 ISO8601
    confidence: float = 0.0  # 0-1，证据可信度

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "dimension": self.dimension,
            "subject": self.subject,
            "statement": self.statement,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
            "source": self.source,
            "source_label": self.source_label,
            "evidence": self.evidence,
            "page_number": self.page_number,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Investment Claim：投资观点（待比对）
# ---------------------------------------------------------------------------
@dataclass
class InvestmentClaim:
    """投资观点：投资材料中提出的主张，需与外部事实交叉验证。"""

    claim_id: str  # INV-XXXXX
    claim: str  # 观点原文
    dimension: str = FACT_DIM_BUSINESS  # 与 Fact 维度对齐，便于配对
    value: Any = None  # 主张涉及的数值（可选）
    unit: str = ""
    period: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "claim": self.claim,
            "dimension": self.dimension,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
        }


# ---------------------------------------------------------------------------
# Conflict Finding：Claim vs Fact 比对结论
# ---------------------------------------------------------------------------
@dataclass
class ConflictFinding:
    """投资观点与外部事实的比对结论。

    结构遵循任务书 §3：
    claim / fact / difference / risk_type / risk_score
    """

    finding_id: str  # CFLT-XXXXX
    claim_id: str
    fact_id: str
    claim: str  # 投资观点原文
    fact: str  # 外部事实陈述
    conflict_type: str  # CONFLICT_TYPES
    difference: str  # 差异描述（人类可读）
    risk_type: str = ""  # 与 Phase 7 风险分类口径一致
    risk_score: float = 0.0  # 0-100
    risk_level: str = "LOW"  # LOW/MEDIUM/HIGH
    evidence_trace: list[dict] = field(default_factory=list)  # 证据链

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "claim_id": self.claim_id,
            "fact_id": self.fact_id,
            "claim": self.claim,
            "fact": self.fact,
            "conflict_type": self.conflict_type,
            "difference": self.difference,
            "risk_type": self.risk_type,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "evidence_trace": self.evidence_trace,
        }


# ---------------------------------------------------------------------------
# Intelligence Report：投资情报报告
# ---------------------------------------------------------------------------
@dataclass
class CompanyProfile:
    """公司画像：从 Facts 聚合的基本面视图。"""

    company: str = ""
    stock_code: str = ""
    business_fields: list[str] = field(default_factory=list)
    key_financials: list[dict] = field(default_factory=list)
    market_coverage: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    competitors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "stock_code": self.stock_code,
            "business_fields": self.business_fields,
            "key_financials": self.key_financials,
            "market_coverage": self.market_coverage,
            "products": self.products,
            "competitors": self.competitors,
        }


@dataclass
class RiskFinding:
    """风险点：从冲突结论聚合的可读风险项。"""

    finding_id: str
    claim_id: str
    risk_type: str
    risk_score: float
    risk_level: str
    summary: str
    conflict_type: str = ""

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "claim_id": self.claim_id,
            "risk_type": self.risk_type,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "summary": self.summary,
            "conflict_type": self.conflict_type,
        }


@dataclass
class IntelligenceReport:
    """投资情报报告（Phase 8 主输出）。

    组成：Company Profile / Verified Facts / Conflicts /
          Risk Findings / Evidence Chain
    """

    id: int | None = None
    document_id: int = 0
    company: str = ""
    stock_code: str = ""
    report_period: str = ""

    company_profile: CompanyProfile = field(default_factory=CompanyProfile)
    verified_facts: list[CompanyFact] = field(default_factory=list)
    conflicts: list[ConflictFinding] = field(default_factory=list)
    risk_findings: list[RiskFinding] = field(default_factory=list)
    evidence_chain: list[dict] = field(default_factory=list)

    # 汇总指标
    overall_risk_score: float = 0.0
    overall_risk_level: str = "LOW"
    conflict_count: int = 0
    support_count: int = 0

    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "company": self.company,
            "stock_code": self.stock_code,
            "report_period": self.report_period,
            "company_profile": self.company_profile.to_dict(),
            "verified_facts": [f.to_dict() for f in self.verified_facts],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "risk_findings": [r.to_dict() for r in self.risk_findings],
            "evidence_chain": self.evidence_chain,
            "overall_risk_score": round(self.overall_risk_score, 1),
            "overall_risk_level": self.overall_risk_level,
            "conflict_count": self.conflict_count,
            "support_count": self.support_count,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# 风险分数 → Level（与 Phase 6/7 阈值一致：LOW<30 / MEDIUM≤65 / HIGH>65）
# ---------------------------------------------------------------------------
def risk_level_of(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"
