"""FinProof Executive AI Governance Center Package（Phase 20）。

整合 Phase 0-19 能力的治理层。**不做新业务**：仅聚合既有 ORM 行 + 串联既有模块入口。
保持 Evidence First；不输出投资建议；不修改 Verification 核心。
"""

from app.services.governance_center.dashboard import (
    build_agent_performance,
    build_dashboard,
    build_overview,
    build_reliability,
)
from app.services.governance_center.executive_report import run_governance_pipeline
from app.services.governance_center.metrics import (
    aggregate_agent_performance,
    aggregate_audit_timeline,
    aggregate_evidence_graph,
    aggregate_intelligence,
    aggregate_reliability,
    aggregate_risk_monitoring,
)
from app.services.governance_center.schemas import (
    AgentPerformance,
    AuditEvent,
    AuditTimeline,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    FinalGovernanceReport,
    GovernanceDashboard,
    IntelligenceOverview,
    PipelineStage,
    ReliabilityScore,
    RiskItem,
    RiskMonitoring,
    contains_forbidden_content,
    risk_level_of,
)

__all__ = [
    # schemas
    "AgentPerformance", "AuditEvent", "AuditTimeline", "EvidenceChain",
    "EvidenceEdge", "EvidenceGraph", "EvidenceNode", "EvidenceRef",
    "FinalGovernanceReport", "GovernanceDashboard", "IntelligenceOverview",
    "PipelineStage", "ReliabilityScore", "RiskItem", "RiskMonitoring",
    "contains_forbidden_content", "risk_level_of",
    # metrics
    "aggregate_reliability", "aggregate_intelligence", "aggregate_risk_monitoring",
    "aggregate_agent_performance", "aggregate_evidence_graph", "aggregate_audit_timeline",
    # dashboard
    "build_dashboard", "build_overview", "build_reliability", "build_agent_performance",
    # executive report
    "run_governance_pipeline",
]
