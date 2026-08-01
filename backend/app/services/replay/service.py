"""FinProof Replay Service（Phase 21）。

build_replay：聚合既有审计数据 → 持久化 audit_replay_events → ReplayTimeline。
get_replay：从 audit_replay_events 读取已持久化时间线。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.replay import AuditReplayEventRow
from app.services.replay.collector import collect_events
from app.services.replay.schemas import (
    ReplayEvent,
    ReplayTimeline,
    TIMELINE_ORDER,
    _now_iso,
)


def build_replay(session: Session, audit_id: str, persist: bool = True) -> ReplayTimeline:
    """构建审计回放时间线：聚合既有数据 → 持久化 → 返回 ReplayTimeline。"""
    if not audit_id:
        raise ValueError("audit_id 不能为空")

    events = collect_events(session, audit_id)

    # 持久化到 audit_replay_events（若 persist 且有事件）
    if persist and events:
        _persist(session, audit_id, events)

    return _assemble(audit_id, events)


def get_replay(session: Session, audit_id: str) -> ReplayTimeline:
    """从已持久化的 audit_replay_events 读取回放时间线。

    若库中无该 audit_id 的事件，**不重新聚合**（仅展示已有数据，任务书 §限制）。
    """
    if not audit_id:
        raise ValueError("audit_id 不能为空")

    rows = (
        session.query(AuditReplayEventRow)
        .filter(AuditReplayEventRow.audit_id == audit_id)
        .order_by(AuditReplayEventRow.id.asc())
        .all()
    )
    events = [
        ReplayEvent(
            id=r.id,
            audit_id=r.audit_id,
            event_type=r.event_type,
            timestamp=(r.timestamp.isoformat(timespec="seconds") + "Z") if r.timestamp else "",
            actor=r.actor or "",
            content=r.content or "",
            evidence_reference=r.evidence_reference or "",
            source=r.source or "",
            evidence_summary=r.evidence_summary or "",
            result_summary=r.result_summary or "",
        )
        for r in rows
    ]
    return _assemble(audit_id, events)


def list_replay(session: Session, limit: int = 50) -> list[dict]:
    """列出最近回放 audit_id（仅元数据，前端选择用）。"""
    rows = (
        session.query(AuditReplayEventRow)
        .order_by(AuditReplayEventRow.id.desc())
        .limit(limit)
        .all()
    )
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r.audit_id in seen:
            continue
        seen.add(r.audit_id)
        out.append({
            "audit_id": r.audit_id,
            "event_count": session.query(AuditReplayEventRow).filter(AuditReplayEventRow.audit_id == r.audit_id).count(),
            "latest_timestamp": (r.timestamp.isoformat(timespec="seconds") + "Z") if r.timestamp else "",
        })
    return out


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------
def _assemble(audit_id: str, events: list[ReplayEvent]) -> ReplayTimeline:
    steps: dict[str, list[ReplayEvent]] = {et: [] for et in TIMELINE_ORDER}
    for e in events:
        if e.event_type in steps:
            steps[e.event_type].append(e)
    return ReplayTimeline(
        audit_id=audit_id,
        events=events,
        total_events=len(events),
        steps=steps,
        created_at=_now_iso(),
    )


def _persist(session: Session, audit_id: str, events: list[ReplayEvent]) -> None:
    """持久化事件到 audit_replay_events（同 audit_id 不重复插入）。"""
    existing = (
        session.query(AuditReplayEventRow)
        .filter(AuditReplayEventRow.audit_id == audit_id)
        .count()
    )
    if existing > 0:
        return  # 已有持久化，不重复写入
    for e in events:
        # 解析 timestamp 字符串 → datetime（宽松）
        ts = None
        if e.timestamp:
            try:
                ts = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                ts = datetime.utcnow()
        else:
            ts = datetime.utcnow()
        session.add(AuditReplayEventRow(
            audit_id=audit_id,
            event_type=e.event_type,
            timestamp=ts,
            actor=e.actor,
            content=e.content,
            evidence_reference=e.evidence_reference,
            source=e.source,
            evidence_summary=e.evidence_summary,
            result_summary=e.result_summary,
        ))
    session.commit()


__all__ = ["build_replay", "get_replay", "list_replay"]
