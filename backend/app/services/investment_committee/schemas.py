"""Investment Committee Multi-Agent Schemas（Phase 9）。

多 Agent 投资审核系统：模拟真实投资委员会流程。

Agents：
- Supervisor Agent   任务拆解 → 调用 Research/Risk/Compliance → 汇总
- Research Agent     Company Overview / Business Analysis / Financial Summary
                     （来源必须来自已有 Evidence）
- Risk Agent         调用已有 Verification / Risk Engine / Intelligence
                     → Risk Findings / Conflict Findings / Risk Score
- Compliance Agent   检查投资材料是否存在：
                       - Unsupported Claim
                       - Overstatement
                       - Missing Evidence
                       - Forecast Presented As Fact

输出：Investment Committee Report
  Executive Summary / Research Findings / Risk Findings /
  Compliance Findings / Evidence Chain / Human Review Items

设计约束（任务书）：
- 不输出投资建议；
- 不自动决定买卖；
- 保持 Human-in-the-loop；
- 不修改已有核心模块（Verification / Risk / Intelligence / Audit / Investment Memo）。
"""

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Agent 标识
# ---------------------------------------------------------------------------
AGENT_SUPERVISOR = "supervisor"
AGENT_RESEARCH = "research"
AGENT_RISK = "risk"
AGENT_COMPLIANCE = "compliance"

AGENTS = (AGENT_SUPERVISOR, AGENT_RESEARCH, AGENT_RISK, AGENT_COMPLIANCE)

AGENT_LABELS = {
    AGENT_SUPERVISOR: "Supervisor Agent（任务拆解与汇总）",
    AGENT_RESEARCH: "Research Agent（公司/业务/财务调研）",
    AGENT_RISK: "Risk Agent（核验/风险/情报）",
    AGENT_COMPLIANCE: "Compliance Agent（合规检查）",
}

# Agent 执行状态
AGENT_STATUS_PENDING = "PENDING"
AGENT_STATUS_RUNNING = "RUNNING"
AGENT_STATUS_DONE = "DONE"
AGENT_STATUS_FAILED = "FAILED"

AGENT_STATUSES = {
    AGENT_STATUS_PENDING,
    AGENT_STATUS_RUNNING,
    AGENT_STATUS_DONE,
    AGENT_STATUS_FAILED,
}

# ---------------------------------------------------------------------------
# Compliance 检查类型（任务书 §5）
# ---------------------------------------------------------------------------
COMPLIANCE_UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"  # Unsupported Claim
COMPLIANCE_OVERSTATEMENT = "OVERSTATEMENT"  # Overstatement
COMPLIANCE_MISSING_EVIDENCE = "MISSING_EVIDENCE"  # Missing Evidence
COMPLIANCE_FORECAST_AS_FACT = "FORECAST_AS_FACT"  # Forecast Presented As Fact

COMPLIANCE_TYPES = {
    COMPLIANCE_UNSUPPORTED_CLAIM,
    COMPLIANCE_OVERSTATEMENT,
    COMPLIANCE_MISSING_EVIDENCE,
    COMPLIANCE_FORECAST_AS_FACT,
}

COMPLIANCE_LABELS = {
    COMPLIANCE_UNSUPPORTED_CLAIM: "无证据支持的主张",
    COMPLIANCE_OVERSTATEMENT: "夸大表达",
    COMPLIANCE_MISSING_EVIDENCE: "证据缺失",
    COMPLIANCE_FORECAST_AS_FACT: "预测被描述为事实",
}

# Compliance 严重度（任务书 §5：四类合规问题）
COMPLIANCE_SEVERITY_HIGH = "HIGH"
COMPLIANCE_SEVERITY_MEDIUM = "MEDIUM"
COMPLIANCE_SEVERITY_LOW = "LOW"

# 默认合规风险分（按严重度）
COMPLIANCE_DEFAULT_SCORE = {
    COMPLIANCE_UNSUPPORTED_CLAIM: 70.0,
    COMPLIANCE_OVERSTATEMENT: 65.0,
    COMPLIANCE_MISSING_EVIDENCE: 75.0,
    COMPLIANCE_FORECAST_AS_FACT: 60.0,
}


