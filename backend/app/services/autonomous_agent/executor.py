"""Autonomous Investigation Executor（Phase 13）。

执行 InvestigationPlan：依次调用工具，收集证据，更新核验/风险，保存 execution_trace。

流程：
  Plan → Tool Calls → Evidence Collection → Verification → Risk Update

execution_trace 字段（任务书 §4）：
- step / tool / input / output / timestamp

约束：
- 不修改已有 Verification 核心逻辑；保持 Evidence First。
- Agent 根据计划选择调用工具；禁止直接生成事实。
- 不输出投资建议；不自动交易；不替代投资经理。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.autonomous_agent import (
    InvestigationRunRow,
    InvestigationStepRow,
)
from app.services.autonomous_agent.memory import get_memory, upsert_memory
from app.services.autonomous_agent.planner import classify_claim_type, make_plan
from app.services.autonomous_agent.schemas import (
    ClaimContext,
    InvestigationRun,
    InvestigationStep,
    STEP_DONE,
    STEP_FAILED,
    STEP_RUNNING,
    TOOL_ASSESS_RISK,
    TOOL_DETECT_CONFLICTS,
    TOOL_RETRIEVE_EVIDENCE,
    TOOL_VERIFY_CLAIM,
    _now_iso,
    risk_level_of,
)
from app.services.autonomous_agent.tool_registry import build_registry, call_tool


def run_investigation(
    session: Session,
    ctx: ClaimContext,
    use_memory: bool = True,
) -> InvestigationRun:
    """端到端执行自主调查：规划 → 执行工具链 → 汇总证据 → 输出结论。

    返回 InvestigationRun（已持久化）。
    """
    trace_id = f"TRACE-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]}"

    # Step 1: 分类 claim_type 并生成 plan
    if not ctx.claim_type:
        ctx.claim_type = classify_claim_type(ctx.claim_text, ctx.claim)
    plan = make_plan(ctx)

    # Step 2: 查询 Agent Memory（供 Continuous Monitoring 调用）
    memory_used = False
    if use_memory and ctx.company:
        mem = get_memory(session, ctx.company)
        if mem is not None:
            memory_used = True
            # 将历史风险/前序发现注入 plan 第一步的 input
            if plan.steps:
                plan.steps[0].input = {
                    **(plan.steps[0].input or {}),
                    "memory": mem.to_dict(),
                }

    # Step 3: 构造并持久化 run
    run = InvestigationRun(
        trace_id=trace_id,
        claim_context=ctx,
        plan=plan,
        steps=[],
        evidence=[],
        conclusion={},
        memory_used=memory_used,
        created_at=_now_iso(),
    )
    run_row = _persist_run(session, run)

    # Step 4: 执行 plan
    registry = build_registry()
    accumulated_evidence: list[dict] = []
    last_verification: dict = ctx.verification_result or {}
    last_risk: dict = {}

    for plan_step in plan.steps:
        step = InvestigationStep(
            step=plan_step.step,
            tool=plan_step.tool,
            purpose=plan_step.purpose,
            input={},
            output={},
            reasoning="",
            status=STEP_RUNNING,
            timestamp=_now_iso(),
        )

        # 构造本步 input
        step.input = _build_step_input(
            plan_step.tool,
            ctx,
            last_verification,
            accumulated_evidence,
        )

        # 执行工具
        output = call_tool(
            registry,
            session,
            plan_step.tool,
            **_tool_kwargs(plan_step.tool, ctx, last_verification, accumulated_evidence),
        )

        step.output = output
        step.evidence_source = output.get("evidence_source", [])
        step.status = STEP_DONE if "error" not in output else STEP_FAILED

        # 累积证据
        if plan_step.tool == TOOL_RETRIEVE_EVIDENCE:
            ev = output.get("evidence", [])
            accumulated_evidence.extend(ev)
        elif plan_step.tool == TOOL_VERIFY_CLAIM:
            vr = output.get("verification_result", {})
            last_verification = vr
            # 核验结果中的证据也累积
            ev_in_vr = vr.get("evidence", []) if isinstance(vr, dict) else []
            for ev in ev_in_vr:
                if ev not in accumulated_evidence:
                    accumulated_evidence.append(ev)
        elif plan_step.tool == TOOL_ASSESS_RISK:
            last_risk = output.get("risk_assessment", {})
        elif plan_step.tool == TOOL_DETECT_CONFLICTS:
            # 冲突检测可能产生 evidence_source
            pass

        run.steps.append(step)
        # 持久化每步
        _persist_step(session, run_row.id, step)

    # Step 5: 汇总证据与结论
    run.evidence = _summarize_evidence(accumulated_evidence)
    run.conclusion = _build_conclusion(
        ctx,
        last_verification,
        last_risk,
        accumulated_evidence,
    )

    # Step 6: 更新 Agent Memory
    if use_memory and ctx.company:
        upsert_memory(
            session,
            company=ctx.company,
            stock_code=ctx.stock_code,
            historical_risk={
                "risk_score": run.conclusion.get("risk_score", 0.0),
                "risk_level": run.conclusion.get("risk_level", "LOW"),
                "risk_type": run.conclusion.get("risk_type", ""),
            },
            previous_findings=[
                {
                    "trace_id": run.trace_id,
                    "claim": ctx.claim_text,
                    "verification_status": run.conclusion.get("verification_status", ""),
                    "risk_score": run.conclusion.get("risk_score", 0.0),
                }
            ],
            last_investigation_id=run_row.id,
        )

    # 更新 run row 的最终结果
    run_row.trace_id = run.trace_id
    run_row.conclusion_json = json.dumps(run.conclusion, ensure_ascii=False)
    run_row.evidence_json = json.dumps(run.evidence, ensure_ascii=False)
    run_row.steps_json = json.dumps([s.to_dict() for s in run.steps], ensure_ascii=False)
    run_row.plan_json = json.dumps(run.plan.to_dict(), ensure_ascii=False)
    run_row.memory_used = memory_used
    session.commit()
    session.refresh(run_row)
    run.run_id = f"INV-{run_row.id}"
    return run


def get_investigation(session: Session, run_id: int) -> InvestigationRun:
    """按数据库 id 查询调查 run。"""
    row = session.get(InvestigationRunRow, run_id)
    if row is None:
        raise LookupError(f"调查不存在: {run_id}")
    return _run_from_row(session, row)


def list_investigations(session: Session, limit: int = 50) -> list[InvestigationRun]:
    rows = (
        session.query(InvestigationRunRow)
        .order_by(InvestigationRunRow.id.desc())
        .limit(limit)
        .all()
    )
    return [_run_from_row(session, r) for r in rows]


# ---------------------------------------------------------------------------
# 内部：持久化
# ---------------------------------------------------------------------------
def _persist_run(session: Session, run: InvestigationRun) -> InvestigationRunRow:
    row = InvestigationRunRow(
        trace_id=run.trace_id,
        claim_context_json=json.dumps(run.claim_context.to_dict(), ensure_ascii=False),
        plan_json=json.dumps(run.plan.to_dict(), ensure_ascii=False),
        steps_json=json.dumps([], ensure_ascii=False),
        evidence_json=json.dumps([], ensure_ascii=False),
        conclusion_json=json.dumps({}, ensure_ascii=False),
        memory_used=run.memory_used,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _persist_step(session: Session, run_id: int, step: InvestigationStep) -> InvestigationStepRow:
    row = InvestigationStepRow(
        run_id=run_id,
        step=step.step,
        tool=step.tool,
        purpose=step.purpose,
        input_json=json.dumps(step.input, ensure_ascii=False),
        output_json=json.dumps(step.output, ensure_ascii=False),
        reasoning=step.reasoning,
        status=step.status,
        evidence_source_json=json.dumps(step.evidence_source, ensure_ascii=False),
        trace_id="",  # 由 run 统一关联
        result=step.output.get("tool", ""),
        timestamp=step.timestamp,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# 内部：工具输入构造
# ---------------------------------------------------------------------------
def _build_step_input(
    tool: str,
    ctx: ClaimContext,
    last_verification: dict,
    evidence: list[dict],
) -> dict:
    base = {"claim_text": ctx.claim_text, "company": ctx.company}
    if tool == TOOL_RETRIEVE_EVIDENCE:
        return {**base, "claim": ctx.claim, "top_k": 8}
    if tool == TOOL_VERIFY_CLAIM:
        return {**base, "claim": ctx.claim, "top_k": 8}
    if tool == TOOL_ASSESS_RISK:
        return {**base, "claim": ctx.claim, "verification_result": last_verification}
    if tool == TOOL_DETECT_CONFLICTS:
        return {**base, "claim": ctx.claim, "evidence": evidence}
    return base


def _tool_kwargs(
    tool: str,
    ctx: ClaimContext,
    last_verification: dict,
    evidence: list[dict],
) -> dict:
    if tool == TOOL_RETRIEVE_EVIDENCE:
        return {"claim": ctx.claim, "top_k": 8}
    if tool == TOOL_VERIFY_CLAIM:
        return {"claim": ctx.claim, "top_k": 8}
    if tool == TOOL_ASSESS_RISK:
        return {"claim": ctx.claim, "verification_result": last_verification}
    if tool == TOOL_DETECT_CONFLICTS:
        return {"claim": ctx.claim, "evidence": evidence}
    if tool in ("get_company_profile", "get_business_map"):
        return {"company": ctx.company, "stock_code": ctx.stock_code}
    return {}


# ---------------------------------------------------------------------------
# 内部：证据汇总与结论
# ---------------------------------------------------------------------------
def _summarize_evidence(evidence: list[dict]) -> list[dict]:
    """去重并标准化证据列表。"""
    seen = set()
    summary = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        key = ev.get("block_id") or ev.get("evidence_id") or str(ev)
        if key in seen:
            continue
        seen.add(key)
        summary.append({
            "block_id": ev.get("block_id") or ev.get("evidence_id"),
            "page_number": ev.get("page_number"),
            "document_id": ev.get("document_id"),
            "text": (ev.get("text") or ev.get("block_text") or "")[:300],
            "score": ev.get("final_score") or ev.get("score") or 0.0,
            "evidence_type": ev.get("evidence_type", "UNKNOWN"),
        })
    return summary


def _build_conclusion(
    ctx: ClaimContext,
    verification: dict,
    risk: dict,
    evidence: list[dict],
) -> dict:
    """构造调查结论（verification_status / risk_score / risk_type / summary）。"""
    v_status = verification.get("verification_status", "INSUFFICIENT_EVIDENCE")
    r_score = risk.get("risk_score", 0.0)
    r_level = risk_level_of(r_score) if r_score else "LOW"
    r_type = risk.get("risk_type", "")

    summary = (
        f"自主调查主张「{ctx.claim_text[:60]}」"
        f"（类型={ctx.claim_type}），"
        f"调用 {len(evidence)} 条证据，"
        f"核验结论 {v_status}，"
        f"风险分 {r_score}（{r_level}）。"
    )

    return {
        "verification_status": v_status,
        "risk_score": round(r_score, 1),
        "risk_level": r_level,
        "risk_type": r_type,
        "evidence_count": len(evidence),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 内部：Row → dataclass
# ---------------------------------------------------------------------------
def _run_from_row(session: Session, row: InvestigationRunRow) -> InvestigationRun:
    ctx_dict = json.loads(row.claim_context_json or "{}")
    ctx = ClaimContext(
        claim_text=ctx_dict.get("claim_text", ""),
        claim_type=ctx_dict.get("claim_type", ""),
        risk_type=ctx_dict.get("risk_type", ""),
        company=ctx_dict.get("company", ""),
        stock_code=ctx_dict.get("stock_code", ""),
        claim=ctx_dict.get("claim", {}),
        verification_result=ctx_dict.get("verification_result", {}),
    )
    plan_dict = json.loads(row.plan_json or "{}")
    steps_list = json.loads(row.steps_json or "[]")
    ev_list = json.loads(row.evidence_json or "[]")
    concl = json.loads(row.conclusion_json or "{}")

    steps = [
        InvestigationStep(
            step=s.get("step", 0),
            tool=s.get("tool", ""),
            purpose=s.get("purpose", ""),
            input=s.get("input", {}),
            output=s.get("output", {}),
            reasoning=s.get("reasoning", ""),
            status=s.get("status", "DONE"),
            evidence_source=s.get("evidence_source", []),
            timestamp=s.get("timestamp", ""),
        )
        for s in steps_list
    ]

    from app.services.autonomous_agent.planner import InvestigationPlan as _IP

    plan = _IP(
        objective=plan_dict.get("objective", ""),
        claim_type=plan_dict.get("claim_type", ""),
        risk_type=plan_dict.get("risk_type", ""),
        steps=[],  # steps 在 run.steps 中
    )

    return InvestigationRun(
        trace_id=row.trace_id,
        run_id=f"INV-{row.id}",
        claim_context=ctx,
        plan=plan,
        steps=steps,
        evidence=ev_list,
        conclusion=concl,
        memory_used=row.memory_used,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z"
        if row.created_at
        else "",
    )


__all__ = [
    "run_investigation",
    "get_investigation",
    "list_investigations",
]
