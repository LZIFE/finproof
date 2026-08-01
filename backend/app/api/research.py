"""FinProof Autonomous Research Agent API（Phase 17，任务书 §6）。

- POST /api/v1/research/run         启动自主研究流程
- GET  /api/v1/research             列出研究会话
- GET  /api/v1/research/{id}        查询研究会话（plan / progress / findings / evidence / memo）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.research_agent import ResearchRunRequest
from app.services.research_agent.orchestrator import get_research, list_research, run_research

router = APIRouter(tags=["research"])


@router.post("/api/v1/research/run", status_code=201)
def run_research_endpoint(
    body: ResearchRunRequest,
    session: Session = Depends(get_session),
) -> dict:
    """从公司名启动自主金融研究流程，返回 ResearchSession（含 Memo）。"""
    try:
        rs = run_research(session, body.company, body.stock_code)
        return rs.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"研究流程失败: {exc}") from exc


@router.get("/api/v1/research")
def list_research_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    rs_list = list_research(session, limit=limit)
    return {
        "count": len(rs_list),
        "sessions": [
            {
                "session_id": r.session_id,
                "company": r.company,
                "stock_code": r.stock_code,
                "phase": r.phase,
                "created_at": r.created_at,
                "finished_at": r.finished_at,
            }
            for r in rs_list
        ],
    }


@router.get("/api/v1/research/{research_id}")
def get_research_endpoint(
    research_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """查询研究会话：plan / progress / findings / evidence / memo。"""
    try:
        return get_research(session, research_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
