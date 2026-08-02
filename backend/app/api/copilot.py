"""FinProof Copilot API（Phase 15，任务书 §6）。

- POST /api/v1/copilot/chat                   Copilot 回答（answer / tool_trace / evidence_chain / risk）
- GET  /api/v1/copilot/history/{session_id}   查询会话历史（支持连续追问）
- GET  /api/v1/copilot/sessions               列出用户会话
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.copilot import ChatRequest
from app.services.copilot import chat, get_history, list_sessions

router = APIRouter(tags=["copilot"])


@router.post("/api/v1/copilot/chat", status_code=201)
def chat_endpoint(
    body: ChatRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Copilot 主入口：自然语言 → 意图识别 → 工具规划 → 证据接地回答。

    基于已有 Evidence First 架构回答；不输出投资建议、不自动交易、不买卖判断。
    """
    try:
        response = chat(
            session,
            body.query,
            session_id=body.session_id,
            user_id=body.user_id or "default",
        )
        out = response.to_dict()
        # 解析实际 session_id：若请求未传 session_id，后端会新建，从最近会话查询
        if body.session_id:
            out["session_id"] = body.session_id
        else:
            sessions = list_sessions(session, user_id=body.user_id or "default", limit=1)
            out["session_id"] = sessions[0].session_id if sessions else ""
        return out
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Copilot 回答失败: {exc}") from exc


@router.get("/api/v1/copilot/history/{session_id}")
def history_endpoint(
    session_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """查询会话历史。"""
    try:
        return get_history(session, session_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/copilot/sessions")
def list_sessions_endpoint(
    user_id: str | None = None,
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    """列出用户会话。"""
    sessions = list_sessions(session, user_id=user_id, limit=limit)
    return {
        "count": len(sessions),
        "sessions": [s.to_dict() for s in sessions],
    }
