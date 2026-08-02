"""投资委员会 API（Phase 9）。

- POST /api/v1/committee/runs                  运行多 Agent 投资委员会审核
- GET  /api/v1/committee/runs/{id}             查询委员会报告
- POST /api/v1/committee/runs/{id}/reviews     人工审核单个人工审核项
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.investment_committee import CommitteeRunRequest, ReviewUpdateRequest
from app.services.investment_committee.supervisor_agent import (
    get_report,
    run_committee,
    save_report,
    update_human_review,
)

router = APIRouter(tags=["committee"])


@router.post("/api/v1/committee/runs", status_code=201)
def run_committee_endpoint(
    body: CommitteeRunRequest,
    session: Session = Depends(get_session),
) -> dict:
    """运行多 Agent 投资委员会：Supervisor → Research → Risk → Compliance → Report。

    不输出投资建议、不自动决定买卖、保持 Human-in-the-loop。
    """
    try:
        report = run_committee(
            session,
            body.document_id,
            body.audit_id,
            body.intelligence_report_id,
        )
        report = save_report(session, report)
        return report.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"委员会审核失败: {exc}") from exc


@router.get("/api/v1/committee/runs/{report_id}")
def get_committee_endpoint(report_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        report = get_report(session, report_id)
        return report.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/v1/committee/runs/{report_id}/reviews")
def review_item_endpoint(
    report_id: int,
    body: ReviewUpdateRequest,
    session: Session = Depends(get_session),
) -> dict:
    """更新人工审核项状态（NEED_REVIEW / APPROVED / REJECTED）。"""
    try:
        item = update_human_review(
            session,
            report_id,
            body.item_id,
            body.review_status,
            note=body.note,
            reviewer=body.reviewer,
        )
        return item.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
