"""投资情报 API（Phase 8）。

- POST /api/v1/intelligence/runs              运行投资调查（生成 Intelligence Report）
- GET  /api/v1/intelligence/runs/{id}         查询投资情报报告
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.intelligence import IntelligenceRunRequest
from app.services.intelligence.intelligence_agent import (
    get_report,
    run_investigation,
    save_report,
)
from app.services.intelligence.schemas import InvestmentClaim

router = APIRouter(tags=["intelligence"])


@router.post("/api/v1/intelligence/runs", status_code=201)
def run_intelligence(
    body: IntelligenceRunRequest,
    session: Session = Depends(get_session),
) -> dict:
    """运行投资调查：投资观点 + 公司公开信息 → 冲突/支持 → 风险。

    不输出投资建议、不进行股票推荐、不替代投资经理决策。
    """
    try:
        claims = [
            InvestmentClaim(
                claim_id=c.get("claim_id") or f"INV-{i+1:04d}",
                claim=c.get("claim", ""),
                dimension=c.get("dimension", "BUSINESS"),
                value=c.get("value"),
                unit=c.get("unit", ""),
                period=c.get("period", ""),
            )
            for i, c in enumerate(body.claims)
        ]
        report = run_investigation(
            session,
            body.document_id,
            claims,
            external_fact_records=body.external_facts or None,
        )
        report = save_report(session, report)
        return report.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"投资调查失败: {exc}") from exc


@router.get("/api/v1/intelligence/runs/{report_id}")
def get_intelligence(report_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        report = get_report(session, report_id)
        return report.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