# ---------------------------------------------------------------------------
# AgentTask / AgentResult：Supervisor 分发与回收的载荷
# ---------------------------------------------------------------------------
@dataclass
class AgentTask:
    """Supervisor 分派给子 Agent 的任务。

    Evidence First：所有 Agent 的结论必须基于已有 Evidence，
    不引入未核验的信息。
    """

    agent: str  # research / risk / compliance
    document_id: int  # 投资材料文档 ID
    audit_id: int | None = None  # 已有审计任务 ID（Risk Agent 必填）
    intelligence_report_id: int | None = None  # 已有情报报告 ID（Risk Agent 可选）
    params: dict = field(default_factory=dict)  # 任务特定参数

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "document_id": self.document_id,
            "audit_id": self.audit_id,
            "intelligence_report_id": self.intelligence_report_id,
            "params": self.params,
        }


@dataclass
class AgentResult:
    """子 Agent 执行结果。

    status: PENDING / RUNNING / DONE / FAILED
    findings: 结构化结论（dict 列表，由各 Agent 定义）
    tools_called: 调用的已有模块（可追溯）
    evidence_refs: 引用的证据 ID 列表（Evidence First）
    """

    agent: str
    status: str = AGENT_STATUS_DONE
    findings: list[dict] = field(default_factory=list)
    summary: str = ""
    tools_called: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "status": self.status,
            "findings": self.findings,
            "summary": self.summary,
            "tools_called": self.tools_called,
            "evidence_refs": self.evidence_refs,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Research Agent 输出（任务书 §3）
# ---------------------------------------------------------------------------
@dataclass
class CompanyOverview:
    """公司概况：来自已有 Evidence 的基本面视图。"""

    company: str = ""
    stock_code: str = ""
    report_period: str = ""
    business_fields: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    market_coverage: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "stock_code": self.stock_code,
            "report_period": self.report_period,
            "business_fields": self.business_fields,
            "products": self.products,
            "market_coverage": self.market_coverage,
        }


@dataclass
class BusinessAnalysis:
    """业务分析：基于 Evidence 的业务结构描述。"""

    segments: list[dict] = field(default_factory=list)  # 业务分部
    growth_drivers: list[str] = field(default_factory=list)  # 增长驱动
    risks: list[str] = field(default_factory=list)  # 业务风险点
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "segments": self.segments,
            "growth_drivers": self.growth_drivers,
            "risks": self.risks,
            "evidence_refs": self.evidence_refs,
        }


@dataclass
class FinancialSummary:
    """财务摘要：来自 Evidence 的关键财务指标。"""

    key_metrics: list[dict] = field(default_factory=list)  # 指标/值/单位/期间
    revenue_trend: list[dict] = field(default_factory=list)  # 营收趋势
    profit_trend: list[dict] = field(default_factory=list)  # 利润趋势
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key_metrics": self.key_metrics,
            "revenue_trend": self.revenue_trend,
            "profit_trend": self.profit_trend,
            "evidence_refs": self.evidence_refs,
        }


@dataclass
class ResearchFindings:
    """Research Agent 输出。"""

    company_overview: CompanyOverview = field(default_factory=CompanyOverview)
    business_analysis: BusinessAnalysis = field(default_factory=BusinessAnalysis)
    financial_summary: FinancialSummary = field(default_factory=FinancialSummary)
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "company_overview": self.company_overview.to_dict(),
            "business_analysis": self.business_analysis.to_dict(),
            "financial_summary": self.financial_summary.to_dict(),
            "evidence_refs": self.evidence_refs,
        }


