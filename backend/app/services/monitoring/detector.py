"""Continuous Monitoring Conflict Detector（Phase 12）。

检测新 Fact 与历史 Claim 之间的 Thesis Conflict。

冲突类型：
- METRIC_DRIFT        关键指标偏离阈值（默认 ±15%）
- DIRECTION_REVERSAL  方向反转（如历史"增长" → 新"下滑"）
- NEW_RISK            新出现的风险关键词（如"立案"/"减持"/"商誉减值"）

输出：ThesisConflict（claim / new_fact / difference / risk_score）

设计约束：不修改已有核心模块；Monitoring 作为新增追踪层。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.monitoring import (
    InvestmentThesisRow,
    MonitoringAlertRow,
)
from app.schemas.monitoring import (
    InvestmentThesis,
    MonitoringAlert,
    ThesisConflict,
    risk_level_of,
)


# ---------------------------------------------------------------------------
# 冲突检测配置
# ---------------------------------------------------------------------------
DRIFT_THRESHOLD = 0.15  # 指标偏离 ±15% 视为漂移

_DIRECTION_POS = ("增长", "上升", "提升", "扩大", "改善", "上行", "回暖", "增加")
_DIRECTION_NEG = ("下滑", "下降", "减少", "收缩", "恶化", "下行", "回落", "降低")

_NEW_RISK_KW = (
    "立案",
    "减持",
    "商誉减值",
    "退市",
    "警示",
    "处罚",
    "违约",
    "爆雷",
    "问询函",
    "监管",
)


# ---------------------------------------------------------------------------
# Thesis CRUD
# ---------------------------------------------------------------------------
def add_thesis(
    session: Session,
    thesis_id: str,
    company: str,
    claim: str,
    metric: str = "",
    metric_value: float | None = None,
    metric_unit: str = "",
    source: str = "",
    risk_score: float = 0.0,
    portfolio_id: str | None = None,
    project_id: int | None = None,
    metadata: dict | None = None,
) -> InvestmentThesis:
    row = InvestmentThesisRow(
        thesis_id=thesis_id,
        portfolio_id=portfolio_id,
        project_id=project_id,
        company=company,
        claim=claim,
        metric=metric,
        metric_value=metric_value,
        metric_unit=metric_unit,
        source=source,
        risk_score=risk_score,
        metadata_json=_json(metadata or {}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _thesis_from_row(row)


def list_theses(session: Session, portfolio_id: str | None = None) -> list[InvestmentThesis]:
    q = session.query(InvestmentThesisRow)
    if portfolio_id:
        q = q.filter(InvestmentThesisRow.portfolio_id == portfolio_id)
    rows = q.order_by(InvestmentThesisRow.id.asc()).all()
    return [_thesis_from_row(r) for r in rows]


def get_thesis(session: Session, thesis_id: str) -> InvestmentThesis:
    row = (
        session.query(InvestmentThesisRow)
        .filter(InvestmentThesisRow.thesis_id == thesis_id)
        .first()
    )
    if row is None:
        raise LookupError(f"投资观点不存在: {thesis_id}")
    return _thesis_from_row(row)


# ---------------------------------------------------------------------------
# Conflict Detection
# ---------------------------------------------------------------------------
def detect_conflicts(
    thesis: InvestmentThesis,
    new_fact: str,
    new_metric_value: float | None = None,
) -> ThesisConflict:
    """检测单条 thesis 与新 Fact 的冲突，返回 ThesisConflict 或 None。"""
    diff_parts: list[str] = []
    conflict_type = "METRIC_DRIFT"
    risk_score = 0.0

    # 1) 指标漂移
    if (
        thesis.metric_value is not None
        and new_metric_value is not None
        and thesis.metric_value != 0
    ):
        base = abs(thesis.metric_value)
        delta = new_metric_value - thesis.metric_value
        ratio = abs(delta) / base
        if ratio >= DRIFT_THRESHOLD:
            diff_parts.append(
                f"指标[{thesis.metric}]由 {thesis.metric_value}{thesis.metric_unit}"
                f" 变为 {new_metric_value}{thesis.metric_unit}（偏离 {ratio:.1%}）"
            )
            risk_score = max(risk_score, min(100.0, 40.0 + ratio * 100.0))

    # 2) 方向反转
    history_pos = any(k in thesis.claim for k in _DIRECTION_POS)
    history_neg = any(k in thesis.claim for k in _DIRECTION_NEG)
    new_pos = any(k in new_fact for k in _DIRECTION_POS)
    new_neg = any(k in new_fact for k in _DIRECTION_NEG)
    reversed_dir = (history_pos and new_neg and not new_pos) or (
        history_neg and new_pos and not new_neg
    )
    if reversed_dir:
        conflict_type = "DIRECTION_REVERSAL"
        diff_parts.append("历史方向与新 Fact 相反")
        risk_score = max(risk_score, 70.0)

    # 3) 新风险关键词
    hit_kw = [k for k in _NEW_RISK_KW if k in new_fact and k not in thesis.claim]
    if hit_kw:
        conflict_type = "NEW_RISK"
        diff_parts.append(f"新风险关键词: {','.join(hit_kw)}")
        risk_score = max(risk_score, 75.0)

    if not diff_parts:
        return ThesisConflict(
            thesis_id=thesis.thesis_id,
            company=thesis.company,
            claim=thesis.claim,
            new_fact=new_fact,
            difference="无冲突",
            risk_score=0.0,
            conflict_type="NONE",
            portfolio_id=thesis.portfolio_id,
            project_id=thesis.project_id,
        )

    return ThesisConflict(
        thesis_id=thesis.thesis_id,
        company=thesis.company,
        claim=thesis.claim,
        new_fact=new_fact,
        difference="；".join(diff_parts),
        risk_score=risk_score,
        conflict_type=conflict_type,
        portfolio_id=thesis.portfolio_id,
        project_id=thesis.project_id,
    )


# ---------------------------------------------------------------------------
# Monitoring run：对一组新 Facts 跑检测并落库告警
# ---------------------------------------------------------------------------
def run_monitoring(
    session: Session,
    portfolio_id: str | None,
    new_facts: list[dict],
) -> list[MonitoringAlert]:
    """对每个 new_fact 关联 thesis 检测冲突，生成 MonitoringAlert。

    new_facts 条目：{"thesis_id", "new_fact", "new_metric_value"(opt)}
    """
    alerts: list[MonitoringAlert] = []
    for nf in new_facts:
        thesis_id = nf.get("thesis_id", "")
        new_fact = nf.get("new_fact", "")
        new_metric_value = nf.get("new_metric_value")
        if not thesis_id:
            continue
        try:
            thesis = get_thesis(session, thesis_id)
        except LookupError:
            continue
        conflict = detect_conflicts(thesis, new_fact, new_metric_value)
        if conflict.conflict_type == "NONE":
            continue
        alert = _save_alert(session, conflict, portfolio_id=portfolio_id)
        alerts.append(alert)
    return alerts


# ---------------------------------------------------------------------------
# Alert CRUD
# ---------------------------------------------------------------------------
def list_alerts(
    session: Session,
    portfolio_id: str | None = None,
    status: str | None = None,
) -> list[MonitoringAlert]:
    q = session.query(MonitoringAlertRow)
    if portfolio_id:
        q = q.filter(MonitoringAlertRow.portfolio_id == portfolio_id)
    if status:
        q = q.filter(MonitoringAlertRow.status == status)
    rows = q.order_by(MonitoringAlertRow.id.desc()).all()
    return [_alert_from_row(r) for r in rows]


def get_alert(session: Session, alert_id: str) -> MonitoringAlert:
    row = (
        session.query(MonitoringAlertRow)
        .filter(MonitoringAlertRow.alert_id == alert_id)
        .first()
    )
    if row is None:
        raise LookupError(f"告警不存在: {alert_id}")
    return _alert_from_row(row)


def update_alert_status(
    session: Session, alert_id: str, status: str, note: str = ""
) -> MonitoringAlert:
    if status not in ("OPEN", "RESOLVED", "IGNORED"):
        raise ValueError(f"非法状态: {status}")
    row = (
        session.query(MonitoringAlertRow)
        .filter(MonitoringAlertRow.alert_id == alert_id)
        .first()
    )
    if row is None:
        raise LookupError(f"告警不存在: {alert_id}")
    row.status = status
    row.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(row)
    return _alert_from_row(row)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _save_alert(
    session: Session,
    conflict: ThesisConflict,
    portfolio_id: str | None,
) -> MonitoringAlert:
    alert_id = f"ALT-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]}"
    risk_level = risk_level_of(conflict.risk_score)
    row = MonitoringAlertRow(
        alert_id=alert_id,
        portfolio_id=conflict.portfolio_id or portfolio_id,
        project_id=conflict.project_id,
        thesis_id=conflict.thesis_id,
        company=conflict.company,
        claim=conflict.claim,
        new_fact=conflict.new_fact,
        difference=conflict.difference,
        risk_score=conflict.risk_score,
        risk_level=risk_level,
        conflict_type=conflict.conflict_type,
        status="OPEN",
        metadata_json=_json({"conflict_type": conflict.conflict_type}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _alert_from_row(row)


def _thesis_from_row(row: InvestmentThesisRow) -> InvestmentThesis:
    import json as _json

    meta = {}
    if row.metadata_json:
        try:
            meta = _json.loads(row.metadata_json)
        except Exception:  # noqa: BLE001
            meta = {}
    return InvestmentThesis(
        thesis_id=row.thesis_id,
        company=row.company,
        claim=row.claim,
        metric=row.metric or "",
        metric_value=row.metric_value,
        metric_unit=row.metric_unit or "",
        source=row.source or "",
        risk_score=row.risk_score,
        portfolio_id=row.portfolio_id,
        project_id=row.project_id,
        metadata=meta,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z"
        if row.created_at
        else "",
    )


def _alert_from_row(row: MonitoringAlertRow) -> MonitoringAlert:
    import json as _json

    meta = {}
    if row.metadata_json:
        try:
            meta = _json.loads(row.metadata_json)
        except Exception:  # noqa: BLE001
            meta = {}
    return MonitoringAlert(
        alert_id=row.alert_id,
        thesis_id=row.thesis_id or "",
        company=row.company,
        claim=row.claim,
        new_fact=row.new_fact,
        difference=row.difference or "",
        risk_score=row.risk_score,
        risk_level=row.risk_level or "LOW",
        conflict_type=row.conflict_type or "METRIC_DRIFT",
        status=row.status,
        portfolio_id=row.portfolio_id,
        project_id=row.project_id,
        metadata=meta,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z"
        if row.created_at
        else "",
    )


def _json(obj: dict) -> str:
    import json as _json

    return _json.dumps(obj, ensure_ascii=False)


__all__ = [
    "DRIFT_THRESHOLD",
    "add_thesis",
    "list_theses",
    "get_thesis",
    "detect_conflicts",
    "run_monitoring",
    "list_alerts",
    "get_alert",
    "update_alert_status",
]
