"""FinProof Agent Arena API（Phase 19，任务书 §API）。

- POST /api/v1/arena/run         启动竞技（company + research_question）
- GET  /api/v1/arena             列出竞技运行
- GET  /api/v1/arena/{id}        查询竞技运行（含 messages + result + score）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.agent_arena import ArenaRunRequest
from app.services.agent_arena.arena import get_arena, list_arena, run_arena

router = APIRouter(tags=["arena"])


@router.post("/api/v1/arena/run", status_code=201)
def run_arena_endpoint(
    body: ArenaRunRequest,
    session: Session = Depends(get_session),
) -> dict:
    """启动多 Agent 竞技：Analyst → Skeptic → Auditor → Judge。"""
    try:
        run = run_arena(session, body.company, body.research_question)
        return run.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"竞技流程失败: {exc}") from exc


@router.get("/api/v1/arena")
def list_arena_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    runs = list_arena(session, limit=limit)
    return {
        "count": len(runs),
        "runs": [
            {
                "run_id": r.run_id,
                "company": r.company,
                "research_question": r.research_question,
                "phase": r.phase,
                "winner": r.result.winner if r.result else "",
                "final_arena_score": r.result.score.final_arena_score if r.result else 0.0,
                "created_at": r.created_at,
                "finished_at": r.finished_at,
            }
            for r in runs
        ],
    }


@router.get("/api/v1/arena/{arena_id}")
def get_arena_endpoint(
    arena_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """查询竞技运行：messages（辩论时间线）+ result（双方观点/挑战/审计/评分）。"""
    try:
        return get_arena(session, arena_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
