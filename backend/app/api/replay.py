"""FinProof Replay API（Phase 21，任务书 §API）。

- GET /api/v1/replay/{audit_id}            获取审计回放时间线（5 类事件 + conclusion）
- GET /api/v1/replay                        列出已有回放 audit_id
- POST /api/v1/replay/{audit_id}/build      构建并持久化回放时间线（聚合既有审计数据）

约束：不修改 Verification/Risk 核心；不增加投资建议；所有内容来自已有数据。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.replay.service import build_replay, get_replay, list_replay

router = APIRouter(tags=["replay"])


@router.post("/api/v1/replay/{audit_id}/build", status_code=201)
def build_replay_endpoint(
    audit_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """构建并持久化审计回放时间线：聚合既有 Evidence/Verification/Risk/Agent 数据。"""
    try:
        timeline = build_replay(session, audit_id, persist=True)
        return timeline.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"回放构建失败: {exc}") from exc


@router.get("/api/v1/replay/{audit_id}")
def get_replay_endpoint(
    audit_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """获取已持久化的审计回放时间线（6 步顺序 + 来源/证据/结果）。

    若库中无该 audit_id 事件，自动触发构建（聚合既有数据并持久化），
    避免前端先 POST 再 GET 的两步操作。
    """
    try:
        timeline = get_replay(session, audit_id)
        # 若无已持久化事件，自动构建
        if timeline.total_events == 0:
            timeline = build_replay(session, audit_id, persist=True)
        return timeline.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"回放查询失败: {exc}") from exc


@router.get("/api/v1/replay")
def list_replay_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    """列出已有回放 audit_id（前端选择用）。"""
    items = list_replay(session, limit=limit)
    return {"count": len(items), "replays": items}
