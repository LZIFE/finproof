"""FinProof Demo Mode API（Phase 22，任务书 §API）。

- POST /api/v1/demo/start         启动演示（company 可选，默认美的集团）
- GET  /api/v1/demo/{id}          查询演示运行（含 steps + 最终输出）
- GET  /api/v1/demo/{id}/steps    查询步骤列表
- GET  /api/v1/demo               列出最近演示

Phase 23.6 安全加固：
- 输入字段（company / report_id）做长度与字符集校验，拒绝控制字符与注入向量；
- company 含 HTML/JS 标签时直接 422 拒绝（反射型 XSS 防护）；
- demo_id 路径参数做正则白名单校验，拒绝路径穿越/SQL 注入/非法字符；
- 异常处理器不再回显原始 payload，统一返回安全错误结构。
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.demo_mode.demo_runner import get_demo, get_demo_steps, list_demos, start_demo
from app.services.demo_mode.portfolio_demo import run_portfolio_demo

router = APIRouter(tags=["demo"])

# ---------------------------------------------------------------------------
# Phase 23.6 安全正则与常量
# ---------------------------------------------------------------------------
# demo_id 白名单：DEMO-<14位时间戳>-<8位hex>，或任意 DEMO-<alnum/-> 组合
_DEMO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
# 危险 HTML/JS 片段（反射型 XSS 防护）
_DANGEROUSMarkup = re.compile(r"<\s*(script|iframe|img|svg|object|embed)[^>]*>", re.IGNORECASE)
# 控制字符（除 \t \n \r 外的 C0/C1）
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# 投资建议禁用词（Prompt Injection 防护：拒绝含 BUY/SELL/买入/卖出 等指令的输入）
_FORBIDDEN_ADVICE_RE = re.compile(
    r"\b(buy|sell|target\s*price|买入|卖出|目标价|建议加仓|建议减仓|推荐买入|推荐卖出)\b",
    re.IGNORECASE,
)


class DemoStartRequest(BaseModel):
    company: str | None = Field(default=None, max_length=120)
    report_id: str | None = Field(default=None, max_length=120)

    @field_validator("company", "report_id")
    @classmethod
    def _no_control_chars(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if _CONTROL_CHARS_RE.search(v):
            raise ValueError("输入含非法控制字符")
        # 反反射型 XSS 防护：拒绝带 HTML/JS 标签的输入
        if _DANGEROUSMarkup.search(v):
            raise ValueError("输入含非法标记（拒绝 XSS 向量）")
        # Phase 23.7：Prompt Injection 真实防护——不依赖关键词拒绝整份报告，
        # 仅检测并记录注入尝试（正常金融文本中的 buy/sell/买入评级 作为待审计内容仍允许输入）。
        from app.services.claims.prompt_injection_guard import (
            prompt_injection_detection_event,
        )
        detection = prompt_injection_detection_event(v or "", source="demo_start_input")
        if detection.detected:
            # 检测到注入指令：可保存与展示，但不执行（不拒绝整份报告，仅拒绝该指令字段）
            raise ValueError(
                f"检测到 Prompt Injection 指令（已记录审计事件，拒绝执行）：{','.join(detection.categories[:3])}"
            )
        return v


def _validate_demo_id(demo_id: str) -> None:
    """白名单校验 demo_id，拒绝路径穿越/SQL 注入/非法字符。"""
    if not demo_id or not _DEMO_ID_RE.match(demo_id):
        raise HTTPException(
            status_code=400,
            detail="非法的 demo_id：仅允许字母、数字、'_'、'-'，长度 1-128",
        )


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
        # Phase 23.6：不回显原始 payload，统一返回安全错误结构
        raise HTTPException(status_code=422, detail="演示启动失败（输入校验或运行异常）") from exc


@router.post("/api/v1/demo/portfolio", status_code=201)
def run_portfolio_demo_endpoint(
    session: Session = Depends(get_session),
) -> dict:
    """Phase 12 演示：3 家公司投资组合 + 模拟新风险触发 Continuous Monitoring 告警。"""
    try:
        return run_portfolio_demo(session)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="组合演示启动失败") from exc


@router.get("/api/v1/demo")
def list_demos_endpoint(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    items = list_demos(session, limit=limit)
    return {"count": len(items), "demos": items}


@router.get("/api/v1/demo/{demo_id}")
def get_demo_endpoint(
    demo_id: str = Path(..., min_length=1, max_length=128),
    session: Session = Depends(get_session),
) -> dict:
    """查询演示运行：8 步记录 + 最终输出（reliability/risk/replay）。"""
    _validate_demo_id(demo_id)
    try:
        return get_demo(session, demo_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="演示不存在") from exc


@router.get("/api/v1/demo/{demo_id}/steps")
def get_demo_steps_endpoint(
    demo_id: str = Path(..., min_length=1, max_length=128),
    session: Session = Depends(get_session),
) -> dict:
    """查询演示步骤列表。"""
    _validate_demo_id(demo_id)
    try:
        steps = get_demo_steps(session, demo_id)
        return {
            "demo_id": demo_id,
            "count": len(steps),
            "steps": [s.to_dict() for s in steps],
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="演示不存在") from exc
