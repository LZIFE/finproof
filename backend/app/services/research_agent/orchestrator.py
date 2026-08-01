"""FinProof Autonomous Research Agent Service（Phase 17，主调度器）。

主入口：run_research —— 从公司名出发，依次执行
  Planning → Collecting Evidence → Analyzing → Risk Checking → Memo Generated，
  返回 ResearchSession（含 plan / progress / findings / evidence / memo），持久化到
  research_sessions / research_tasks。

约束：不生成投资建议；不做股票推荐；不做自动交易；不修改 Verification 核心逻辑。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.research_agent import ResearchSessionRow, ResearchTaskRow
from app.services.research_agent.analyst import analyze_findings
from app.services.research_agent.collector import collect_evidence
from app.services.research_agent.memo_generator import generate_memo
from app.services.research_agent.planner import make_plan
from app.services.research_agent.schemas import (
    EvidenceRef,
    PHASE_ANALYZING,
    PHASE_COLLECTING,
    PHASE_MEMO_GENERATED,
    PHASE_PLANNING,
    PHASE_RISK_CHECKING,
    ResearchFinding,
    ResearchSession,
    RiskFinding,
    ToolCall,
    TASK_DONE,
    TASK_SKIPPED,
    _now_iso,
)


def run_research(session: Session, company: str, stock_code: str = "") -> ResearchSession:
    """从公司名启动自主研究流程，返回 ResearchSession（已持久化）。

    流程：
      1. Planning        make_plan
      2. Collecting      collect_evidence（Evidence Retrieval + Knowledge Graph）
      3. Analyzing       analyze_findings（ResearchFinding + RiskFinding）
      4. Risk Checking   （风险发现已在 analyze 内完成）
      5. Memo Generated  generate_memo
    """
    if not company:
        raise ValueError("company 不能为空")

    session_id = f"RESEARCH-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]}"
    tasks_status: dict[str, str] = {}
    tool_calls: list[ToolCall] = []

    # ① Planning
    plan = make_plan(company, stock_code)
    for spec in plan.tasks:
        tasks_status[spec.task_type] = "PENDING"

    research_session = ResearchSession(
        session_id=session_id,
        company=company,
        stock_code=stock_code,
        plan=plan,
        phase=PHASE_PLANNING,
        tasks_status=tasks_status,
        tool_calls=tool_calls,
        created_at=_now_iso(),
    )
    session_row = _persist_session_start(session, research_session)

    # ② Collecting Evidence
    research_session.phase = PHASE_COLLECTING
    evidence_by_task = collect_evidence(session, plan, tasks_status, tool_calls)

    # ③ Analyzing
    research_session.phase = PHASE_ANALYZING
    findings, risk_findings = analyze_findings(session, plan, evidence_by_task, tool_calls)

    # ④ Risk Checking（风险发现已在 analyze 内调用 risk/reasoning/monitoring 完成）
    research_session.phase = PHASE_RISK_CHECKING
    research_session.findings = findings
    research_session.risk_findings = risk_findings

    # ⑤ Memo Generated
    research_session.phase = PHASE_MEMO_GENERATED
    memo = generate_memo(plan, findings, risk_findings, tasks_status, tool_calls)
    research_session.memo = memo
    research_session.finished_at = _now_iso()

    # 持久化完成态 + 任务详情
    _persist_session_finish(session, session_row, research_session, evidence_by_task)
    return research_session


def get_research(session: Session, research_id: int) -> ResearchSession:
    """按数据库 id 查询 ResearchSession（含 plan / progress / findings / evidence / memo）。"""
    row = session.get(ResearchSessionRow, research_id)
    if row is None:
        raise LookupError(f"研究会话不存在: {research_id}")
    return _session_from_row(session, row)


def list_research(session: Session, limit: int = 50) -> list[ResearchSession]:
    """列出最近研究会话（仅元数据）。"""
    rows = (
        session.query(ResearchSessionRow)
        .order_by(ResearchSessionRow.id.desc())
        .limit(limit)
        .all()
    )
    return [_session_from_row(session, r, with_details=False) for r in rows]


# ---------------------------------------------------------------------------
# 内部：持久化
# ---------------------------------------------------------------------------
def _persist_session_start(session: Session, rs: ResearchSession) -> ResearchSessionRow:
    """持久化研究会话起始态（plan + phase=Planning）。"""
    row = ResearchSessionRow(
        session_id=rs.session_id,
        company=rs.company,
        stock_code=rs.stock_code,
        phase=rs.phase,
        plan_json=json.dumps(rs.plan.to_dict() if rs.plan else {}, ensure_ascii=False),
        tasks_count=len(rs.tasks_status),
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    return row


def _persist_session_finish(
    session: Session,
    row: ResearchSessionRow,
    rs: ResearchSession,
    evidence_by_task: dict[str, list[EvidenceRef]],
) -> None:
    """持久化完成态：tool_calls / findings / risk_findings / memo + 任务详情。"""
    row.phase = rs.phase
    row.tool_calls_json = json.dumps([t.to_dict() for t in rs.tool_calls], ensure_ascii=False)
    row.findings_json = json.dumps([f.to_dict() for f in rs.findings], ensure_ascii=False)
    row.risk_findings_json = json.dumps([r.to_dict() for r in rs.risk_findings], ensure_ascii=False)
    row.memo_json = json.dumps(rs.memo.to_dict() if rs.memo else {}, ensure_ascii=False)
    row.evidence_count = sum(len(v) for v in evidence_by_task.values())
    row.tasks_done = sum(1 for s in rs.tasks_status.values() if s == TASK_DONE)
    row.finished_at = datetime.utcnow()
    session.add(row)

    # 任务详情
    for spec in (rs.plan.tasks if rs.plan else []):
        ev = evidence_by_task.get(spec.task_type, [])
        task_findings = [f for f in rs.findings if f.task_type == spec.task_type]
        task_tool_calls = [t for t in rs.tool_calls if t.task_type == spec.task_type]
        task_row = ResearchTaskRow(
            session_id=row.id,
            task_type=spec.task_type,
            category=spec.category,
            metric=spec.metric,
            objective=spec.objective,
            status=rs.tasks_status.get(spec.task_type, "PENDING"),
            evidence_json=json.dumps([e.to_dict() for e in ev], ensure_ascii=False),
            findings_json=json.dumps([f.to_dict() for f in task_findings], ensure_ascii=False),
            tool_calls_json=json.dumps([t.to_dict() for t in task_tool_calls], ensure_ascii=False),
            finished_at=datetime.utcnow() if rs.tasks_status.get(spec.task_type) in (TASK_DONE, TASK_SKIPPED) else None,
        )
        session.add(task_row)

    session.commit()


def _session_from_row(session: Session, row: ResearchSessionRow, with_details: bool = True) -> ResearchSession:
    """从数据库 row 构造 ResearchSession。"""
    def _loads(s, default):
        if not s:
            return default
        try:
            return json.loads(s)
        except Exception:  # noqa: BLE001
            return default

    plan_dict = _loads(row.plan_json, {})
    plan = None
    if plan_dict:
        from app.services.research_agent.schemas import ResearchPlan, ResearchTaskSpec
        plan = ResearchPlan(
            company=plan_dict.get("company", row.company),
            stock_code=plan_dict.get("stock_code", row.stock_code),
            tasks=[ResearchTaskSpec(
                task_type=t.get("task_type", ""),
                category=t.get("category", ""),
                objective=t.get("objective", ""),
                claim_query=t.get("claim_query", ""),
                metric=t.get("metric", ""),
                need_knowledge_graph=t.get("need_knowledge_graph", False),
                need_reasoning=t.get("need_reasoning", False),
                need_monitoring=t.get("need_monitoring", False),
            ) for t in plan_dict.get("tasks", [])],
            created_at=plan_dict.get("created_at", ""),
        )

    tool_calls = [ToolCall(
        tool=t.get("tool", ""),
        task_type=t.get("task_type", ""),
        input_summary=t.get("input_summary", ""),
        output_summary=t.get("output_summary", ""),
        evidence_count=t.get("evidence_count", 0),
        success=t.get("success", True),
        timestamp=t.get("timestamp", ""),
    ) for t in _loads(row.tool_calls_json, [])] if with_details else []

    findings = [ResearchFinding(
        task_type=f.get("task_type", ""),
        metric=f.get("metric", ""),
        content=f.get("content", ""),
        evidence=[EvidenceRef(
            block_id=e.get("block_id", ""),
            document_id=e.get("document_id", ""),
            page_number=e.get("page_number", ""),
            text=e.get("text", ""),
            final_score=e.get("final_score", 0.0),
            evidence_type=e.get("evidence_type", ""),
            evidence_tier=e.get("evidence_tier", ""),
        ) for e in f.get("evidence", [])],
        supported=f.get("supported", True),
        risk_score=f.get("risk_score", 0.0),
        risk_level=f.get("risk_level", "LOW"),
        notes=f.get("notes", ""),
    ) for f in _loads(row.findings_json, [])] if with_details else []

    risk_findings = [RiskFinding(
        risk_type=r.get("risk_type", ""),
        source_tool=r.get("source_tool", ""),
        content=r.get("content", ""),
        evidence=[EvidenceRef(
            block_id=e.get("block_id", ""),
            document_id=e.get("document_id", ""),
            page_number=e.get("page_number", ""),
            text=e.get("text", ""),
        ) for e in r.get("evidence", [])],
        risk_score=r.get("risk_score", 0.0),
        risk_level=r.get("risk_level", "LOW"),
        logical_gap=r.get("logical_gap", ""),
    ) for r in _loads(row.risk_findings_json, [])] if with_details else []

    memo_dict = _loads(row.memo_json, {}) if with_details else {}
    memo = None
    if memo_dict:
        from app.services.research_agent.schemas import ResearchMemo
        memo = ResearchMemo(
            company=memo_dict.get("company", row.company),
            stock_code=memo_dict.get("stock_code", row.stock_code),
            company_overview=memo_dict.get("company_overview", ""),
            key_facts=[ResearchFinding(
                task_type=f.get("task_type", ""), metric=f.get("metric", ""),
                content=f.get("content", ""), supported=f.get("supported", True),
            ) for f in memo_dict.get("key_facts", [])],
            financial_facts=[ResearchFinding(
                task_type=f.get("task_type", ""), metric=f.get("metric", ""),
                content=f.get("content", ""), supported=f.get("supported", True),
            ) for f in memo_dict.get("financial_facts", [])],
            business_facts=[ResearchFinding(
                task_type=f.get("task_type", ""), metric=f.get("metric", ""),
                content=f.get("content", ""), supported=f.get("supported", True),
            ) for f in memo_dict.get("business_facts", [])],
            risk_findings=[RiskFinding(
                risk_type=r.get("risk_type", ""), source_tool=r.get("source_tool", ""),
                content=r.get("content", ""), logical_gap=r.get("logical_gap", ""),
            ) for r in memo_dict.get("risk_findings", [])],
            evidence_chain=[EvidenceRef(
                block_id=e.get("block_id", ""), document_id=e.get("document_id", ""),
                page_number=e.get("page_number", ""), text=e.get("text", ""),
            ) for e in memo_dict.get("evidence_chain", [])],
            open_questions=memo_dict.get("open_questions", []),
            evidence_coverage=memo_dict.get("evidence_coverage", 0.0),
            unsupported_claim_rate=memo_dict.get("unsupported_claim_rate", 0.0),
            task_completion_rate=memo_dict.get("task_completion_rate", 0.0),
            generated_at=memo_dict.get("generated_at", ""),
        )

    return ResearchSession(
        session_id=row.session_id,
        company=row.company,
        stock_code=row.stock_code,
        plan=plan,
        phase=row.phase,
        tool_calls=tool_calls,
        findings=findings,
        risk_findings=risk_findings,
        memo=memo,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z" if row.created_at else "",
        finished_at=row.finished_at.isoformat(timespec="seconds") + "Z" if row.finished_at else "",
    )


__all__ = ["run_research", "get_research", "list_research"]
