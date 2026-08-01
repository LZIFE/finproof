"""FinProof Demo Mode API（Phase 22，任务书 §API）。

- POST /api/v1/demo/start         启动演示（company 可选，默认美的集团）
- GET  /api/v1/demo/{id}          查询演示运行（含 steps + 最终输出）
- GET  /api/v1/demo/{id}/steps    查询步骤列表
- GET  /api/v1/demo               列出最近演示
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.demo_mode.demo_runner import get_demo, get_demo_steps, list_demos, start_demo

router = APIRouter(tags=["demo"])


class DemoStartRequest(BaseModel):
    company: str | None = Field(default=None, max_length=120)
    report_id: str | None = Field(default=None, max_length=120)


@router.post("/api/v1/demo/start", status_code=201)
def start_demo_endpoint(
    body: DemoStartRequest | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """启动比赛演示：自动执行 8 步已有流程，最终输出可靠性评分/风险/审计回放。"""
    body = body or DemoStartRequest()
    try:
        run = start_demo(session, body.company or "", body.report_id or "")
        return run.to_dict()
    except Exception as exc:  # noqa: BLE101
        raise HTTPException(status_code=422, detail=f"演示启动失败: {exc}") from exc


@router.get("/api/v1/demo")
def list_demos_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    items = list_demos(session, limit=limit)
    return {"count": len(items), "demos": items}


@router.get("/api/v1/demo/{demo_id}")
def get_demo_endpoint(
    demo_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """查询演示运行：8 步记录 + 最终输出（reliability/risk/replay）。"""
    try:
        return get_demo(session, demo_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/demo/{demo_id}/steps")
def get_demo_steps_endpoint(
    demo_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """查询演示步骤列表。"""
    try:
        steps = get_demo_steps(session, demo_id)
        return {
            "demo_id": demo_id,
            "count": len(steps),
            "steps": [s.to_dict() for s in steps],
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
