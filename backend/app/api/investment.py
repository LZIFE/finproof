"""投资尽调 API（Phase 7）。

- POST /api/v1/investment/memos                生成 Investment Risk Memo（{audit_id}）
- GET  /api/v1/investment/memos/{id}           查询 Memo（含审核记录）
- POST /api/v1/investment/memos/{id}/reviews   人工审核单条主张（NEED_REVIEW/APPROVED/REJECTED）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.investment import InvestmentMemoCreateRequest, ReviewUpdateRequest
from app.services.investment import investment_analyzer

router = APIRouter(tags=["investment"])


@router.post("/api/v1/investment/memos", status_code=201)
def create_investment_memo(
    body: InvestmentMemoCreateRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        memo = investment_analyzer.create_investment_memo(session, body.audit_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Memo 生成失败: {exc}") from exc
    return memo.to_dict()


@router.get("/api/v1/investment/memos/{memo_id}")
def get_investment_memo(memo_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        memo = investment_analyzer.get_investment_memo(session, memo_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return memo.to_dict()


@router.post("/api/v1/investment/memos/{memo_id}/reviews")
def review_claim(
    memo_id: int,
    body: ReviewUpdateRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        record = investment_analyzer.update_review(
            session, memo_id, body.claim_id, body.review_status,
            note=body.note, reviewer=body.reviewer,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return record.to_dict()
