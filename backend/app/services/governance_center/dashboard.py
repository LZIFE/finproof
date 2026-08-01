"""FinProof Governance Center Dashboard Assembler（Phase 20）。

组装顶层 GovernanceDashboard：6 部分聚合（reliability / intelligence / risk /
agent / evidence / audit）。**不做新业务**，仅编排 metrics 聚合器。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.governance_center.metrics import (
    aggregate_agent_performance,
    aggregate_audit_timeline,
    aggregate_evidence_graph,
    aggregate_intelligence,
    aggregate_reliability,
    aggregate_risk_monitoring,
)
from app.services.governance_center.schemas import (
    GovernanceDashboard,
    _now_iso,
)


def build_dashboard(session: Session, governance_id: str = "") -> GovernanceDashboard:
    """组装并返回顶层治理仪表板（6 部分聚合）。"""
    if not governance_id:
        governance_id = f"GOV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    return GovernanceDashboard(
        reliability=aggregate_reliability(session),
        intelligence=aggregate_intelligence(session),
        risk_monitoring=aggregate_risk_monitoring(session),
        agent_performance=aggregate_agent_performance(session),
        evidence_graph=aggregate_evidence_graph(session),
        audit_timeline=aggregate_audit_timeline(session),
        generated_at=_now_iso(),
        governance_id=governance_id,
    )


def build_overview(session: Session) -> dict:
    """轻量概览：仅顶层指标（供 GET /overview 高频轮询）。"""
    rel = aggregate_reliability(session)
    intel = aggregate_intelligence(session)
    risk = aggregate_risk_monitoring(session)
    agent = aggregate_agent_performance(session)
    return {
        "generated_at": _now_iso(),
        "overall_reliability": rel.overall_reliability,
        "evidence_coverage": rel.evidence_coverage,
        "risk_detection_rate": rel.risk_detection_rate,
        "hallucination_detection_rate": rel.hallucination_detection_rate,
        "companies_analyzed": intel.companies_analyzed,
        "claims_verified": intel.claims_verified,
        "risk_findings": intel.risk_findings,
        "current_risks": len(risk.current_risks),
        "unresolved_reviews": risk.unresolved_reviews,
        "agent_score": agent.agent_score,
        "arena_runs": agent.arena_runs,
        "simulation_runs": agent.simulation_runs,
    }


def build_reliability(session: Session) -> dict:
    """仅可靠性部分（供 GET /reliability）。"""
    return aggregate_reliability(session).to_dict()


def build_agent_performance(session: Session) -> dict:
    """仅 Agent 性能部分（供 GET /agent-performance）。"""
    return aggregate_agent_performance(session).to_dict()


__all__ = [
    "build_dashboard",
    "build_overview",
    "build_reliability",
    "build_agent_performance",
]
