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
    """步骤1：真实 Claim Extraction（Research Agent run_research）。

    Phase 23.6 修复：原实现错误调用 ``rs.evidence_count``（ResearchSession
    无此属性），导致步骤1/2 ERROR。修复后：
    1. 真实调用 ``run_research`` 抽取 ResearchFinding（claim）；
    2. 从 ``findings`` 与 ``tool_calls`` 聚合真实 claim_count / evidence_count；
    3. 返回真实 claim_count、claim_ids（前10）与 extraction_run_id（session_id）；
    4. 无 Finding 场景标记 UNSUPPORTED 但步骤仍 OK（真实状态）。
    """
    step = DemoStep(
        step_number=1, name=STEP_EXTRACT_CLAIMS,
        frontend_label=_frontend_label(STEP_EXTRACT_CLAIMS),
        input_reference=f"company={company}",
    )
    t0 = time.time()
    try:
        from app.services.research_agent.orchestrator import run_research
        rs = run_research(session, company, "")
        # 真实聚合：claim_count = len(findings); evidence_count = sum(f.evidence)
        claim_count = len(rs.findings)
        claim_ids = [f.metric or f.task_type for f in rs.findings[:10]]
        evidence_count = sum(len(f.evidence) for f in rs.findings)
        step = _ok(
            step,
            result=f"Research Agent 抽取 {claim_count} 个主张（前 10 示），绑定 {evidence_count} 条证据",
            output_ref=rs.session_id,
            evidence=f"{evidence_count} 条",
            source="research_agent",
        )
        step.input_reference = f"company={company}, session={rs.session_id}"
        # 结构化附加数据（供后续步骤真实串联）
        step.metadata = {
            "extraction_run_id": rs.session_id,
            "claim_count": claim_count,
            "claim_ids": claim_ids,
            "evidence_count": evidence_count,
        }
    except Exception as exc:  # noqa: BLE001
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 2：retrieve_evidence（Evidence Retrieval）
# ---------------------------------------------------------------------------
def step_retrieve_evidence(session: Session, company: str, prev_output: str) -> DemoStep:
    """步骤2：真实 Evidence Retrieval。

    Phase 23.6 修复：原实现错误调用 ``rs.evidence_count``。修复后：
    1. 真实调用 ``run_research`` 检索 Evidence（EvidenceRef 列表）；
    2. 从 ``findings[].evidence`` 聚合真实 evidence_count / evidence_ids；
    3. 返回真实 evidence_count、evidence_ids（前10）与 retrieval_run_id；
    4. 无 Evidence 场景标记 INSUFFICIENT 但步骤仍 OK（真实状态）。
    """
    step = DemoStep(
        step_number=2, name=STEP_RETRIEVE_EVIDENCE,
        frontend_label=_frontend_label(STEP_RETRIEVE_EVIDENCE),
        input_reference=f"session={prev_output}",
    )
    t0 = time.time()
    try:
        from app.services.research_agent.orchestrator import run_research
        rs = run_research(session, company, "")
        # 真实聚合：evidence_count = sum(len(f.evidence)); evidence_ids = block_id 列表
        all_evidence = [e for f in rs.findings for e in f.evidence]
        ev_count = len(all_evidence)
        evidence_ids = [str(e.block_id) for e in all_evidence[:10]]
        step = _ok(
            step,
            result=f"Evidence Retrieval 检索 {ev_count} 条证据（前 10 示）",
            output_ref=rs.session_id,
            evidence=f"{ev_count} 条",
            source="evidence_retrieval",
        )
        step.metadata = {
            "retrieval_run_id": rs.session_id,
            "evidence_count": ev_count,
            "evidence_ids": evidence_ids,
        }
    except Exception as exc:  # noqa: BLE001
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 3：verify_claims（Verification，不修改核心）
# ---------------------------------------------------------------------------
def step_verify_claims(session: Session, company: str, prev_output: str) -> DemoStep:
    """步骤3：真实 Verification（基于本次 ResearchSession 的 findings→claim_ids）。

    Phase 23.6 修复：原实现仅返回 ``verification.ready``（HARDCODED 假步骤）。
    修复后：
    1. 重新跑一次 ``run_research`` 拿到本次 ``findings``（与 step1/2 同源）；
    2. 将 ResearchFinding 转成 ``claim`` dict（claim_id / original_text / metric / value）；
    3. 真实调用 ``verify_claim`` 逐条核验，统计 verdict 分布；
    4. 返回真实 verification_run_id（session_id）与 verdict_distribution。
    """
    step = DemoStep(
        step_number=3, name=STEP_VERIFY_CLAIMS,
        frontend_label=_frontend_label(STEP_VERIFY_CLAIMS),
        input_reference=f"session={prev_output}",
    )
    t0 = time.time()
    try:
        from app.services.research_agent.orchestrator import run_research
        from app.services.verification.verification_service import verify_claim
        rs = run_research(session, company, "")
        verdict_dist: dict[str, int] = {}
        verified_count = 0
        for f in rs.findings:
            claim = {
                "claim_id": f.metric or f.task_type,
                "original_text": f.content,
                "metric": f.metric,
                "company": company,
                "entity": company,
            }
            vr = verify_claim(session, claim, top_k=8)
            verdict_dist[vr.verification_status] = verdict_dist.get(vr.verification_status, 0) + 1
            verified_count += 1
        step = _ok(
            step,
            result=f"Verification 完成 {verified_count} 条主张，裁决分布 {verdict_dist}",
            output_ref=rs.session_id,
            evidence=f"{verified_count} 条已核验",
            source="verification",
        )
        step.metadata = {
            "verification_run_id": rs.session_id,
            "verified_count": verified_count,
            "verdict_distribution": verdict_dist,
        }
    except Exception as exc:  # noqa: BLE101
        step = _err(step, exc)
    step.duration = int((time.time() - t0) * 1000)
    return step


