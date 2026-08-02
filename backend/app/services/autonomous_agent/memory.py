"""Autonomous Investigation Agent Memory（Phase 13）。

保存公司历史风险 / 前序发现 / 已解决问题，供 Continuous Monitoring 调用。

数据库表：investigation_memory
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.autonomous_agent import InvestigationMemoryRow
from app.services.autonomous_agent.schemas import AgentMemory, _now_iso


def get_memory(session: Session, company: str) -> AgentMemory | None:
    """按公司名查询记忆。"""
    row = (
        session.query(InvestigationMemoryRow)
        .filter(InvestigationMemoryRow.company == company)
        .first()
    )
    if row is None:
        return None
    return _memory_from_row(row)


def upsert_memory(
    session: Session,
    company: str,
    stock_code: str = "",
    historical_risk: dict | None = None,
    previous_findings: list[dict] | None = None,
    resolved_issues: list[dict] | None = None,
    last_investigation_id: int | None = None,
    replace_findings: bool = False,
    replace_resolved: bool = False,
) -> AgentMemory:
    """插入或更新记忆（按 company 唯一）。

    默认追加 previous_findings / resolved_issues 以保留历史；
    传入 replace_findings=True / replace_resolved=True 则整体替换。
    """
    row = (
        session.query(InvestigationMemoryRow)
        .filter(InvestigationMemoryRow.company == company)
        .first()
    )
    now = datetime.utcnow()
    if row is None:
        row = InvestigationMemoryRow(
            company=company,
            stock_code=stock_code,
            historical_risk_json=_json(historical_risk or {}),
            previous_findings_json=_json(previous_findings or []),
            resolved_issues_json=_json(resolved_issues or []),
            last_investigation_id=last_investigation_id,
            updated_at=now,
        )
        session.add(row)
    else:
        if historical_risk is not None:
            row.historical_risk_json = _json(historical_risk)
        if previous_findings is not None:
            if replace_findings:
                row.previous_findings_json = _json(previous_findings[-20:])
            else:
                existing = _loads_list(row.previous_findings_json)
                existing.extend(previous_findings)
                row.previous_findings_json = _json(existing[-20:])
        if resolved_issues is not None:
            if replace_resolved:
                row.resolved_issues_json = _json(resolved_issues[-20:])
            else:
                existing = _loads_list(row.resolved_issues_json)
                existing.extend(resolved_issues)
                row.resolved_issues_json = _json(existing[-20:])
        if last_investigation_id is not None:
            row.last_investigation_id = last_investigation_id
        if stock_code:
            row.stock_code = stock_code
        row.updated_at = now
    session.commit()
    session.refresh(row)
    return _memory_from_row(row)


def resolve_issue(
    session: Session,
    company: str,
    issue: dict,
) -> AgentMemory | None:
    """将一个问题从 previous_findings 标记为 resolved。"""
    mem = get_memory(session, company)
    if mem is None:
        return None
    findings = [f for f in mem.previous_findings if f != issue]
    resolved = list(mem.resolved_issues) + [issue]
    # 用替换模式避免追加导致重复
    return upsert_memory(
        session,
        company,
        previous_findings=findings,
        resolved_issues=resolved,
        replace_findings=True,
        replace_resolved=True,
    )


def list_memories(session: Session, limit: int = 100) -> list[AgentMemory]:
    rows = (
        session.query(InvestigationMemoryRow)
        .order_by(InvestigationMemoryRow.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [_memory_from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _memory_from_row(row: InvestigationMemoryRow) -> AgentMemory:
    return AgentMemory(
        id=row.id,
        company=row.company,
        stock_code=row.stock_code or "",
        historical_risk=_loads_dict(row.historical_risk_json),
        previous_findings=_loads_list(row.previous_findings_json),
        resolved_issues=_loads_list(row.resolved_issues_json),
        last_investigation_id=row.last_investigation_id,
        updated_at=row.updated_at.isoformat(timespec="seconds") + "Z"
        if row.updated_at
        else "",
    )


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads_dict(s) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s) or {}
    except Exception:  # noqa: BLE001
        return {}


def _loads_list(s) -> list:
    if not s:
        return []
    try:
        return json.loads(s) or []
    except Exception:  # noqa: BLE001
        return []


__all__ = [
    "get_memory",
    "upsert_memory",
    "resolve_issue",
    "list_memories",
]
