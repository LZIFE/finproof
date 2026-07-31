"""审计 API（Phase 5）。

- POST /api/v1/audits          创建审计任务（{document_id} → {audit_id, status}，同步执行）
- GET  /api/v1/audits/{id}     查询审计结果（summary/findings/evidence_chain/verification_results）
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.audit import AuditReport
from app.schemas.audit import (
    AuditCreateRequest,
    AuditReportOut,
    AuditRunOut,
    AuditSummaryOut,
)
from app.services.agent.executor import run_audit

router = APIRouter(tags=["audit"])


@router.post("/api/v1/audits", status_code=201)
def create_audit(
    body: AuditCreateRequest,
    session: Session = Depends(get_session),
) -> AuditRunOut:
    result = run_audit(session, body.document_id, mode="ai")
    return AuditRunOut(audit_id=result["audit_id"], status="COMPLETED")


@router.get("/api/v1/audits/{audit_id}")
def get_audit(audit_id: int, session: Session = Depends(get_session)) -> AuditReportOut:
    row = session.get(AuditReport, audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"审计任务不存在: {audit_id}")
    report = json.loads(row.report_json or "{}")
    summary = report.get("summary", {})
    # Phase 6：Audit Report 集成 Overall Risk（确定性重建，不重复入库）
    from app.services.risk.risk_engine import assess_audit

    risk = assess_audit(session, audit_id, persist=False).to_dict()
    return AuditReportOut(
        audit_id=row.id,
        document_id=row.document_id,
        summary=AuditSummaryOut(**summary),
        findings=report.get("findings", []),
        evidence_chain=report.get("evidence_chain", []),
        verification_results=report.get("verification_results", []),
        plan=json.loads(row.plan_json) if row.plan_json else None,
        risk={
            "overall_risk_score": risk["overall_risk_score"],
            "overall_risk_level": risk["overall_risk_level"],
            "risk_distribution": risk["risk_distribution"],
        },
    )