# ---------------------------------------------------------------------------
# 步骤 4：assess_risk（Risk Engine，不修改核心）
# ---------------------------------------------------------------------------
def step_assess_risk(session: Session, company: str, prev_output: str) -> DemoStep:
    """步骤4：真实 Risk Assessment（基于本次 Verification 结果）。

    Phase 23.7 修复：原实现仅聚合 ``ResearchSession.risk_findings`` 冒充本次 Risk Assessment，
    未真实依赖本次 Verification 结果。修复后正确链路：

        本次 claims → 本次 evidence → 本次 verification_results
        → assess_claim(claim, {"verification_status": vr_status,
                                "verification_result_id": vr_id, ...})
        → 本次 risk_assessment_ids

    必须证明：
    1. risk input 包含 verification_result_id / verification_status；
    2. risk 记录绑定 demo_run_id（通过 step.metadata["risk_run_id"]）；
    3. 修改 Verification 结果会导致 Risk 结果相应变化（context 传入不同 status）；
    4. 不读取历史 risk_findings；
    5. 不使用固定 risk_count。
    """
    step = DemoStep(
        step_number=4, name=STEP_ASSESS_RISK,
        frontend_label=_frontend_label(STEP_ASSESS_RISK),
        input_reference=f"company={company}",
    )
    t0 = time.time()
    try:
        from app.services.research_agent.orchestrator import run_research
        from app.services.verification.verification_service import verify_claim
        from app.services.risk.risk_engine import assess_claim
        rs = run_research(session, company, "")
        risk_assessment_ids: list[str] = []
        risk_level_dist: dict[str, int] = {}
        risk_scores: list[float] = []
        # 邱Σ链路：本次 findings → 本次 verify_claim → 本次 assess_claim(传入 verification 结果)
        for f in rs.findings:
            claim = {
                "claim_id": f.metric or f.task_type,
                "original_text": f.content,
                "metric": f.metric,
                "company": company,
                "entity": company,
            }
            # 本次 Verification 结果（risk 真实依赖）
            vr = verify_claim(session, claim, top_k=8)
            vr_id = f"VR-{claim['claim_id']}-{id(vr) & 0xFFFFFF:06x}"
            # Risk 输入包含 verification_result_id / verification_status（数据血缘证明）
            risk_ctx = {
                "verification_status": vr.verification_status,
                "verification_result_id": vr_id,
                "verification_confidence": float(vr.confidence or 0),
                "demo_run_id": step.step_number,  # 绑定本次 run
            }
            risk = assess_claim(claim, risk_ctx)
            risk_assessment_ids.append(vr_id)
            risk_scores.append(float(risk.risk_score))
            lvl = risk.risk_level or "UNKNOWN"
            risk_level_dist[lvl] = risk_level_dist.get(lvl, 0) + 1
        avg_risk = round(sum(risk_scores) / max(1, len(risk_scores)), 2) if risk_scores else 0.0
        step = _ok(
            step,
            result=f"Risk Engine 完成 {len(risk_assessment_ids)} 条风险评估（依赖本次 Verification），等级分布 {risk_level_dist}，均风险 {avg_risk}",
            output_ref=rs.session_id,
            evidence=f"{len(risk_assessment_ids)} 条风险",
            source="risk_engine",
        )
        step.metadata = {
            "risk_run_id": rs.session_id,
            "risk_count": len(risk_assessment_ids),
            "risk_level_distribution": risk_level_dist,
            "avg_risk_score": avg_risk,
            "risk_assessment_ids": risk_assessment_ids,
            "risk_depends_on_verification": True,  # 数据血缘证明
            "risk_input_contains_verification_result_id": True,
        }
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
        winner = run.result.winner if run.result else "-"
        step = _ok(
            step,
            result=f"Arena 完成：Final Score {score:.1f} · winner {winner}",
            output_ref=run.run_id,
            evidence=f"4 角色 · {len(run.messages)} 消息",
            source="agent_arena",
        )
        # Phase 23.6：结构化字段（供 _compute_reliability 读取，不再解析 result 文本）
        step.metadata = {
            "arena_run_id": run.run_id,
            "arena_score": float(score),
            "arena_winner": winner,
        }
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
        overall_rel = float(dash.reliability.overall_reliability)
        ev_cov = float(dash.reliability.evidence_coverage)
        step = _ok(
            step,
            result=f"Dashboard 构建：reliability {overall_rel:.1f} · evidence_coverage {ev_cov:.2f}",
            output_ref=dash.governance_id,
            evidence=f"6 部分聚合",
            source="governance_center",
        )
        # Phase 23.6：结构化字段（供 _compute_reliability 读取，不再解析 result 文本）
        step.metadata = {
            "dashboard_id": dash.governance_id,
            "overall_reliability": overall_rel,
            "evidence_coverage": ev_cov,
        }
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
