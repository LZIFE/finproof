"""Governance API（Phase 12）。

企业治理视图：审计日志 + 证据溯源。

- POST /api/v1/governance/logs                 记录一条审计日志
- GET  /api/v1/governance/logs                 查询审计日志（支持 user/action/target_type 过滤）
- GET  /api/v1/governance/logs/{log_id}        查询单条审计日志
- GET  /api/v1/governance/evidence-trace/{target_type}/{target_id}
                                               查询某对象相关的审计日志（证据溯源）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.audit_trail_api import AuditLogCreate
from app.services.audit_trail import get_log, list_logs, log_audit

router = APIRouter(tags=["governance"])


@router.post("/api/v1/governance/logs", status_code=201)
def create_log_endpoint(
    body: AuditLogCreate,
    session: Session = Depends(get_session),
) -> dict:
    log = log_audit(
        session,
        user=body.user,
        action=body.action,
        target_type=body.target_type,
        target_id=body.target_id,
        model_version=body.model_version,
        rule_version=body.rule_version,
        evidence_used=body.evidence_used,
        detail=body.detail,
    )
    return log.to_dict()


@router.get("/api/v1/governance/logs")
def list_logs_endpoint(
    user: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
) -> dict:
    logs = list_logs(session, user, action, target_type, limit)
    return {"count": len(logs), "logs": [l.to_dict() for l in logs]}


@router.get("/api/v1/governance/logs/{log_id}")
def get_log_endpoint(log_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return get_log(session, log_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/governance/evidence-trace/{target_type}/{target_id}")
def evidence_trace_endpoint(
    target_type: str,
    target_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """证据溯源：返回与某对象相关的全部审计日志（按时间倒序）。"""
    logs = list_logs(session, target_type=target_type, limit=500)
    related = [l for l in logs if l.target_id == target_id]
    return {
        "target_type": target_type,
        "target_id": target_id,
        "count": len(related),
        "trace": [l.to_dict() for l in related],
    }
