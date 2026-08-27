"""来源链 API：返回单条主张的完整溯源链路。

- GET /api/v1/source-chain/{claim_id}  主张 → 证据 → 原始来源
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.source_chain import build_source_chain

router = APIRouter(tags=["source-chain"])


@router.get("/api/v1/source-chain/{claim_id}")
def get_source_chain(
    claim_id: str,
    top_k: int = Query(default=5, ge=1, le=20),
    session: Session = Depends(get_session),
) -> dict:
    """构建主张的来源链：主张信息 + 核验结论 + 证据溯源链。"""
    try:
        return build_source_chain(session, claim_id, top_k=top_k)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"来源链构建失败: {exc}") from exc
