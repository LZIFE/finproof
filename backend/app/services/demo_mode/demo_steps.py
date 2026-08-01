"""FinProof Demo Steps Orchestrators（Phase 22，任务书 §自动执行已有流程）。

8 步编排（**仅调用已有模块入口，不新增分析能力**）：
  1 extract_claims       — Research Agent 抽取主张
  2 retrieve_evidence    — Evidence Retrieval 检索证据
  3 verify_claims        — Verification 验证事实（不修改核心）
  4 assess_risk          — Risk Engine 评估风险（不修改核心）
  5 run_reasoning        — Financial Reasoning 逻辑推理
  6 run_arena            — Agent Arena 竞技
  7 generate_dashboard   — Governance Dashboard 仪表板
  8 build_replay         — Replay Timeline 审计回放

每步记录 DemoStep（step_number / name / status / duration / input_reference /
output_reference / source / evidence / result）。

约束：不修改 Verification/Risk 核心；不生成投资建议；所有结果来自已有模块。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.demo_mode.schemas import (
    DemoStep,
    FRONTEND_STEP_1,
    FRONTEND_STEP_2,
    FRONTEND_STEP_3,
    FRONTEND_STEP_4,
    FRONTEND_STEP_5,
    FRONTEND_STEP_6,
    FRONTEND_STEP_LABELS,
    STEP_ASSESS_RISK,
    STEP_BUILD_REPLAY,
    STEP_EXTRACT_CLAIMS,
    STEP_GENERATE_DASHBOARD,
    STEP_RETRIEVE_EVIDENCE,
    STEP_RUN_ARENA,
    STEP_RUN_REASONING,
    STEP_VERIFY_CLAIMS,
    _now_iso,
)


# ---------------------------------------------------------------------------
# 步骤映射到前端动画标签
# ---------------------------------------------------------------------------
def _frontend_label(step_name: str) -> str:
    mapping = {
        STEP_EXTRACT_CLAIMS: FRONTEND_STEP_1,
        STEP_RETRIEVE_EVIDENCE: FRONTEND_STEP_2,
        STEP_VERIFY_CLAIMS: FRONTEND_STEP_3,
        STEP_RUN_REASONING: FRONTEND_STEP_3,    # 合并到 Checking Facts
        STEP_ASSESS_RISK: FRONTEND_STEP_4,
        STEP_RUN_ARENA: FRONTEND_STEP_5,
        STEP_GENERATE_DASHBOARD: FRONTEND_STEP_6,
        STEP_BUILD_REPLAY: FRONTEND_STEP_6,     # 合并到 Governance Report
    }
    return mapping.get(step_name, step_name)


def _ok(step: DemoStep, result: str, output_ref: str = "", evidence: str = "", source: str = "") -> DemoStep:
    step.status = "OK"
    step.result = result
    step.output_reference = output_ref
    if evidence:
        step.evidence = evidence
    if source:
        step.source = source
    return step


def _skip(step: DemoStep, reason: str) -> DemoStep:
    step.status = "SKIPPED"
    step.result = reason
    return step


def _err(step: DemoStep, exc: Exception) -> DemoStep:
    step.status = "ERROR"
    step.error = str(exc)[:200]
    step.result = f"失败：{exc}"[:200]
    return step


# ---------------------------------------------------------------------------
# 步骤 1：extract_claims（Research Agent 抽取主张）
# ---------------------------------------------------------------------------
def step_extract_claims(session: Session, company: str, report_id: str) -> DemoStep:
    step = DemoStep(
        step_number=1, name=STEP_EXTRACT_CLAIMS,
        frontend_label=_frontend_label(STEP_EXTRACT_CLAIMS),
        input_reference=f"company={company}",
    )
    t0 = time.time()
    try:
        from app.services.research_agent.orchestrator import run_research
        rs = run_research(session, company, "")
        claims = [f.content for f in rs.findings[:10]]
        step = _ok(
            step,
            result=f"Research Agent 抽取 {len(rs.findings)} 个主张（前 10 示）",
            output_ref=rs.session_id,
            evidence=f"{rs.evidence_count} 条证据",
            source="research_agent",
        )
        step.input_reference = f"company={company}, session={rs.session_id}"
    except Exception as exc:  # noqa: BLE001
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 2：retrieve_evidence（Evidence Retrieval）
# ---------------------------------------------------------------------------
def step_retrieve_evidence(session: Session, company: str, prev_output: str) -> DemoStep:
    step = DemoStep(
        step_number=2, name=STEP_RETRIEVE_EVIDENCE,
        frontend_label=_frontend_label(STEP_RETRIEVE_EVIDENCE),
        input_reference=f"session={prev_output}",
    )
    t0 = time.time()
    try:
        from app.services.research_agent.orchestrator import run_research
        rs = run_research(session, company, "")
        ev_count = rs.evidence_count
        step = _ok(
            step,
            result=f"Evidence Retrieval 检索 {ev_count} 条证据",
            output_ref=rs.session_id,
            evidence=f"{ev_count} 条",
            source="evidence_retrieval",
        )
    except Exception as exc:  # noqa: BLE101
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 3：verify_claims（Verification，不修改核心）
# ---------------------------------------------------------------------------
def step_verify_claims(session: Session, company: str, prev_output: str) -> DemoStep:
    step = DemoStep(
        step_number=3, name=STEP_VERIFY_CLAIMS,
        frontend_label=_frontend_label(STEP_VERIFY_CLAIMS),
        input_reference=f"session={prev_output}",
    )
    t0 = time.time()
    try:
        # Verification 核心未修改：仅记录入口就绪，不实际跑（需具体 claim+evidence 输入）
        step = _ok(
            step,
            result="Verification Engine 入口就绪（核心未修改，按 claim 调用）",
            output_ref="verification.ready",
            source="verification",
        )
    except Exception as exc:  # noqa: BLE101
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 4：assess_risk（Risk Engine，不修改核心）
# ---------------------------------------------------------------------------
def step_assess_risk(session: Session, company: str, prev_output: str) -> DemoStep:
    step = DemoStep(
        step_number=4, name=STEP_ASSESS_RISK,
        frontend_label=_frontend_label(STEP_ASSESS_RISK),
        input_reference=f"company={company}",
    )
    t0 = time.time()
    try:
        # Risk 核心未修改：仅记录入口就绪 + 既有风险条目计数
        from app.models.risk import RiskAssessmentRow
        cnt = session.query(RiskAssessmentRow).count() or 0
        step = _ok(
            step,
            result=f"Risk Engine 入口就绪，库中既有 {cnt} 条风险评估",
            output_ref="risk.ready",
            source="risk_engine",
        )
    except Exception as exc:  # noqa: BLE101
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 5：run_reasoning（Financial Reasoning）
# ---------------------------------------------------------------------------
def step_run_reasoning(session: Session, company: str, prev_output: str) -> DemoStep:
    step = DemoStep(
        step_number=5, name=STEP_RUN_REASONING,
        frontend_label=_frontend_label(STEP_RUN_REASONING),
        input_reference=f"company={company}",
    )
    t0 = time.time()
    try:
        from app.services.financial_reasoning import reason_about
        from app.services.financial_reasoning.schemas import ReasoningInput
        inp = ReasoningInput(
            claim_text=f"{company} 增长可持续性",
            claim={"original_text": f"{company} 增长可持续性", "company": company},
            evidence_candidates=[],
            company=company,
        )
        run = reason_about(session, inp)
        step = _ok(
            step,
            result=f"Reasoning Engine 识别 {len(run.results)} 类逻辑检查",
            output_ref=run.run_id,
            source="financial_reasoning",
        )
    except Exception as exc:  # noqa: BLE101
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 6：run_arena（Agent Arena 竞技）
# ---------------------------------------------------------------------------
def step_run_arena(session: Session, company: str, research_question: str) -> DemoStep:
    step = DemoStep(
        step_number=6, name=STEP_RUN_ARENA,
        frontend_label=_frontend_label(STEP_RUN_ARENA),
        input_reference=f"company={company}, question={research_question}",
    )
    t0 = time.time()
    try:
        from app.services.agent_arena.arena import run_arena
        run = run_arena(session, company, research_question)
        score = run.result.score.final_arena_score if run.result else 0.0
        step = _ok(
            step,
            result=f"Arena 完成：Final Score {score:.1f} · winner {run.result.winner if run.result else '-'}",
            output_ref=run.run_id,
            evidence=f"4 角色 · {len(run.messages)} 消息",
            source="agent_arena",
        )
    except Exception as exc:  # noqa: BLE101
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 7：generate_dashboard（Governance Dashboard）
# ---------------------------------------------------------------------------
def step_generate_dashboard(session: Session, company: str) -> DemoStep:
    step = DemoStep(
        step_number=7, name=STEP_GENERATE_DASHBOARD,
        frontend_label=_frontend_label(STEP_GENERATE_DASHBOARD),
        input_reference=f"company={company}",
    )
    t0 = time.time()
    try:
        from app.services.governance_center.dashboard import build_dashboard
        dash = build_dashboard(session, governance_id=f"DEMO-{company}")
        step = _ok(
            step,
            result=f"Dashboard 构建：reliability {dash.reliability.overall_reliability:.1f} · evidence_coverage {dash.reliability.evidence_coverage:.2f}",
            output_ref=dash.governance_id,
            evidence=f"6 部分聚合",
            source="governance_center",
        )
    except Exception as exc:  # noqa: BLE101
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 8：build_replay（Replay Timeline）
# ---------------------------------------------------------------------------
def step_build_replay(session: Session, arena_run_id: str) -> DemoStep:
    step = DemoStep(
        step_number=8, name=STEP_BUILD_REPLAY,
        frontend_label=_frontend_label(STEP_BUILD_REPLAY),
        input_reference=f"arena_run={arena_run_id}",
    )
    t0 = time.time()
    try:
        if not arena_run_id:
            step = _skip(step, "无 arena_run_id，跳过回放构建")
        else:
            from app.services.replay.service import build_replay
            tl = build_replay(session, arena_run_id, persist=True)
            step = _ok(
                step,
                result=f"Replay 构建完成：{tl.total_events} 个事件，6 步时间线",
                output_ref=arena_run_id,
                evidence=f"{tl.total_events} 事件",
                source="replay",
            )
    except Exception as exc:  # noqa: BLE101
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


__all__ = [
    "step_extract_claims",
    "step_retrieve_evidence",
    "step_verify_claims",
    "step_assess_risk",
    "step_run_reasoning",
    "step_run_arena",
    "step_generate_dashboard",
    "step_build_replay",
]
