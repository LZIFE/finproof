"""FinProof Replay Collector（Phase 21）。

聚合既有审计数据 → 5 类回放事件。**不新增分析能力**，仅 SELECT 既有 ORM 行。
保持 Evidence First；不输出投资建议；不修改 Verification/Risk 核心。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.replay.schemas import (
    EVENT_AGENT,
    EVENT_CLAIM,
    EVENT_CONCLUSION,
    EVENT_EVIDENCE,
    EVENT_RISK,
    EVENT_VERIFICATION,
    ReplayEvent,
    _now_iso,
)


def collect_events(session: Session, audit_id: str) -> list[ReplayEvent]:
    """按 audit_id 聚合既有审计数据 → 5 类回放事件（按时间线顺序）。

    audit_id 解析规则（兼容多种既有表）：
      - "ARENA-XXXX"    → Arena Run（claim/evidence/agent 来自 Arena）
      - "GOV-RPT-XXXX"  → Governance Report（agent 来自 Arena）
      - "RESEARCH-XXXX" → Research Session（claim/evidence 来自 Research）
      - "RISK-XXXX"     → Risk Assessment（risk 来自 Risk Engine）
      - 数字            → 按表 id fallback
    若无匹配则返回空列表（前端显示"无回放事件"）。
    """
    events: list[ReplayEvent] = []
    if not audit_id:
        return events

    # ① AI Claim + ② Evidence（Research Agent / Arena Analyst）
    events.extend(_collect_claim_evidence(session, audit_id))

    # ③ Verification（Risk Assessment 的 verification_status / Reasoning Results）
    events.extend(_collect_verification(session, audit_id))

    # ④ Risk Assessment（Risk Engine）
    events.extend(_collect_risk(session, audit_id))

    # ⑤ Agent Discussion（Arena 4 角色 / Committee / Copilot）
    events.extend(_collect_agent(session, audit_id))

    # ⑥ Final Conclusion（Arena Judge / Committee Report）
    events.extend(_collect_conclusion(session, audit_id))

    # 按时间线顺序稳定排序（claim → evidence → verification → risk → agent → conclusion）
    order_index = {t: i for i, t in enumerate([EVENT_CLAIM, EVENT_EVIDENCE, EVENT_VERIFICATION, EVENT_RISK, EVENT_AGENT, EVENT_CONCLUSION])}
    events.sort(key=lambda e: (order_index.get(e.event_type, 99), e.id or 0))
    return events


# ---------------------------------------------------------------------------
# ① Claim + ② Evidence
# ---------------------------------------------------------------------------
def _collect_claim_evidence(session: Session, audit_id: str) -> list[ReplayEvent]:
    out: list[ReplayEvent] = []
    # Arena Analyst viewpoints（claim）+ evidence
    if audit_id.startswith("ARENA-"):
        try:
            from app.models.agent_arena import ArenaRunRow, ArenaMessageRow
            run_row = session.query(ArenaRunRow).filter(ArenaRunRow.run_id == audit_id).first()
            if run_row:
                msgs = session.query(ArenaMessageRow).filter(ArenaMessageRow.run_id == run_row.id).order_by(ArenaMessageRow.id.asc()).all()
                for m in msgs:
                    vps = _loads(m.viewpoints_json, [])
                    for v in vps:
                        out.append(ReplayEvent(
                            audit_id=audit_id,
                            event_type=EVENT_CLAIM,
                            timestamp=_iso(m.created_at),
                            actor="Analyst Agent",
                            content=v.get("claim", ""),
                            evidence_reference=json.dumps(v.get("evidence", [])[:3], ensure_ascii=False),
                            source="arena.analyst",
                            evidence_summary=f"{len(v.get('evidence', []))} 条证据",
                            result_summary="unsupported" if v.get("unsupported") else "grounded",
                        ))
                        # evidence_event：每条证据
                        for e in v.get("evidence", [])[:3]:
                            out.append(ReplayEvent(
                                audit_id=audit_id,
                                event_type=EVENT_EVIDENCE,
                                timestamp=_iso(m.created_at),
                                actor="Evidence Retrieval",
                                content=(e.get("text") or "")[:200],
                                evidence_reference=json.dumps({"block_id": e.get("block_id"), "document_id": e.get("document_id"), "page": e.get("page_number")}, ensure_ascii=False),
                                source="arena.evidence",
                                evidence_summary=f"doc {e.get('document_id')} p{e.get('page_number')}",
                                result_summary=f"score {e.get('final_score', 0)}",
                            ))
        except Exception:  # noqa: BLE001
            pass
    # Research Session findings（claim）+ evidence
    elif audit_id.startswith("RESEARCH-"):
        try:
            from app.models.research_agent import ResearchSessionRow
            rs = session.query(ResearchSessionRow).filter(ResearchSessionRow.session_id == audit_id).first()
            if rs:
                findings = _loads(rs.findings_json, [])
                for f in findings[:20]:
                    out.append(ReplayEvent(
                        audit_id=audit_id,
                        event_type=EVENT_CLAIM,
                        timestamp=_iso(rs.created_at),
                        actor="Research Agent",
                        content=(f.get("content") or "")[:200],
                        evidence_reference=json.dumps(f.get("evidence", [])[:3], ensure_ascii=False),
                        source="research.finding",
                        evidence_summary=f"{len(f.get('evidence', []))} 条证据",
                        result_summary="supported" if f.get("supported") else "unsupported",
                    ))
                    for e in f.get("evidence", [])[:3]:
                        out.append(ReplayEvent(
                            audit_id=audit_id,
                            event_type=EVENT_EVIDENCE,
                            timestamp=_iso(rs.created_at),
                            actor="Evidence Retrieval",
                            content=(e.get("text") or "")[:200],
                            evidence_reference=json.dumps({"block_id": e.get("block_id"), "document_id": e.get("document_id")}, ensure_ascii=False),
                            source="research.evidence",
                            evidence_summary=f"doc {e.get('document_id')} p{e.get('page_number')}",
                            result_summary=f"score {e.get('final_score', 0)}",
                        ))
        except Exception:  # noqa: BLE101
            pass
    return out


# ---------------------------------------------------------------------------
# ③ Verification
# ---------------------------------------------------------------------------
def _collect_verification(session: Session, audit_id: str) -> list[ReplayEvent]:
    out: list[ReplayEvent] = []
    # Risk Assessment 的 verification_status
    try:
        from app.models.risk import RiskAssessmentRow
        rows = session.query(RiskAssessmentRow).filter(RiskAssessmentRow.audit_id == audit_id).all()
        for r in rows:
            out.append(ReplayEvent(
                id=r.id,
                audit_id=audit_id,
                event_type=EVENT_VERIFICATION,
                timestamp=_iso(r.created_at),
                actor="Verification Engine",
                content=(r.verification_status or "") + (f" ({r.verification_type})" if r.verification_type else ""),
                evidence_reference="",
                source="verification",
                evidence_summary="-",
                result_summary=r.verification_status or "",
            ))
    except Exception:  # noqa: BLE101
        pass
    # Reasoning Results（逻辑验证）
    try:
        from app.models.financial_reasoning import ReasoningRunRow, ReasoningResultRow
        rr = session.query(ReasoningRunRow).filter(ReasoningRunRow.run_id == audit_id).first()
        if rr:
            res = session.query(ReasoningResultRow).filter(ReasoningResultRow.run_id == rr.id).all()
            for r in res:
                out.append(ReplayEvent(
                    id=r.id,
                    audit_id=audit_id,
                    event_type=EVENT_VERIFICATION,
                    timestamp=_iso(r.created_at),
                    actor="Reasoning Engine",
                    content=f"{r.reasoning_type}: {r.status} — {(r.explanation or '')[:120]}",
                    evidence_reference=r.evidence_ids_json or "",
                    source="reasoning",
                    evidence_summary=f"{len(_loads(r.supporting_evidence_json, []))} 支持 / {len(_loads(r.counter_evidence_json, []))} 反驳",
                    result_summary=r.status or "",
                ))
    except Exception:  # noqa: BLE101
        pass
    return out


# ---------------------------------------------------------------------------
# ④ Risk Assessment
# ---------------------------------------------------------------------------
def _collect_risk(session: Session, audit_id: str) -> list[ReplayEvent]:
    out: list[ReplayEvent] = []
    try:
        from app.models.risk import RiskAssessmentRow
        rows = session.query(RiskAssessmentRow).filter(RiskAssessmentRow.audit_id == audit_id).all()
        for r in rows:
            out.append(ReplayEvent(
                id=r.id,
                audit_id=audit_id,
                event_type=EVENT_RISK,
                timestamp=_iso(r.created_at),
                actor="Risk Engine",
                content=f"{r.risk_type} [{r.risk_level}] score={r.risk_score} — {(r.risk_reason or '')[:120]}",
                evidence_reference="",
                source="risk",
                evidence_summary="-",
                result_summary=f"{r.risk_level} ({r.risk_score})",
            ))
    except Exception:  # noqa: BLE101
        pass
    return out


# ---------------------------------------------------------------------------
# ⑤ Agent Discussion
# ---------------------------------------------------------------------------
def _collect_agent(session: Session, audit_id: str) -> list[ReplayEvent]:
    out: list[ReplayEvent] = []
    # Arena 4 角色 messages
    if audit_id.startswith("ARENA-"):
        try:
            from app.models.agent_arena import ArenaRunRow, ArenaMessageRow
            run_row = session.query(ArenaRunRow).filter(ArenaRunRow.run_id == audit_id).first()
            if run_row:
                msgs = session.query(ArenaMessageRow).filter(ArenaMessageRow.run_id == run_row.id).order_by(ArenaMessageRow.id.asc()).all()
                for m in msgs:
                    out.append(ReplayEvent(
                        id=m.id,
                        audit_id=audit_id,
                        event_type=EVENT_AGENT,
                        timestamp=_iso(m.created_at),
                        actor=m.role or "Agent",
                        content=(m.content or "")[:200],
                        evidence_reference=m.evidence_json or "",
                        source="arena.agent",
                        evidence_summary=f"viewpoints {len(_loads(m.viewpoints_json, []))} / challenges {len(_loads(m.challenges_json, []))}",
                        result_summary=m.phase or "",
                    ))
        except Exception:  # noqa: BLE101
            pass
    # Committee Report agent_flow
    try:
        from app.models.investment_committee import CommitteeReportRow
        cr = session.query(CommitteeReportRow).filter(CommitteeReportRow.audit_id == audit_id).first()
        if cr:
            flow = _loads(cr.agent_flow_json, [])
            for step in flow[:20]:
                out.append(ReplayEvent(
                    audit_id=audit_id,
                    event_type=EVENT_AGENT,
                    timestamp=_iso(cr.created_at),
                    actor=step.get("agent", "Committee Agent"),
                    content=(step.get("action") or step.get("summary") or "")[:200],
                    evidence_reference=json.dumps(step.get("evidence", []), ensure_ascii=False) if step.get("evidence") else "",
                    source="committee.agent",
                    evidence_summary=f"{len(step.get('evidence', []))} 条证据",
                    result_summary=step.get("status", ""),
                ))
    except Exception:  # noqa: BLE101
        pass
    # Copilot messages（Agent 讨论）
    try:
        from app.models.copilot import CopilotMessageRow
        rows = session.query(CopilotMessageRow).filter(CopilotMessageRow.session_id == audit_id).all()
        for r in rows:
            out.append(ReplayEvent(
                id=r.id,
                audit_id=audit_id,
                event_type=EVENT_AGENT,
                timestamp=r.timestamp or _iso(r.created_at) if hasattr(r, "created_at") else "",
                actor=r.role or "Copilot",
                content=(r.content or "")[:200],
                evidence_reference=r.evidence_json or "",
                source="copilot",
                evidence_summary=f"{len(_loads(r.evidence_json, []))} 条证据",
                result_summary=r.intent_type or "",
            ))
    except Exception:  # noqa: BLE101
        pass
    return out


# ---------------------------------------------------------------------------
# ⑥ Final Conclusion
# ---------------------------------------------------------------------------
def _collect_conclusion(session: Session, audit_id: str) -> list[ReplayEvent]:
    out: list[ReplayEvent] = []
    # Arena Judge final score
    if audit_id.startswith("ARENA-"):
        try:
            from app.models.agent_arena import ArenaRunRow, ArenaResultRow
            run_row = session.query(ArenaRunRow).filter(ArenaRunRow.run_id == audit_id).first()
            if run_row:
                res = session.query(ArenaResultRow).filter(ArenaResultRow.run_id == run_row.id).first()
                if res:
                    score = json.loads(res.score_json or "{}")
                    out.append(ReplayEvent(
                        id=res.id,
                        audit_id=audit_id,
                        event_type=EVENT_CONCLUSION,
                        timestamp=_iso(res.created_at),
                        actor="Judge",
                        content=f"Final Arena Score {res.final_arena_score:.1f} · winner={res.winner}（仅辩论胜负，非投资建议）",
                        evidence_reference=res.score_json or "",
                        source="arena.judge",
                        evidence_summary=f"valid_challenges {len(json.loads(res.auditor_report_json or '{}').get('valid_challenges', []))}",
                        result_summary=f"score {res.final_arena_score:.1f}",
                    ))
        except Exception:  # noqa: BLE101
            pass
    # Committee Report overall
    try:
        from app.models.investment_committee import CommitteeReportRow
        cr = session.query(CommitteeReportRow).filter(CommitteeReportRow.audit_id == audit_id).first()
        if cr:
            out.append(ReplayEvent(
                id=cr.id,
                audit_id=audit_id,
                event_type=EVENT_CONCLUSION,
                timestamp=_iso(cr.created_at),
                actor="Investment Committee",
                content=f"Overall Risk {cr.overall_risk_score} [{cr.overall_risk_level}] · Compliance {cr.overall_compliance_score}（不输出投资建议）",
                evidence_reference="",
                source="committee",
                evidence_summary="-",
                result_summary=f"risk {cr.overall_risk_level}",
            ))
    except Exception:  # noqa: BLE101
        pass
    return out


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _loads(s: str | None, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return default


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.isoformat(timespec="seconds") + "Z"


__all__ = ["collect_events"]