# ---------------------------------------------------------------------------
# Risk Agent 输出（任务书 §4）
# ---------------------------------------------------------------------------
@dataclass
class RiskFindings:
    """Risk Agent 输出：调用 Verification + Risk Engine + Intelligence。"""

    risk_score: float = 0.0  # 整体风险评分 0-100
    risk_level: str = "LOW"  # LOW/MEDIUM/HIGH
    risk_findings: list[dict] = field(default_factory=list)  # 来自 Risk Engine
    conflict_findings: list[dict] = field(default_factory=list)  # 来自 Intelligence
    verification_summary: dict = field(default_factory=dict)  # 来自 Verification
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "risk_findings": self.risk_findings,
            "conflict_findings": self.conflict_findings,
            "verification_summary": self.verification_summary,
            "evidence_refs": self.evidence_refs,
        }


# ---------------------------------------------------------------------------
# Compliance Agent 输出（任务书 §5）
# ---------------------------------------------------------------------------
@dataclass
class ComplianceFinding:
    """合规发现：投资材料中的合规问题。"""

    finding_id: str  # COMP-XXXXX
    check_type: str  # COMPLIANCE_TYPES
    claim_id: str = ""  # 关联的主张 ID
    claim_text: str = ""  # 主张原文
    description: str = ""  # 问题描述
    severity: str = COMPLIANCE_SEVERITY_MEDIUM  # HIGH/MEDIUM/LOW
    risk_score: float = 0.0  # 0-100
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "check_type": self.check_type,
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "description": self.description,
            "severity": self.severity,
            "risk_score": round(self.risk_score, 1),
            "evidence_refs": self.evidence_refs,
        }


@dataclass
class ComplianceFindings:
    """Compliance Agent 输出。"""

    findings: list[ComplianceFinding] = field(default_factory=list)
    unsupported_claim_count: int = 0
    overstatement_count: int = 0
    missing_evidence_count: int = 0
    forecast_as_fact_count: int = 0
    overall_compliance_score: float = 0.0  # 0-100，越高越不合规

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "unsupported_claim_count": self.unsupported_claim_count,
            "overstatement_count": self.overstatement_count,
            "missing_evidence_count": self.missing_evidence_count,
            "forecast_as_fact_count": self.forecast_as_fact_count,
            "overall_compliance_score": round(self.overall_compliance_score, 1),
        }


# ---------------------------------------------------------------------------
# Human Review Item（保持 Human-in-the-loop）
# ---------------------------------------------------------------------------
@dataclass
class HumanReviewItem:
    """人工审核项：Agent 提请投资委员会/投资经理审核的事项。"""

    item_id: str  # REV-XXXXX
    agent: str  # 提请的 Agent
    review_type: str  # RISK / COMPLIANCE / RESEARCH_GAP
    claim_id: str = ""
    description: str = ""
    risk_score: float = 0.0
    risk_level: str = "LOW"
    review_status: str = "NEED_REVIEW"  # NEED_REVIEW / APPROVED / REJECTED
    note: str = ""
    reviewer: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "agent": self.agent,
            "review_type": self.review_type,
            "claim_id": self.claim_id,
            "description": self.description,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "review_status": self.review_status,
            "note": self.note,
            "reviewer": self.reviewer,
        }


# ---------------------------------------------------------------------------
# Investment Committee Report（任务书 §6）
# ---------------------------------------------------------------------------
@dataclass
class ExecutiveSummary:
    """执行摘要：Supervisor 汇总三 Agent 结论。"""

    company: str = ""
    stock_code: str = ""
    report_period: str = ""
    overall_risk_score: float = 0.0
    overall_risk_level: str = "LOW"
    overall_compliance_score: float = 0.0
    research_summary: str = ""
    risk_summary: str = ""
    compliance_summary: str = ""
    key_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "stock_code": self.stock_code,
            "report_period": self.report_period,
            "overall_risk_score": round(self.overall_risk_score, 1),
            "overall_risk_level": self.overall_risk_level,
            "overall_compliance_score": round(self.overall_compliance_score, 1),
            "research_summary": self.research_summary,
            "risk_summary": self.risk_summary,
            "compliance_summary": self.compliance_summary,
            "key_findings": self.key_findings,
        }


