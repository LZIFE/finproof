"""FinProof FinSim Simulator（Phase 18，任务书 §3）。

模拟流程：Scenario → Agent receives task → autonomously investigates →
collect evidence → generate memo → compare with expected findings。

调用 Research Agent 完成调查，全程记录 SimulationStep，最后交 evaluator 评分。

约束：不输出投资建议；不交易；不修改 Verification 核心。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.financial_simulation.schemas import (
    AgentRunRecord,
    PHASE_AGENT_INVESTIGATES,
    PHASE_COLLECT_EVIDENCE,
    PHASE_COMPARE_AND_SCORE,
    PHASE_GENERATE_MEMO,
    PHASE_SCENARIO,
    SimulationRun,
    SimulationStep,
    _now_iso,
)
from app.services.financial_simulation.evaluator import evaluate_run
from app.services.financial_simulation.scenario_generator import make_scenario


def run_simulation(
    session: Session,
    scenario_type: str,
    company: str,
    industry: str = "综合",
    difficulty: str = "Easy",
    scenario_id: str = "",
) -> SimulationRun:
    """对单个场景执行端到端模拟：跑 Agent → 评分。"""
    if not scenario_id:
        scenario_id = f"SCEN-{scenario_type[0]}-{difficulty[0]}-{datetime.utcnow().strftime('%H%M%S')}"

    run_id = f"SIM-RUN-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]}"
    scenario = make_scenario(scenario_id, scenario_type, company, industry, difficulty)
    steps: list[SimulationStep] = []

    sim_run = SimulationRun(
        run_id=run_id,
        scenario_id=scenario.scenario_id,
        scenario=scenario,
        phase=PHASE_SCENARIO,
        steps=steps,
        created_at=_now_iso(),
    )

    # ① Scenario 阶段
    steps.append(SimulationStep(
        step_id="STEP-001",
        phase=PHASE_SCENARIO,
        tool="scenario_generator",
        input_summary=f"scenario_type={scenario_type} company={company} difficulty={difficulty}",
        output_summary=f"scenario_id={scenario.scenario_id} expected={len(scenario.expected_findings)} hidden={len(scenario.hidden_risks)}",
        timestamp=_now_iso(),
    ))

    # ② Agent Investigates + ③ Collect Evidence + ④ Generate Memo
    agent_record = _run_research_agent(session, scenario, steps)
    sim_run.phase = PHASE_GENERATE_MEMO

    # ⑤ Compare and Score
    sim_run.phase = PHASE_COMPARE_AND_SCORE
    steps.append(SimulationStep(
        step_id=f"STEP-005",
        phase=PHASE_COMPARE_AND_SCORE,
        tool="evaluator",
        input_summary=f"scenario={scenario.scenario_id} agent_findings={len(agent_record.findings)}",
        output_summary="compute 5 sub-scores + FinAgent Score",
        findings_count=len(agent_record.findings),
        timestamp=_now_iso(),
    ))
    result = evaluate_run(session, sim_id=run_id, scenario=scenario, agent_record=agent_record, steps=steps)
    sim_run.result = result
    sim_run.finished_at = _now_iso()

    # 持久化
    _persist(session, sim_run)
    return sim_run


def run_simulation_by_id(session: Session, scenario_id: str, company: str, industry: str = "综合") -> SimulationRun:
    """按 scenario_id（demo/catalog）执行模拟。解析 id 提取类型与难度。"""
    st, diff = _parse_scenario_id(scenario_id)
    return run_simulation(session, st, company, industry, diff, scenario_id)


def _parse_scenario_id(sid: str) -> tuple[str, str]:
    """从 scenario_id 解析 (scenario_type, difficulty)。

    约定：SCEN-<type首字母>-<difficulty首字母>[-后缀]
    """
    parts = sid.split("-")
    if len(parts) < 3:
        raise ValueError(f"非法 scenario_id: {sid}")
    type_letter = parts[1]
    diff_letter = parts[2]
    type_map = {"F": "Financial Misstatement", "B": "Business Overstatement",
                "G": "Growth Quality Problem", "C": "Competitive Claim Verification",
                "E": "Risk Monitoring"}
    diff_map = {"E": "Easy", "M": "Medium", "H": "Hard", "D": "Hard"}  # D=DEMO
    st = type_map.get(type_letter)
    diff = diff_map.get(diff_letter, "Easy")
    if not st:
        raise ValueError(f"非法 scenario_id 类型字母: {type_letter}")
    return st, diff


# ---------------------------------------------------------------------------
# 内部：跑 Research Agent
# ---------------------------------------------------------------------------
def _run_research_agent(
    session: Session,
    scenario: Any,
    steps: list[SimulationStep],
) -> AgentRunRecord:
    """调用 Research Agent 执行场景任务，返回 AgentRunRecord。"""
    from app.services.research_agent.orchestrator import run_research

    step_idx = 2
    start = datetime.utcnow()
    agent_record = AgentRunRecord()

    try:
        # ② Agent Investigates
        steps.append(SimulationStep(
            step_id=f"STEP-{step_idx:03d}",
            phase=PHASE_AGENT_INVESTIGATES,
            tool="research_agent",
            input_summary=scenario.task_query,
            output_summary="Agent 启动自主研究流程",
            timestamp=_now_iso(),
        ))
        step_idx += 1

        # ③ Collect Evidence + ④ Generate Memo（由 research_agent 内部完成）
        rs = run_research(session, scenario.company, "")
        agent_record.session_id = rs.session_id
        agent_record.tool_calls = [t.to_dict() for t in rs.tool_calls]
        agent_record.findings = [f.to_dict() for f in rs.findings]
        agent_record.risk_findings = [r.to_dict() for r in rs.risk_findings]
        agent_record.memo = rs.memo.to_dict() if rs.memo else {}
        agent_record.evidence = [e.to_dict() for e in (rs.memo.evidence_chain if rs.memo else [])]
        agent_record.duration_sec = (datetime.utcnow() - start).total_seconds()

        steps.append(SimulationStep(
            step_id=f"STEP-{step_idx:03d}",
            phase=PHASE_COLLECT_EVIDENCE,
            tool="research_agent",
            input_summary=scenario.task_query,
            output_summary=f"findings={len(agent_record.findings)} risks={len(agent_record.risk_findings)} evidence={len(agent_record.evidence)}",
            evidence_count=len(agent_record.evidence),
            findings_count=len(agent_record.findings),
            timestamp=_now_iso(),
        ))
        step_idx += 1

        steps.append(SimulationStep(
            step_id=f"STEP-{step_idx:03d}",
            phase=PHASE_GENERATE_MEMO,
            tool="research_agent",
            input_summary="generate_memo",
            output_summary=f"memo sections=7 coverage={agent_record.memo.get('evidence_coverage', 0)}",
            success=bool(agent_record.memo),
            timestamp=_now_iso(),
        ))
    except Exception as exc:  # noqa: BLE001
        steps.append(SimulationStep(
            step_id=f"STEP-{step_idx:03d}",
            phase=PHASE_AGENT_INVESTIGATES,
            tool="research_agent",
            input_summary=scenario.task_query,
            output_summary=f"error: {exc}",
            success=False,
            timestamp=_now_iso(),
        ))
    return agent_record


# ---------------------------------------------------------------------------
# 内部：持久化
# ---------------------------------------------------------------------------
def _persist(session: Session, sim_run: SimulationRun) -> None:
    """持久化 SimulationRun + steps + result。"""
    import json
    from app.models.financial_simulation import (
        SimulationResultRow,
        SimulationRunRow,
        SimulationStepRow,
    )

    run_row = SimulationRunRow(
        run_id=sim_run.run_id,
        scenario_id=sim_run.scenario_id,
        scenario_json=json.dumps(sim_run.scenario.to_dict() if sim_run.scenario else {}, ensure_ascii=False),
        agent_name=sim_run.agent_name,
        phase=sim_run.phase,
        created_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
    )
    session.add(run_row)
    session.flush()
    run_db_id = run_row.id

    for st in sim_run.steps:
        session.add(SimulationStepRow(
            run_id=run_db_id,
            step_id=st.step_id,
            phase=st.phase,
            tool=st.tool,
            input_summary=st.input_summary,
            output_summary=st.output_summary,
            evidence_count=st.evidence_count,
            findings_count=st.findings_count,
            success=st.success,
            created_at=datetime.utcnow(),
        ))

    if sim_run.result:
        r = sim_run.result
        session.add(SimulationResultRow(
            run_id=run_db_id,
            result_id=r.result_id,
            agent_run_json=json.dumps(r.agent_run.to_dict(), ensure_ascii=False),
            detected_findings_json=json.dumps(r.detected_findings, ensure_ascii=False),
            missed_findings_json=json.dumps(r.missed_findings, ensure_ascii=False),
            hallucination_findings_json=json.dumps(r.hallucination_findings, ensure_ascii=False),
            score_json=json.dumps(r.score.to_dict(), ensure_ascii=False),
            fin_agent_score=r.score.fin_agent_score,
            final_score=r.score.final_score,
            success=r.success,
            created_at=datetime.utcnow(),
        ))

    session.commit()


__all__ = ["run_simulation", "run_simulation_by_id"]
