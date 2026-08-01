"""FinProof FinSim API（Phase 18，任务书 §6）。

- POST /api/v1/simulation/runs              启动模拟（按场景类型/公司/难度）
- GET  /api/v1/simulation/runs/{run_id}     查询模拟运行（含 steps + result）
- GET  /api/v1/simulation/scenarios         列出可场景类型与难度
- GET  /api/v1/simulation/runs              列出最近模拟运行
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.financial_simulation import SimulationRunRequest
from app.services.financial_simulation.scenario_generator import list_scenario_types
from app.services.financial_simulation.schemas import DIFFICULTY_LEVELS, SCENARIO_LABELS

router = APIRouter(tags=["simulation"])


@router.get("/api/v1/simulation/scenarios")
def list_scenarios_endpoint() -> dict:
    """列出可场景类型与难度。"""
    return {
        "scenario_types": [
            {"type": st, "label": SCENARIO_LABELS.get(st, st)}
            for st in list_scenario_types()
        ],
        "difficulties": list(DIFFICULTY_LEVELS),
    }


@router.post("/api/v1/simulation/runs", status_code=201)
def create_run_endpoint(
    body: SimulationRunRequest,
    session: Session = Depends(get_session),
) -> dict:
    """启动模拟：按场景类型 / 公司 / 行业 / 难度执行 Agent 评估。"""
    from app.services.financial_simulation.simulator import run_simulation

    try:
        sim = run_simulation(
            session,
            body.scenario_type,
            body.company,
            body.industry,
            body.difficulty,
        )
        return sim.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"模拟失败: {exc}") from exc


@router.get("/api/v1/simulation/runs")
def list_runs_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    """列出最近模拟运行（仅元数据）。"""
    import json
    from app.models.financial_simulation import SimulationRunRow

    rows = (
        session.query(SimulationRunRow)
        .order_by(SimulationRunRow.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(rows),
        "runs": [
            {
                "run_id": r.run_id,
                "scenario_id": r.scenario_id,
                "agent_name": r.agent_name,
                "phase": r.phase,
                "created_at": r.created_at.isoformat(timespec="seconds") + "Z" if r.created_at else "",
                "finished_at": r.finished_at.isoformat(timespec="seconds") + "Z" if r.finished_at else "",
            }
            for r in rows
        ],
    }


@router.get("/api/v1/simulation/runs/{run_id}")
def get_run_endpoint(
    run_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """查询模拟运行：scenario / steps / result / score。"""
    import json
    from app.models.financial_simulation import (
        SimulationResultRow,
        SimulationRunRow,
        SimulationStepRow,
    )

    row = session.get(SimulationRunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"模拟运行不存在: {run_id}")

    scenario = {}
    if row.scenario_json:
        try:
            scenario = json.loads(row.scenario_json)
        except Exception:  # noqa: BLE001
            pass

    steps = (
        session.query(SimulationStepRow)
        .filter(SimulationStepRow.run_id == row.id)
        .order_by(SimulationStepRow.id.asc())
        .all()
    )

    result_row = (
        session.query(SimulationResultRow)
        .filter(SimulationResultRow.run_id == row.id)
        .first()
    )
    result = {}
    if result_row:
        def _loads(s, default):
            if not s:
                return default
            try:
                return json.loads(s)
            except Exception:  # noqa: BLE001
                return default
        result = {
            "result_id": result_row.result_id,
            "agent_run": _loads(result_row.agent_run_json, {}),
            "detected_findings": _loads(result_row.detected_findings_json, []),
            "missed_findings": _loads(result_row.missed_findings_json, []),
            "hallucination_findings": _loads(result_row.hallucination_findings_json, []),
            "score": _loads(result_row.score_json, {}),
            "fin_agent_score": result_row.fin_agent_score,
            "final_score": result_row.final_score,
            "success": result_row.success,
            "created_at": result_row.created_at.isoformat(timespec="seconds") + "Z" if result_row.created_at else "",
        }

    return {
        "run_id": row.run_id,
        "scenario_id": row.scenario_id,
        "scenario": scenario,
        "agent_name": row.agent_name,
        "phase": row.phase,
        "steps": [
            {
                "step_id": s.step_id,
                "phase": s.phase,
                "tool": s.tool,
                "input_summary": s.input_summary,
                "output_summary": s.output_summary,
                "evidence_count": s.evidence_count,
                "findings_count": s.findings_count,
                "success": s.success,
            }
            for s in steps
        ],
        "result": result,
        "created_at": row.created_at.isoformat(timespec="seconds") + "Z" if row.created_at else "",
        "finished_at": row.finished_at.isoformat(timespec="seconds") + "Z" if row.finished_at else "",
    }
