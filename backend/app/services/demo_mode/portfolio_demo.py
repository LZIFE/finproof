"""Phase 12 · Enterprise Investment Governance Demo。

演示场景（任务书 §Demo）：
- 投资组合：3 家公司（美的集团 / 格力电器 / 海尔智家）
- 模拟：某公司出现新风险（Continuous Monitoring 触发 Thesis Conflict）
- 输出：Portfolio Risk Snapshot + Monitoring Alerts + Audit Trail

设计约束：
- **不新增分析能力**，仅编排 Phase 12 已有模块（portfolio / monitoring / audit_trail）。
- **不修改已有 8 步比赛 demo**（demo_runner.start_demo）。
- **不输出投资建议 / 交易 / 股票推荐**。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.audit_trail import log_audit
from app.services.monitoring import (
    add_thesis,
    list_alerts,
    run_monitoring,
)
from app.services.portfolio import (
    add_project,
    build_snapshot,
    list_projects,
    update_project_risk,
)
from app.services.demo_mode.schemas import _now_iso, contains_forbidden_content

# ---------------------------------------------------------------------------
# 固定 Demo Case（3 家公司组合 + 模拟新风险）
# ---------------------------------------------------------------------------
DEMO_PORTFolio_ID = "PF-DEMO-001"

DEMO_PORTFolio_COMPANIES = [
    {
        "company": "美的集团",
        "stock_code": "000333",
        "weight": 0.40,
        "latest_risk_score": 42.0,  # MEDIUM
        "thesis_id": "THS-DEMO-001",
        "thesis_claim": "海外业务同比增长 13%",
        "thesis_metric": "海外业务同比",
        "thesis_metric_value": 13.0,
        "thesis_metric_unit": "%",
        "thesis_source": "2024 Q1 报告",
    },
    {
        "company": "格力电器",
        "stock_code": "000651",
        "weight": 0.30,
        "latest_risk_score": 28.0,  # LOW
        "thesis_id": "THS-DEMO-002",
        "thesis_claim": "空调国内市占率维持 30%",
        "thesis_metric": "空调国内市占率",
        "thesis_metric_value": 30.0,
        "thesis_metric_unit": "%",
        "thesis_source": "2024 行业研报",
    },
    {
        "company": "海尔智家",
        "stock_code": "600690",
        "weight": 0.30,
        "latest_risk_score": 55.0,  # MEDIUM
        "thesis_id": "THS-DEMO-003",
        "thesis_claim": "海外业务利润贡献占比 40%",
        "thesis_metric": "海外业务利润占比",
        "thesis_metric_value": 40.0,
        "thesis_metric_unit": "%",
        "thesis_source": "2024 Q1 报告",
    },
]

# 模拟新风险：美的集团海外业务同比从 13% 下滑至 5%（Thesis Conflict: METRIC_DRIFT）
DEMO_NEW_FACTS = [
    {
        "thesis_id": "THS-DEMO-001",
        "new_fact": "2024 Q2 财报：海外业务同比仅增长 5%",
        "new_metric_value": 5.0,
    },
]


def run_portfolio_demo(session: Session, portfolio_id: str = DEMO_PORTFolio_ID) -> dict:
    """执行 Phase 12 Enterprise Investment Governance Demo。

    步骤：
    1. 创建 3 家公司组合项目
    2. 为每家公司登记历史投资观点（Thesis）
    3. 构建组合风险快照（Portfolio Risk Snapshot）
    4. 模拟新风险：对 Q2 新 Fact 运行 Continuous Monitoring
    5. 记录 Audit Trail（全程留痕）

    返回：dict 含 snapshot / alerts / audit_log。
    """
    demo_started_at = _now_iso()

    # ① 记录 demo 启动（Audit Trail）
    start_log = log_audit(
        session,
        user="demo_runner",
        action="RUN_PORTFolio_DEMO",
        target_type="portfolio",
        target_id=None,
        model_version="phase12-v1",
        rule_version="phase12-r1",
        evidence_used=[{"source": "demo_scenario", "text": "3-company portfolio + new risk"}],
        detail={"portfolio_id": portfolio_id, "started_at": demo_started_at},
    )

    # ② 创建 3 家公司组合项目（若已存在则更新风险分）
    projects: list[dict] = []
    for c in DEMO_PORTFolio_COMPANIES:
        existing = list_projects(session, portfolio_id)
        match = [p for p in existing if p.company == c["company"]]
        if match:
            project = update_project_risk(session, match[0].project_id, c["latest_risk_score"])
        else:
            project = add_project(
                session,
                portfolio_id=portfolio_id,
                company=c["company"],
                stock_code=c["stock_code"],
                weight=c["weight"],
                latest_risk_score=c["latest_risk_score"],
            )
        projects.append(project.to_dict())

        # ③ 登记历史投资观点（Thesis）
        existing_theses = [
            t for t in _list_theses_safe(session, portfolio_id)
            if t.thesis_id == c["thesis_id"]
        ]
        if not existing_theses:
            add_thesis(
                session,
                thesis_id=c["thesis_id"],
                company=c["company"],
                claim=c["thesis_claim"],
                metric=c["thesis_metric"],
                metric_value=c["thesis_metric_value"],
                metric_unit=c["thesis_metric_unit"],
                source=c["thesis_source"],
                risk_score=c["latest_risk_score"],
                portfolio_id=portfolio_id,
                project_id=project.project_id,
                metadata={"demo": True},
            )

    # ④ 构建组合风险快照
    snapshot = build_snapshot(session, portfolio_id)

    # ⑤ 模拟新风险：对 Q2 新 Fact 运行 Continuous Monitoring
    alerts_raw = run_monitoring(session, portfolio_id, DEMO_NEW_FACTS)
    alerts = [a.to_dict() for a in alerts_raw]

    # ⑥ 记录 demo 完成（Audit Trail，含 evidence_used = snapshot + alerts）
    complete_log = log_audit(
        session,
        user="demo_runner",
        action="RUN_PORTFolio_DEMO_DONE",
        target_type="portfolio",
        target_id=None,
        model_version="phase12-v1",
        rule_version="phase12-r1",
        evidence_used=[
            {"source": "portfolio_snapshot", "text": f"score={snapshot.portfolio_risk_score:.1f}"},
            {"source": "monitoring_alerts", "text": f"count={len(alerts)}"},
        ],
        detail={
            "portfolio_id": portfolio_id,
            "started_at": demo_started_at,
            "finished_at": _now_iso(),
            "snapshot_id": snapshot.id,
            "alerts_count": len(alerts),
        },
    )

    result = {
        "demo": "phase12_enterprise_investment_governance",
        "portfolio_id": portfolio_id,
        "started_at": demo_started_at,
        "finished_at": _now_iso(),
        "projects": projects,
        "snapshot": snapshot.to_dict(),
        "monitoring_alerts": alerts,
        "audit_log": {
            "start": start_log.to_dict(),
            "complete": complete_log.to_dict(),
        },
        "scenario_note": (
            "模拟场景：美的集团 2024 Q2 海外业务同比从 13% 下滑至 5%，"
            "Continuous Monitoring 检测到 Thesis Conflict 并生成告警。"
        ),
    }

    # 护栏：不输出禁止词
    if contains_forbidden_content(json.dumps(result, ensure_ascii=False)):
        raise RuntimeError("demo 输出含禁止词（投资建议/股票推荐）")

    return result


def _list_theses_safe(session: Session, portfolio_id: str) -> list[Any]:
    """安全拉取 thesis 列表（避免循环导入）。"""
    from app.services.monitoring import list_theses
    return list_theses(session, portfolio_id)


__all__ = [
    "DEMO_PORTFolio_ID",
    "DEMO_PORTFolio_COMPANIES",
    "DEMO_NEW_FACTS",
    "run_portfolio_demo",
]
