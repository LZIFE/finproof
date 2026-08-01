"""FinProof Financial Reasoning API（Phase 16，任务书 §7）。

- POST /api/v1/reasoning/runs              启动推理
- GET  /api/v1/reasoning/runs              列出推理运行
- GET  /api/v1/reasoning/runs/{run_id}     查询推理运行（含 results）
- GET  /api/v1/reasoning/runs/{run_id}/results  仅查询结果
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.financial_reasoning import ReasoningRunRequest
from app.services.financial_reasoning import (
    get_run,
    get_run_results,
    list_runs,
    reason_about,
)
from app.services.financial_reasoning.schemas import ReasoningInput

router = APIRouter(tags=["reasoning"])


@router.post("/api/v1/reasoning/runs", status_code=201)
def create_run_endpoint(
    body: ReasoningRunRequest,
    session: Session = Depends(get_session),
) -> dict:
    """启动金融推理：识别逻辑风险、隐含假设、结论跳跃。"""
    try:
        input_ = ReasoningInput(
            claim_text=body.claim_text,
            claim=body.claim or {},
            verification_result=body.verification_result or {},
            evidence_candidates=body.evidence_candidates or [],
            knowledge_graph_facts=body.knowledge_graph_facts or [],
            risk_assessment=body.risk_assessment or {},
            company=body.company,
            period=body.period,
        )
        run = reason_about(session, input_)
        return run.to_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"推理失败: {exc}") from exc


@router.get("/api/v1/reasoning/runs")
def list_runs_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    runs = list_runs(session, limit=limit)
    return {
        "count": len(runs),
        "runs": [
            {
                "run_id": r.run_id,
                "claim_text": r.claim_text,
                "rule_version": r.rule_version,
                "results_count": len(r.results),
                "created_at": r.created_at,
            }
            for r in runs
        ],
    }


@router.get("/api/v1/reasoning/runs/{run_id}")
def get_run_endpoint(
    run_id: int,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return get_run(session, run_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/reasoning/runs/{run_id}/results")
def get_run_results_endpoint(
    run_id: int,
    session: Session = Depends(get_session),
) -> dict:
    try:
        results = get_run_results(session, run_id)
        return {
            "run_id": run_id,
            "count": len(results),
            "results": [r.to_dict() for r in results],
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
