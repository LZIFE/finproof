"""FinProof Governance Center API（Phase 20，任务书 §API）。

- POST /api/v1/governance/dashboard   构建完整治理仪表板（6 部分聚合）
- GET  /api/v1/governance/overview    轻量概览（顶层指标，高频轮询）
- GET  /api/v1/governance/reliability 仅 AI 可靠性评分
- GET  /api/v1/governance/agent-performance 仅 Agent 性能

整合层：不修改已有核心模块；不输出投资建议。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.governance_center import DashboardRequest
from app.services.governance_center.dashboard import (
    build_agent_performance,
    build_dashboard,
    build_overview,
    build_reliability,
)

router = APIRouter(tags=["governance"])


@router.post("/api/v1/governance/dashboard", status_code=200)
def build_dashboard_endpoint(
    body: DashboardRequest | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """构建完整 FinProof AI Governance Dashboard（6 部分聚合）。"""
    governance_id = f"GOV-{body.company}" if body and body.company else ""
    dashboard = build_dashboard(session, governance_id=governance_id)
    return dashboard.to_dict()


@router.get("/api/v1/governance/overview")
def overview_endpoint(session: Session = Depends(get_session)) -> dict:
    """轻量概览：仅顶层指标。"""
    return build_overview(session)


@router.get("/api/v1/governance/reliability")
def reliability_endpoint(session: Session = Depends(get_session)) -> dict:
    """仅 AI 可靠性评分部分。"""
    return build_reliability(session)


@router.get("/api/v1/governance/agent-performance")
def agent_performance_endpoint(session: Session = Depends(get_session)) -> dict:
    """仅 Agent 性能部分。"""
    return build_agent_performance(session)
