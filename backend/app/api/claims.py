"""主张提取 API（Phase 3）。

- POST   /api/v1/documents/{document_id}/claim-extractions  创建提取任务（同步）
- GET    /api/v1/claim-extractions/{run_id}                 提取任务详情
- GET    /api/v1/documents/{document_id}/claims             主张列表（过滤/分页/排序）
- GET    /api/v1/claims/{claim_id}                          主张详情
- PATCH  /api/v1/claims/{claim_id}/review                   人工审核
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.enums import ClaimNature, ClaimType, ExtractionMode, ReviewStatus, RiskLevel
from app.core.exceptions import AppError
from app.db import get_session
from app.schemas.claim import (
    ClaimListResponse,
    ClaimOut,
    ExtractionRunOut,
    ReviewRequest,
    RunCreateRequest,
    RunCreateResponse,
)
from app.services import claim_service

router = APIRouter(tags=["claims"])

_CLAIM_TYPES = {e.value for e in ClaimType}
_RISK_LEVELS = {e.value for e in RiskLevel}
_CLAIM_NATURES = {e.value for e in ClaimNature}
_REVIEW_STATUSES = {e.value for e in ReviewStatus}


@router.post("/api/v1/documents/{document_id}/claim-extractions", status_code=201)
def create_claim_extraction(
    document_id: int,
    body: RunCreateRequest,
    session: Session = Depends(get_session),
) -> RunCreateResponse:
    run, created = claim_service.run_claim_extraction(
        session, document_id, mode=body.mode.value, force=body.force
    )
    return RunCreateResponse(
        extraction_run_id=run.id,
        document_id=document_id,
        status=run.status,
        mode=body.mode,
        extracted_claim_count=run.extracted_claim_count,
    )


@router.get("/api/v1/claim-extractions/{run_id}")
def get_claim_extraction(
    run_id: int, session: Session = Depends(get_session)
) -> ExtractionRunOut:
    run = claim_service.get_run_or_404(session, run_id)
    return ExtractionRunOut.model_validate(run)


@router.get("/api/v1/documents/{document_id}/claims")
def list_document_claims(
    document_id: int,
    claim_type: str | None = Query(None),
    risk_level: str | None = Query(None),
    claim_nature: str | None = Query(None),
    review_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("id_desc", pattern="^(id_desc|risk_desc|value_desc)$"),
    session: Session = Depends(get_session),
) -> ClaimListResponse:
    for name, value, allowed in [
        ("claim_type", claim_type, _CLAIM_TYPES),
        ("risk_level", risk_level, _RISK_LEVELS),
        ("claim_nature", claim_nature, _CLAIM_NATURES),
        ("review_status", review_status, _REVIEW_STATUSES),
    ]:
        if value is not None and value not in allowed:
            raise AppError(f"非法{name}: {value}", status_code=422, code=f"INVALID_{name.upper()}")
    total, claims = claim_service.list_claims(
        session,
        document_id,
        claim_type=claim_type,
        risk_level=risk_level,
        claim_nature=claim_nature,
        review_status=review_status,
        page=page,
        page_size=page_size,
        sort=sort,
    )
    return ClaimListResponse(
        total=total,
        page=page,
        page_size=page_size,
        claims=[ClaimOut.model_validate(c) for c in claims],
    )


@router.get("/api/v1/claims/{claim_id}")
def get_claim(claim_id: int, session: Session = Depends(get_session)) -> ClaimOut:
    claim = claim_service.get_claim_or_404(session, claim_id)
    return ClaimOut.model_validate(claim)


@router.patch("/api/v1/claims/{claim_id}/review")
def review_claim(
    claim_id: int,
    body: ReviewRequest,
    session: Session = Depends(get_session),
) -> ClaimOut:
    claim = claim_service.review_claim(
        session,
        claim_id,
        review_status=body.review_status.value,
        comment=body.comment,
        changes=body.changes,
    )
    return ClaimOut.model_validate(claim)
