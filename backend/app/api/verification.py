"""核验 API（Phase 4B.1）。

- POST /api/v1/verifications           创建核验任务（claim_ids + mode，同步执行）
- GET  /api/v1/verifications/{id}      核验任务详情（含每条主张的 status/confidence/证据/计算/说明）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.verification import VerificationRun
from app.schemas.verification import (
    VerificationCreateRequest,
    VerificationDetailOut,
    VerificationResultOut,
    VerificationRunOut,
)
from app.services.verification import verification_service

router = APIRouter(tags=["verification"])


@router.post("/api/v1/verifications", status_code=201)
def create_verification(
    body: VerificationCreateRequest,
    session: Session = Depends(get_session),
) -> VerificationDetailOut:
    run = verification_service.run_verification_batch(session, body.claim_ids, mode=body.mode)
    results = verification_service.get_verification_results(session, run.id)
    return VerificationDetailOut(
        run=VerificationRunOut.model_validate(run),
        results=[VerificationResultOut(**r) for r in results],
    )


@router.get("/api/v1/verifications/{run_id}")
def get_verification(run_id: int, session: Session = Depends(get_session)) -> VerificationDetailOut:
    run = session.get(VerificationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"核验任务不存在: {run_id}")
    results = verification_service.get_verification_results(session, run_id)
    return VerificationDetailOut(
        run=VerificationRunOut.model_validate(run),
        results=[VerificationResultOut(**r) for r in results],
    )
