"""FinProof Arena Orchestrator（Phase 19，任务书 §Workflow）。

输入：company + research_question
流程：Analyst 观点 → Skeptic 挑战 → Auditor 审计 → Judge 评分 → 保存 ArenaReport
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.agent_arena import ArenaMessageRow, ArenaResultRow, ArenaRunRow
from app.services.agent_arena.analyst_agent import generate_viewpoints
from app.services.agent_arena.auditor_agent import audit_debate
from app.services.agent_arena.judge import decide_winner, score_arena
from app.services.agent_arena.schemas import (
    ArenaMessage,
    ArenaResult,
    ArenaRun,
    ArenaScore,
    PHASE_ANALYST,
    PHASE_AUDITOR_VERIFIES,
    PHASE_JUDGE_SCORES,
    PHASE_SKEPTIC_ATTACKS,
    PHARE_DONE,
    ROLE_JUDGE,
    _now_iso,
)
from app.services.agent_arena.skeptic_agent import challenge_viewpoints


def run_arena(session: Session, company: str, research_question: str) -> ArenaRun:
    """执行竞技流程：4 角色 Agent 依次产出 → 评分 → 持久化。"""
    if not company:
        raise ValueError("company 不能为空")
    if not research_question:
        raise ValueError("research_question 不能为空")

    run_id = f"ARENA-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]}"
    messages: list[ArenaMessage] = []

    run = ArenaRun(
        run_id=run_id,
        company=company,
        research_question=research_question,
        phase=PHASE_ANALYST,
        messages=messages,
        created_at=_now_iso(),
    )

    # ① Analyst 生成观点
    viewpoints, all_evidence, analyst_msg = generate_viewpoints(session, company, research_question)
    messages.append(analyst_msg)
    run.phase = PHASE_SKEPTIC_ATTACKS

    # ② Skeptic 挑战
    challenges, skeptic_msg = challenge_viewpoints(session, viewpoints, company)
    messages.append(skeptic_msg)
    run.phase = PHASE_AUDITOR_VERIFIES

    # ③ Auditor 审计
    auditor_report, auditor_msg = audit_debate(viewpoints, challenges, all_evidence)
    messages.append(auditor_msg)
    run.phase = PHASE_JUDGE_SCORES

    # ④ Judge 评分
    score = score_arena(viewpoints, challenges, auditor_report, tool_call_count=sum(1 for m in messages if m.viewpoints or m.challenges))
    winner = decide_winner(score, viewpoints, challenges, auditor_report)
    judge_msg = ArenaMessage(
        message_id="MSG-004",
        role=ROLE_JUDGE,
        phase=PHASE_JUDGE_SCORES,
        content=f"Judge 评分：Final Arena Score {score.final_arena_score:.1f} · 辩论胜负={winner}。",
        timestamp=_now_iso(),
    )
    messages.append(judge_msg)

    # ⑤ ArenaReport
    result = ArenaResult(
        result_id=f"AR-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:16]}",
        run_id=run_id,
        analyst_viewpoints=viewpoints,
        skeptic_challenges=challenges,
        auditor_report=auditor_report,
        score=score,
        winner=winner,
        created_at=_now_iso(),
    )
    run.result = result
    run.phase = PHARE_DONE
    run.finished_at = _now_iso()

    _persist(session, run)
    return run


def get_arena(session: Session, arena_id: int) -> ArenaRun:
    """按数据库 id 查询 ArenaRun（含 messages + result）。"""
    row = session.get(ArenaRunRow, arena_id)
    if row is None:
        raise LookupError(f"竞技运行不存在: {arena_id}")
    return _run_from_row(session, row)


def list_arena(session: Session, limit: int = 50) -> list[ArenaRun]:
    """列出最近竞技运行（仅元数据）。"""
    rows = (
        session.query(ArenaRunRow)
        .order_by(ArenaRunRow.id.desc())
        .limit(limit)
        .all()
    )
    return [_run_from_row(session, r, with_details=False) for r in rows]


# ---------------------------------------------------------------------------
# 内部：持久化
# ---------------------------------------------------------------------------
def _persist(session: Session, run: ArenaRun) -> None:
    run_row = ArenaRunRow(
        run_id=run.run_id,
        company=run.company,
        research_question=run.research_question,
        phase=run.phase,
        created_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
    )
    session.add(run_row)
    session.flush()
    run_db_id = run_row.id

    for msg in run.messages:
        session.add(ArenaMessageRow(
            run_id=run_db_id,
            message_id=msg.message_id,
            role=msg.role,
            phase=msg.phase,
            content=msg.content,
            viewpoints_json=json.dumps([v.to_dict() for v in msg.viewpoints], ensure_ascii=False),
            challenges_json=json.dumps([c.to_dict() for c in msg.challenges], ensure_ascii=False),
            audit_json=json.dumps(msg.audit.to_dict() if msg.audit else {}, ensure_ascii=False),
            evidence_json=json.dumps([e.to_dict() for e in msg.evidence], ensure_ascii=False),
            created_at=datetime.utcnow(),
        ))

    if run.result:
        r = run.result
        session.add(ArenaResultRow(
            run_id=run_db_id,
            result_id=r.result_id,
            analyst_viewpoints_json=json.dumps([v.to_dict() for v in r.analyst_viewpoints], ensure_ascii=False),
            skeptic_challenges_json=json.dumps([c.to_dict() for c in r.skeptic_challenges], ensure_ascii=False),
            auditor_report_json=json.dumps(r.auditor_report.to_dict() if r.auditor_report else {}, ensure_ascii=False),
            score_json=json.dumps(r.score.to_dict(), ensure_ascii=False),
            final_arena_score=r.score.final_arena_score,
            winner=r.winner,
            created_at=datetime.utcnow(),
        ))

    session.commit()


def _run_from_row(session: Session, row: ArenaRunRow, with_details: bool = True) -> ArenaRun:
    def _loads(s, default):
        if not s:
            return default
        try:
            return json.loads(s)
        except Exception:  # noqa: BLE001
            return default

    messages: list[ArenaMessage] = []
    result = None
    if with_details:
        msg_rows = (
            session.query(ArenaMessageRow)
            .filter(ArenaMessageRow.run_id == row.id)
            .order_by(ArenaMessageRow.id.asc())
            .all()
        )
        for mr in msg_rows:
            from app.services.agent_arena.schemas import (
                AnalystViewpoint, AuditorIssue, AuditorReport, EvidenceRef, SkepticChallenge,
            )
            vps = [AnalystViewpoint(
                viewpoint_id=v.get("viewpoint_id", ""),
                claim=v.get("claim", ""),
                evidence=[EvidenceRef(block_id=e.get("block_id"), document_id=e.get("document_id"), page_number=e.get("page_number"), text=e.get("text")) for e in v.get("evidence", [])],
                confidence=v.get("confidence", 0.0),
                metric=v.get("metric", ""),
                unsupported=v.get("unsupported", False),
            ) for v in _loads(mr.viewpoints_json, [])]
            chs = [SkepticChallenge(
                challenge_id=c.get("challenge_id", ""),
                target_viewpoint_id=c.get("target_viewpoint_id", ""),
                challenge_type=c.get("challenge_type", ""),
                counter_claim=c.get("counter_claim", ""),
                missing_evidence=c.get("missing_evidence", ""),
                risk=c.get("risk", ""),
                evidence=[EvidenceRef(block_id=e.get("block_id")) for e in c.get("evidence", [])],
                risk_score=c.get("risk_score", 0.0),
                valid=c.get("valid", True),
            ) for c in _loads(mr.challenges_json, [])]
            audit_dict = _loads(mr.audit_json, {})
            audit = AuditorReport(
                audit_score=audit_dict.get("audit_score", 0.0),
                issues=[AuditorIssue(issue_id=i.get("issue_id"), issue_type=i.get("issue_type"), description=i.get("description"), affected=i.get("affected")) for i in audit_dict.get("issues", [])],
                evidence_coverage=audit_dict.get("evidence_coverage", 0.0),
                logical_consistency=audit_dict.get("logical_consistency", 0.0),
                risk_completeness=audit_dict.get("risk_completeness", 0.0),
                valid_challenges=audit_dict.get("valid_challenges", []),
                invalid_challenges=audit_dict.get("invalid_challenges", []),
            ) if audit_dict else None
            messages.append(ArenaMessage(
                message_id=mr.message_id,
                role=mr.role,
                phase=mr.phase,
                content=mr.content,
                viewpoints=vps,
                challenges=chs,
                audit=audit,
                evidence=[EvidenceRef(block_id=e.get("block_id"), text=e.get("text")) for e in _loads(mr.evidence_json, [])],
                timestamp=mr.created_at.isoformat(timespec="seconds") + "Z" if mr.created_at else "",
            ))

        result_row = (
            session.query(ArenaResultRow)
            .filter(ArenaResultRow.run_id == row.id)
            .first()
        )
        if result_row:
            from app.services.agent_arena.schemas import (
                AnalystViewpoint, ArenaScore, AuditorIssue, AuditorReport, EvidenceRef, ScoreBreakdown, SkepticChallenge,
            )
            score_dict = _loads(result_row.score_json, {})
            audit_dict = _loads(result_row.auditor_report_json, {})
            result = ArenaResult(
                result_id=result_row.result_id,
                run_id=row.run_id,
                analyst_viewpoints=[AnalystViewpoint(viewpoint_id=v.get("viewpoint_id"), claim=v.get("claim"), unsupported=v.get("unsupported")) for v in _loads(result_row.analyst_viewpoints_json, [])],
                skeptic_challenges=[SkepticChallenge(challenge_id=c.get("challenge_id"), target_viewpoint_id=c.get("target_viewpoint_id"), challenge_type=c.get("challenge_type"), counter_claim=c.get("counter_claim"), valid=c.get("valid")) for c in _loads(result_row.skeptic_challenges_json, [])],
                auditor_report=AuditorReport(
                    audit_score=audit_dict.get("audit_score", 0.0),
                    issues=[AuditorIssue(issue_id=i.get("issue_id"), issue_type=i.get("issue_type"), description=i.get("description"), affected=i.get("affected")) for i in audit_dict.get("issues", [])],
                    evidence_coverage=audit_dict.get("evidence_coverage", 0.0),
                    logical_consistency=audit_dict.get("logical_consistency", 0.0),
                    risk_completeness=audit_dict.get("risk_completeness", 0.0),
                ),
                score=ArenaScore(
                    analyst_quality=ScoreBreakdown(score=score_dict.get("analyst_quality", {}).get("score", 0)),
                    skeptic_detection=ScoreBreakdown(score=score_dict.get("skeptic_detection", {}).get("score", 0)),
                    auditor_reliability=ScoreBreakdown(score=score_dict.get("auditor_reliability", {}).get("score", 0)),
                    evidence_score=ScoreBreakdown(score=score_dict.get("evidence_score", {}).get("score", 0)),
                    reasoning_score=ScoreBreakdown(score=score_dict.get("reasoning_score", {}).get("score", 0)),
                    risk_detection_score=ScoreBreakdown(score=score_dict.get("risk_detection_score", {}).get("score", 0)),
                    efficiency_score=ScoreBreakdown(score=score_dict.get("efficiency_score", {}).get("score", 0)),
                    safety_score=ScoreBreakdown(score=score_dict.get("safety_score", {}).get("score", 0)),
                    final_arena_score=score_dict.get("final_arena_score", 0.0),
                ),
                winner=result_row.winner or "",
                created_at=result_row.created_at.isoformat(timespec="seconds") + "Z" if result_row.created_at else "",
            )

    return ArenaRun(
        run_id=row.run_id,
        company=row.company,
        research_question=row.research_question,
        phase=row.phase,
        messages=messages,
        result=result,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z" if row.created_at else "",
        finished_at=row.finished_at.isoformat(timespec="seconds") + "Z" if row.finished_at else "",
    )


__all__ = ["run_arena", "get_arena", "list_arena"]
