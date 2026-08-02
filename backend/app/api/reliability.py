"""FinProof Reliability Improvement API（Phase 23，任务书 §API）。

- POST /api/v1/reliability/analyze   生成 Reliability Improvement Report（持久化）
- GET  /api/v1/reliability/report    查询已持久化报告（支持 ?report_id= 或最新一条）
- GET  /api/v1/reliability/reports   列出最近报告元数据

约束：不修改已有核心模块；不自动修改模型；不输出投资建议。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.reliability_improvement.improvement_report import (
    analyze_reliability,
    get_report,
    list_reports,
    persist_report,
)

router = APIRouter(tags=["reliability"])


class AnalyzeRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=2000)


@router.post("/api/v1/reliability/analyze", status_code=201)
def analyze_endpoint(
    body: AnalyzeRequest | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """生成 Reliability Improvement Report：聚合 Benchmark/Red Team/Arena/Reasoning 失败模式。"""
    body = body or AnalyzeRequest()
    try:
        report = analyze_reliability(session, limit=body.limit)
        db_id = persist_report(session, report)
        out = report.to_dict()
        out["db_id"] = db_id
        return out
    except Exception as exc:  # noqa: BLE101
        raise HTTPException(status_code=422, detail=f"可靠性分析失败: {exc}") from exc


@router.get("/api/v1/reliability/report")
def get_report_endpoint(
    report_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """查询报告：传 ?report_id= 指定；不传则返回最新一条。"""
    try:
        if report_id:
            return get_report(session, report_id).to_dict()
        # 最新一条
        items = list_reports(session, limit=1)
        if not items:
            return {"report_id": "", "total_cases": 0, "total_failures": 0, "patterns": [], "trend": {}, "summary": "尚无已持久化报告，请先 POST /analyze"}
        rid = items[0]["report_id"]
        return get_report(session, rid).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE101
        raise HTTPException(status_code=422, detail=f"报告查询失败: {exc}") from exc


@router.get("/api/v1/reliability/reports")
def list_reports_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    """列出最近报告元数据（前端选择用）。"""
    items = list_reports(session, limit=limit)
    return {"count": len(items), "reports": items}
