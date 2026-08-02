"""FinProof Demo Runner（Phase 22，任务书 §功能 start_demo）。

start_demo(company, report_id)：编排 8 步已有流程 → DemoRun。
仅编排已有模块，**不新增分析能力**。保持 Evidence First；不生成投资建议。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.demo_mode import DemoRunRow, DemoStepRow
from app.services.demo_mode.demo_steps import (
    step_assess_risk,
    step_build_replay,
    step_extract_claims,
    step_generate_dashboard,
    step_retrieve_evidence,
    step_run_arena,
    step_run_reasoning,
    step_verify_claims,
)
from app.services.demo_mode.schemas import (
    BACKEND_STEPS,
    DEMO_COMPANY,
    DEMO_REPORT_TITLE,
    DEMO_SCENARIOS,
    DemoRun,
    DemoStep,
    _now_iso,
)


def start_demo(session: Session, company: str, report_id: str = "") -> DemoRun:
    """启动演示：自动执行 8 步已有流程，每步记录 DemoStep，最终输出 3 项。"""
    if not company:
        company = DEMO_COMPANY  # 固定 Demo Case（任务书 §Demo Case）

    # Phase 23.6 修复：原 demo_id = DEMO-{秒级时间戳} 在同秒连续启动时重复，
    # 触发 demo_runs.demo_id UNIQUE 约束冲突导致 HTTP 422。
    # 修复：加入 uuid4 短后缀保证全局唯一，支持连续/并发运行。
    import uuid as _uuid
    demo_id = f"DEMO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{_uuid.uuid4().hex[:8]}"
    run = DemoRun(
        demo_id=demo_id,
        company=company,
        report_id=report_id,
        status="RUNNING",
        current_step=BACKEND_STEPS[0],
        created_at=_now_iso(),
    )

    # ① extract_claims
    s1 = step_extract_claims(session, company, report_id)
    run.steps.append(s1)
    run.current_step = BACKEND_STEPS[1]
    prev_out = s1.output_reference

    # ② retrieve_evidence
    s2 = step_retrieve_evidence(session, company, prev_out)
    run.steps.append(s2)
    run.current_step = BACKEND_STEPS[2]
    prev_out = s2.output_reference

    # ③ verify_claims
    s3 = step_verify_claims(session, company, prev_out)
    run.steps.append(s3)
    run.current_step = BACKEND_STEPS[3]

    # ④ assess_risk
    s4 = step_assess_risk(session, company, prev_out)
    run.steps.append(s4)
    run.current_step = BACKEND_STEPS[4]

    # ⑤ run_reasoning
    s5 = step_run_reasoning(session, company, prev_out)
    run.steps.append(s5)
    run.current_step = BACKEND_STEPS[5]

    # ⑥ run_arena
    research_question = f"{company} 海外增长是否可持续"
    s6 = step_run_arena(session, company, research_question)
    run.steps.append(s6)
    run.arena_run_id = s6.output_reference
    run.current_step = BACKEND_STEPS[6]

    # ⑦ generate_dashboard
    s7 = step_generate_dashboard(session, company)
    run.steps.append(s7)
    run.dashboard_id = s7.output_reference
    run.current_step = BACKEND_STEPS[7]

    # ⑧ build_replay（基于 arena run id）
    s8 = step_build_replay(session, run.arena_run_id)
    run.steps.append(s8)
    run.audit_replay_id = run.arena_run_id  # replay audit_id = arena run id

    # 最终输出（任务书 §最后展示）
    run.reliability_score = _compute_reliability(s6, s7)
    run.risk_findings = _collect_risk_findings(session, company)
    run.audit_replay = _load_replay(session, run.audit_replay_id)
    run.status = "DONE"
    run.finished_at = _now_iso()
    run.current_step = "DONE"

    _persist(session, run)
    return run


def get_demo(session: Session, demo_id: str) -> DemoRun:
    """按 demo_id 查询 DemoRun（含 steps + 最终输出）。"""
    row = session.query(DemoRunRow).filter(DemoRunRow.demo_id == demo_id).first()
    if row is None:
        raise LookupError(f"演示不存在: {demo_id}")
    return _run_from_row(session, row)


def get_demo_steps(session: Session, demo_id: str) -> list[DemoStep]:
    """按 demo_id 查询步骤列表。"""
    row = session.query(DemoRunRow).filter(DemoRunRow.demo_id == demo_id).first()
    if row is None:
        raise LookupError(f"演示不存在: {demo_id}")
    step_rows = (
        session.query(DemoStepRow)
        .filter(DemoStepRow.demo_id == row.id)
        .order_by(DemoStepRow.step_number.asc())
        .all()
    )
    return [
        DemoStep(
            step_number=r.step_number,
            name=r.name,
            frontend_label=r.frontend_label or "",
            status=r.status,
            duration=r.duration or 0,
            input_reference=r.input_reference or "",
            output_reference=r.output_reference or "",
            source=r.source or "",
            evidence=r.evidence or "",
            result=r.result or "",
            error=r.error or "",
        )
        for r in step_rows
    ]


def list_demos(session: Session, limit: int = 50) -> list[dict]:
    """列出最近演示（元数据）。"""
    rows = (
        session.query(DemoRunRow)
        .order_by(DemoRunRow.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "demo_id": r.demo_id,
            "company": r.company,
            "status": r.status,
            "current_step": r.current_step,
            "reliability_score": r.reliability_score,
            "created_at": (r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 内部：最终输出计算
# ---------------------------------------------------------------------------
def _compute_reliability(arena_step: DemoStep, dashboard_step: DemoStep) -> float:
    """AI 可靠性评分 = Arena Score × 0.6 + Dashboard reliability × 0.4。"""
    arena_score = 0.0
    if arena_step.result and "Final Score" in arena_step.result:
        try:
            arena_score = float(arena_step.result.split("Final Score")[1].split("·")[0].strip())
        except Exception:  # noqa: BLE101
            pass
    dash_score = 0.0
    if dashboard_step.result and "reliability" in dashboard_step.result:
        try:
            dash_score = float(dashboard_step.result.split("reliability")[1].split("·")[0].strip())
        except Exception:  # noqa: BLE101
            pass
    return arena_score * 0.6 + dash_score * 0.4


def _collect_risk_findings(session: Session, company: str) -> list[dict]:
    """收集风险条目（来自既有 Risk Engine 产出，不新增分析）。"""
    findings: list[dict] = []
    try:
        from app.models.risk import RiskAssessmentRow
        rows = (
            session.query(RiskAssessmentRow)
            .filter(RiskAssessmentRow.audit_id.like(f"%{company}%"))
            .limit(10)
            .all()
        )
        for r in rows:
            findings.append({
                "risk_id": f"RISK-{r.id}",
                "risk_type": r.risk_type or "",
                "level": r.risk_level or "",
                "score": float(r.risk_score or 0.0),
                "reason": (r.risk_reason or "")[:200],
                "status": r.verification_status or "",
            })
    except Exception:  # noqa: BLE101
        pass
    # 若库中无该公司风险条目，注入 3 个 Demo Case 场景（任务书 §Demo Case 展示）
    if not findings:
        findings = [
            {"risk_id": "DEMO-RISK-1", "risk_type": "FINANCIAL", "level": "HIGH", "score": 75.0,
             "reason": "错误财务增长率：海外利润增长率与营收增长率口径不一致", "status": "REFUTED"},
            {"risk_id": "DEMO-RISK-2", "risk_type": "SEMANTIC", "level": "MEDIUM", "score": 60.0,
             "reason": "战略夸大：'海外业务是利润增长核心引擎'缺多期数据支撑", "status": "PARTIALLY_SUPPORTED"},
            {"risk_id": "DEMO-RISK-3", "risk_type": "EVIDENCE", "level": "HIGH", "score": 80.0,
             "reason": "证据不足：增长可持续性主张未绑定现金流/应收/存货交叉证据", "status": "INSUFFICIENT"},
        ]
    return findings


def _load_replay(session: Session, audit_replay_id: str) -> dict:
    """加载审计回放时间线（来自 Replay service，不新增）。"""
    if not audit_replay_id:
        return {}
    try:
        from app.services.replay.service import get_replay
        tl = get_replay(session, audit_replay_id)
        return tl.to_dict()
    except Exception:  # noqa: BLE101
        return {}


# ---------------------------------------------------------------------------
# 内部：持久化
# ---------------------------------------------------------------------------
def _persist(session: Session, run: DemoRun) -> None:
    run_row = DemoRunRow(
        demo_id=run.demo_id,
        company=run.company,
        report_id=run.report_id,
        status=run.status,
        current_step=run.current_step,
        reliability_score=run.reliability_score,
        arena_run_id=run.arena_run_id,
        dashboard_id=run.dashboard_id,
        audit_replay_id=run.audit_replay_id,
        created_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
    )
    session.add(run_row)
    session.flush()
    db_id = run_row.id

    for s in run.steps:
        session.add(DemoStepRow(
            demo_id=db_id,
            step_number=s.step_number,
            name=s.name,
            frontend_label=s.frontend_label,
            status=s.status,
            duration=s.duration,
            input_reference=s.input_reference,
            output_reference=s.output_reference,
            source=s.source,
            evidence=s.evidence,
            result=s.result,
            error=s.error,
            created_at=datetime.utcnow(),
        ))

    # 最终输出 JSON 持久化
    run_row.risk_findings_json = json.dumps(run.risk_findings, ensure_ascii=False)
    run_row.audit_replay_json = json.dumps(run.audit_replay, ensure_ascii=False)
    session.commit()


def _run_from_row(session: Session, row: DemoRunRow) -> DemoRun:
    steps = get_demo_steps(session, row.demo_id)
    risk_findings = []
    if row.risk_findings_json:
        try:
            risk_findings = json.loads(row.risk_findings_json)
        except Exception:  # noqa: BLE101
            pass
    audit_replay = {}
    if row.audit_replay_json:
        try:
            audit_replay = json.loads(row.audit_replay_json)
        except Exception:  # noqa: BLE101
            pass
    return DemoRun(
        demo_id=row.demo_id,
        company=row.company,
        report_id=row.report_id or "",
        status=row.status,
        current_step=row.current_step or "",
        steps=steps,
        reliability_score=row.reliability_score or 0.0,
        risk_findings=risk_findings,
        audit_replay_id=row.audit_replay_id or "",
        audit_replay=audit_replay,
        arena_run_id=row.arena_run_id or "",
        dashboard_id=row.dashboard_id or "",
        created_at=(row.created_at.isoformat(timespec="seconds") + "Z") if row.created_at else "",
        finished_at=(row.finished_at.isoformat(timespec="seconds") + "Z") if row.finished_at else "",
    )


__all__ = ["start_demo", "get_demo", "get_demo_steps", "list_demos"]
