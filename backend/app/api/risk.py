"""风险评分 API（Phase 6）。

- POST /api/v1/risk-assessments/{audit_id}  对一次 Audit 生成风险评分（入库）
- GET  /api/v1/risk-assessments/{audit_id}   查询整体风险（overall/distribution/top_risks/claim_details）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.audit import AuditReport
from app.services.risk.risk_engine import assess_audit

router = APIRouter(tags=["risk"])


def _get_audit_or_404(session: Session, audit_id: int) -> AuditReport:
    row = session.get(AuditReport, audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"审计任务不存在: {audit_id}")
    return row


@router.post("/api/v1/risk-assessments/{audit_id}", status_code=201)
def create_risk_assessment(audit_id: int, session: Session = Depends(get_session)) -> dict:
    _get_audit_or_404(session, audit_id)
    try:
        report = assess_audit(session, audit_id, persist=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"风险评分失败: {exc}") from exc
    return report.to_dict()


@router.get("/api/v1/risk-assessments/{audit_id}")
def get_risk_assessment(audit_id: int, session: Session = Depends(get_session)) -> dict:
    _get_audit_or_404(session, audit_id)
    report = assess_audit(session, audit_id, persist=False)  # 确定性重建，不重复入库
    return report.to_dict()
