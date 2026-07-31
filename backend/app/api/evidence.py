"""证据检索 API（Phase 4A Oracle 模式）。

- POST /api/v1/evidence-retrievals                    创建检索任务（同步执行）
- GET  /api/v1/evidence-retrievals/{id}               任务详情
- GET  /api/v1/evidence-retrievals/{id}/claims        全部主张的 Top-K 候选
- GET  /api/v1/evidence-retrievals/{id}/claims/{claim_id}  单条主张的 Top-K 候选
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.evidence import EvidenceRetrievalRun
from app.schemas.evidence import (
    ClaimCandidatesOut,
    EvidenceCandidateOut,
    RetrievalClaimsOut,
    RetrievalRunCreateRequest,
    RetrievalRunOut,
)
from app.services.evidence_retrieval.service import get_run_claims, run_retrieval

router = APIRouter(tags=["evidence-retrieval"])


@router.get("/api/v1/evidence-retrievals")
def list_retrievals(
    limit: int = Query(default=10, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[RetrievalRunOut]:
    rows = (
        session.query(EvidenceRetrievalRun)
        .order_by(EvidenceRetrievalRun.id.desc())
        .limit(limit)
        .all()
    )
    return [RetrievalRunOut.model_validate(r) for r in rows]


@router.post("/api/v1/evidence-retrievals", status_code=201)
def create_retrieval(
    body: RetrievalRunCreateRequest,
    session: Session = Depends(get_session),
) -> RetrievalRunOut:
    run = run_retrieval(
        session,
        dataset=body.dataset,
        input_mode=body.input_mode,
        top_k=body.top_k,
        version="v2",
    )
    return RetrievalRunOut.model_validate(run)


def _get_run(session: Session, run_id: int) -> EvidenceRetrievalRun:
    run = session.get(EvidenceRetrievalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"检索任务不存在: {run_id}")
    return run


@router.get("/api/v1/evidence-retrievals/{run_id}")
def get_retrieval(run_id: int, session: Session = Depends(get_session)) -> RetrievalRunOut:
    return RetrievalRunOut.model_validate(_get_run(session, run_id))


@router.get("/api/v1/evidence-retrievals/{run_id}/claims")
def get_retrieval_claims(run_id: int, session: Session = Depends(get_session)) -> RetrievalClaimsOut:
    _get_run(session, run_id)
    grouped = get_run_claims(session, run_id)
    claims = [
        ClaimCandidatesOut(
            claim_id=cid,
            candidates=[EvidenceCandidateOut(**c) for c in cands],
        )
        for cid, cands in sorted(grouped.items())
    ]
    return RetrievalClaimsOut(retrieval_run_id=run_id, claim_count=len(claims), claims=claims)


@router.get("/api/v1/evidence-retrievals/{run_id}/claims/{claim_id}")
def get_retrieval_claim(
    run_id: int, claim_id: str, session: Session = Depends(get_session)
) -> ClaimCandidatesOut:
    _get_run(session, run_id)
    grouped = get_run_claims(session, run_id)
    cands = grouped.get(claim_id, [])
    if not cands:
        raise HTTPException(status_code=404, detail=f"主张无检索候选: {claim_id}")
    return ClaimCandidatesOut(claim_id=claim_id, candidates=[EvidenceCandidateOut(**c) for c in cands])
