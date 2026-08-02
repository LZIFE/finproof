"""Portfolio Risk Dashboard API（Phase 12）。

- POST /api/v1/portfolio/projects               添加投资项目
- GET  /api/v1/portfolio/projects               查询组合内项目
- PATCH /api/v1/portfolio/projects/{id}         更新项目风险分
- POST /api/v1/portfolio/snapshots              构建并保存组合风险快照
- GET  /api/v1/portfolio/snapshots              查询组合历史快照
- GET  /api/v1/portfolio/snapshots/{id}         查询单个快照
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.portfolio_api import (
    PortfolioProjectCreate,
    PortfolioProjectUpdate,
    SnapshotBuildRequest,
)
from app.services.portfolio import (
    add_project,
    build_snapshot,
    get_project,
    get_snapshot,
    list_projects,
    list_snapshots,
    update_project_risk,
)

router = APIRouter(tags=["portfolio"])


@router.post("/api/v1/portfolio/projects", status_code=201)
def create_project_endpoint(
    body: PortfolioProjectCreate,
    session: Session = Depends(get_session),
) -> dict:
    project = add_project(
        session,
        portfolio_id=body.portfolio_id,
        company=body.company,
        stock_code=body.stock_code,
        weight=body.weight,
        audit_id=body.audit_id,
        committee_report_id=body.committee_report_id,
        latest_risk_score=body.latest_risk_score,
    )
    return project.to_dict()


@router.get("/api/v1/portfolio/projects")
def list_projects_endpoint(
    portfolio_id: str,
    session: Session = Depends(get_session),
) -> dict:
    projects = list_projects(session, portfolio_id)
    return {"portfolio_id": portfolio_id, "count": len(projects), "projects": [p.to_dict() for p in projects]}


@router.patch("/api/v1/portfolio/projects/{project_id}")
def update_project_endpoint(
    project_id: int,
    body: PortfolioProjectUpdate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        project = update_project_risk(session, project_id, body.latest_risk_score)
        return project.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/v1/portfolio/snapshots", status_code=201)
def build_snapshot_endpoint(
    body: SnapshotBuildRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        snapshot = build_snapshot(session, body.portfolio_id)
        return snapshot.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/v1/portfolio/snapshots")
def list_snapshots_endpoint(
    portfolio_id: str,
    session: Session = Depends(get_session),
) -> dict:
    snapshots = list_snapshots(session, portfolio_id)
    return {
        "portfolio_id": portfolio_id,
        "count": len(snapshots),
        "snapshots": [s.to_dict() for s in snapshots],
    }


@router.get("/api/v1/portfolio/snapshots/{snapshot_id}")
def get_snapshot_endpoint(
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return get_snapshot(session, snapshot_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
