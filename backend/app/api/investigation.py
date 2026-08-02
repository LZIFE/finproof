"""Autonomous Investigation API（Phase 13，任务书 §8）。

- POST /api/v1/investigations              启动自主调查
- GET  /api/v1/investigations              列出调查
- GET  /api/v1/investigations/{run_id}     查询调查（plan / steps / evidence / conclusion）
- GET  /api/v1/investigations/memory/{company}   查询 Agent Memory
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.autonomous_agent import InvestigationRequest
from app.services.autonomous_agent import (
    get_investigation,
    get_memory,
    list_investigations,
    run_investigation,
)
from app.services.autonomous_agent.schemas import ClaimContext

router = APIRouter(tags=["investigation"])


@router.post("/api/v1/investigations", status_code=201)
def start_investigation_endpoint(
    body: InvestigationRequest,
    session: Session = Depends(get_session),
) -> dict:
    """启动自主调查：根据 claim_type / risk_type 自主规划调查路径。"""
    try:
        ctx = ClaimContext(
            claim_text=body.claim_text,
            claim_type=body.claim_type,
            risk_type=body.risk_type,
            company=body.company,
            stock_code=body.stock_code,
            claim=body.claim or {},
            verification_result=body.verification_result or {},
        )
        run = run_investigation(session, ctx, use_memory=body.use_memory)
        return run.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"调查失败: {exc}") from exc


@router.get("/api/v1/investigations")
def list_investigations_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    runs = list_investigations(session, limit=limit)
    return {
        "count": len(runs),
        "investigations": [
            {
                "trace_id": r.trace_id,
                "run_id": r.run_id,
                "claim_text": r.claim_context.claim_text,
                "claim_type": r.claim_context.claim_type,
                "risk_type": r.claim_context.risk_type,
                "company": r.claim_context.company,
                "conclusion": r.conclusion,
                "created_at": r.created_at,
            }
            for r in runs
        ],
    }


@router.get("/api/v1/investigations/{run_id}")
def get_investigation_endpoint(
    run_id: int,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return get_investigation(session, run_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/investigations/memory/{company}")
def get_memory_endpoint(
    company: str,
    session: Session = Depends(get_session),
) -> dict:
    mem = get_memory(session, company)
    if mem is None:
        raise HTTPException(status_code=404, detail=f"无记忆: {company}")
    return mem.to_dict()