@dataclass
class CommitteeReport:
    """Investment Committee Report（Phase 9 主输出）。

    组成：Executive Summary / Research Findings / Risk Findings /
          Compliance Findings / Evidence Chain / Human Review Items。

    流程：Supervisor → Research → Risk → Compliance → Final Report。
    """

    id: int | None = None
    document_id: int = 0
    audit_id: int | None = None
    intelligence_report_id: int | None = None

    company: str = ""
    stock_code: str = ""
    report_period: str = ""

    # Agent 执行流程
    agent_flow: list[dict] = field(default_factory=list)
    agent_results: dict[str, AgentResult] = field(default_factory=dict)

    # 报告各部分
    executive_summary: ExecutiveSummary = field(default_factory=ExecutiveSummary)
    research_findings: ResearchFindings = field(default_factory=ResearchFindings)
    risk_findings: RiskFindings = field(default_factory=RiskFindings)
    compliance_findings: ComplianceFindings = field(default_factory=ComplianceFindings)
    evidence_chain: list[dict] = field(default_factory=list)
    human_review_items: list[HumanReviewItem] = field(default_factory=list)

    overall_risk_score: float = 0.0
    overall_risk_level: str = "LOW"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "audit_id": self.audit_id,
            "intelligence_report_id": self.intelligence_report_id,
            "company": self.company,
            "stock_code": self.stock_code,
            "report_period": self.report_period,
            "agent_flow": self.agent_flow,
            "agent_results": {
                k: v.to_dict() if isinstance(v, AgentResult) else v
                for k, v in self.agent_results.items()
            },
            "executive_summary": self.executive_summary.to_dict(),
            "research_findings": self.research_findings.to_dict(),
            "risk_findings": self.risk_findings.to_dict(),
            "compliance_findings": self.compliance_findings.to_dict(),
            "evidence_chain": self.evidence_chain,
            "human_review_items": [h.to_dict() for h in self.human_review_items],
            "overall_risk_score": round(self.overall_risk_score, 1),
            "overall_risk_level": self.overall_risk_level,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# 风险分数 → Level（与 Phase 6/7/8 阈值一致：LOW<30 / MEDIUM≤65 / HIGH>65）
# ---------------------------------------------------------------------------
def risk_level_of(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"


def severity_of(score: float) -> str:
    """风险分 → 严重度（与 risk_level_of 同口径）。"""
    if score < 30.0:
        return COMPLIANCE_SEVERITY_LOW
    if score <= 65.0:
        return COMPLIANCE_SEVERITY_MEDIUM
    return COMPLIANCE_SEVERITY_HIGH


__all__ = [
    # Agent 标识
    "AGENT_SUPERVISOR",
    "AGENT_RESEARCH",
    "AGENT_RISK",
    "AGENT_COMPLIANCE",
    "AGENTS",
    "AGENT_LABELS",
    "AGENT_STATUS_PENDING",
    "AGENT_STATUS_RUNNING",
    "AGENT_STATUS_DONE",
    "AGENT_STATUS_FAILED",
    "AGENT_STATUSES",
    # Compliance
    "COMPLIANCE_UNSUPPORTED_CLAIM",
    "COMPLIANCE_OVERSTATEMENT",
    "COMPLIANCE_MISSING_EVIDENCE",
    "COMPLIANCE_FORECAST_AS_FACT",
    "COMPLIANCE_TYPES",
    "COMPLIANCE_LABELS",
    "COMPLIANCE_SEVERITY_HIGH",
    "COMPLIANCE_SEVERITY_MEDIUM",
    "COMPLIANCE_SEVERITY_LOW",
    "COMPLIANCE_DEFAULT_SCORE",
    # 数据类
    "AgentTask",
    "AgentResult",
    "CompanyOverview",
    "BusinessAnalysis",
    "FinancialSummary",
    "ResearchFindings",
    "RiskFindings",
    "ComplianceFinding",
    "ComplianceFindings",
    "HumanReviewItem",
    "ExecutiveSummary",
    "CommitteeReport",
    # 工具
    "risk_level_of",
    "severity_of",
]
