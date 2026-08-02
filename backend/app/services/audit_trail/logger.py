"""Audit Trail Logger Service（Phase 12）。

提供 `log_audit` 工具，供各模块在关键操作时记录审计日志。

字段（任务书 §3）：
- user              操作人
- action            动作类型（如 RUN_COMMITTEE / RUN_VERIFICATION）
- timestamp         时间戳
- model_version     模型版本
- rule_version      规则版本
- evidence_used     使用的证据（list[dict]）
- detail            其他上下文（dict）
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.audit_trail import AuditTrailLogRow
from app.schemas.audit_trail import AuditTrailLog


def log_audit(
    session: Session,
    *,
    user: str = "system",
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    model_version: str = "",
    rule_version: str = "",
    evidence_used: list[dict] | None = None,
    detail: dict | None = None,
) -> AuditTrailLog:
    """记录一条审计日志并返回。"""
    now = datetime.utcnow()
    log_id = f"LOG-{now.strftime('%Y%m%d%H%M%S%f')[:20]}"
    row = AuditTrailLogRow(
        log_id=log_id,
        user=user,
        action=action,
        target_type=target_type,
        target_id=target_id,
        timestamp=now,
        model_version=model_version,
        rule_version=rule_version,
        evidence_used_json=json.dumps(evidence_used or [], ensure_ascii=False),
        detail_json=json.dumps(detail or {}, ensure_ascii=False),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _log_from_row(row)


def list_logs(
    session: Session,
    user: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    limit: int = 100,
) -> list[AuditTrailLog]:
    q = session.query(AuditTrailLogRow)
    if user:
        q = q.filter(AuditTrailLogRow.user == user)
    if action:
        q = q.filter(AuditTrailLogRow.action == action)
    if target_type:
        q = q.filter(AuditTrailLogRow.target_type == target_type)
    rows = q.order_by(AuditTrailLogRow.id.desc()).limit(limit).all()
    return [_log_from_row(r) for r in rows]


def get_log(session: Session, log_id: str) -> AuditTrailLog:
    row = (
        session.query(AuditTrailLogRow)
        .filter(AuditTrailLogRow.log_id == log_id)
        .first()
    )
    if row is None:
        raise LookupError(f"审计日志不存在: {log_id}")
    return _log_from_row(row)


def _log_from_row(row: AuditTrailLogRow) -> AuditTrailLog:
    evidence = []
    if row.evidence_used_json:
        try:
            evidence = json.loads(row.evidence_used_json)
        except Exception:  # noqa: BLE001
            evidence = []
    detail = {}
    if row.detail_json:
        try:
            detail = json.loads(row.detail_json)
        except Exception:  # noqa: BLE001
            detail = {}
    return AuditTrailLog(
        log_id=row.log_id,
        user=row.user,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        timestamp=row.timestamp.isoformat(timespec="seconds") + "Z"
        if row.timestamp
        else "",
        model_version=row.model_version or "",
        rule_version=row.rule_version or "",
        evidence_used=evidence,
        detail=detail,
    )


__all__ = ["log_audit", "list_logs", "get_log"]
