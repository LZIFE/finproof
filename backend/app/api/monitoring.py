"""Continuous Monitoring API（Phase 12）。

- POST /api/v1/monitoring/theses       新增历史投资观点
- GET  /api/v1/monitoring/theses        查询观点（可按 portfolio 过滤）
- POST /api/v1/monitoring/runs         对新 Facts 运行监控检测，生成告警
- GET  /api/v1/monitoring/alerts       查询告警（可按 portfolio/status 过滤）
- PATCH /api/v1/monitoring/alerts/{id} 更新告警状态
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.monitoring_api import (
    AlertStatusUpdate,
    MonitoringRunRequest,
    ThesisCreate,
)
from app.services.monitoring import (
    add_thesis,
    list_alerts,
    list_theses,
    run_monitoring,
    update_alert_status,
)

router = APIRouter(tags=["monitoring"])


@router.post("/api/v1/monitoring/theses", status_code=201)
def create_thesis_endpoint(
    body: ThesisCreate,
    session: Session = Depends(get_session),
) -> dict:
    thesis = add_thesis(
        session,
        thesis_id=body.thesis_id,
        company=body.company,
        claim=body.claim,
        metric=body.metric,
        metric_value=body.metric_value,
        metric_unit=body.metric_unit,
        source=body.source,
        risk_score=body.risk_score,
        portfolio_id=body.portfolio_id,
        project_id=body.project_id,
        metadata=body.metadata,
    )
    return thesis.to_dict()


@router.get("/api/v1/monitoring/theses")
def list_theses_endpoint(
    portfolio_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    theses = list_theses(session, portfolio_id)
    return {"count": len(theses), "theses": [t.to_dict() for t in theses]}


@router.post("/api/v1/monitoring/runs", status_code=201)
def run_monitoring_endpoint(
    body: MonitoringRunRequest,
    session: Session = Depends(get_session),
) -> dict:
    new_facts = [nf.model_dump() for nf in body.new_facts]
    alerts = run_monitoring(session, body.portfolio_id, new_facts)
    return {
        "portfolio_id": body.portfolio_id,
        "new_facts_count": len(new_facts),
        "alerts_count": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
    }


@router.get("/api/v1/monitoring/alerts")
def list_alerts_endpoint(
    portfolio_id: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    alerts = list_alerts(session, portfolio_id, status)
    return {"count": len(alerts), "alerts": [a.to_dict() for a in alerts]}


@router.patch("/api/v1/monitoring/alerts/{alert_id}")
def update_alert_endpoint(
    alert_id: str,
    body: AlertStatusUpdate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        alert = update_alert_status(session, alert_id, body.status, body.note)
        return alert.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
