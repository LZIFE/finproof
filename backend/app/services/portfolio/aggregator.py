"""Portfolio Risk Dashboard Service（Phase 12）。

企业投资组合风险汇总：聚合多个投资项目的风险评分与 Findings。

输入：PortfolioProject 列表（每项含 company / latest_risk_score / weight）
输出：PortfolioRiskSnapshot
  - portfolio_risk_score     加权平均风险分
  - company_ranking          公司风险排名（按 risk_score 降序）
  - risk_distribution        风险分布（HIGH/MEDIUM/LOW 计数与占比）
  - highest_risk_findings    最高风险 Findings 摘要

设计约束：
- 不修改已有核心模块；Portfolio 作为新增聚合层。
- 不输出投资建议、不自动决定买卖。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.portfolio import (
    PortfolioProjectRow,
    PortfolioRiskSnapshotRow,
)
from app.schemas.portfolio import (
    CompanyRankingItem,
    HighestRiskFinding,
    PortfolioProject,
    PortfolioRiskSnapshot,
    RiskDistributionItem,
    risk_level_of,
)


# ---------------------------------------------------------------------------
# 项目 CRUD
# ---------------------------------------------------------------------------
def add_project(
    session: Session,
    portfolio_id: str,
    company: str,
    stock_code: str = "",
    weight: float = 0.0,
    audit_id: int | None = None,
    committee_report_id: int | None = None,
    latest_risk_score: float = 0.0,
) -> PortfolioProject:
    """添加一个投资项目到组合。"""
    row = PortfolioProjectRow(
        portfolio_id=portfolio_id,
        company=company,
        stock_code=stock_code,
        weight=weight,
        audit_id=audit_id,
        committee_report_id=committee_report_id,
        latest_risk_score=latest_risk_score,
        latest_risk_level=risk_level_of(latest_risk_score),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _project_from_row(row)


def list_projects(session: Session, portfolio_id: str) -> list[PortfolioProject]:
    rows = (
        session.query(PortfolioProjectRow)
        .filter(PortfolioProjectRow.portfolio_id == portfolio_id)
        .order_by(PortfolioProjectRow.id.asc())
        .all()
    )
    return [_project_from_row(r) for r in rows]


def get_project(session: Session, project_id: int) -> PortfolioProject:
    row = session.get(PortfolioProjectRow, project_id)
    if row is None:
        raise LookupError(f"项目不存在: {project_id}")
    return _project_from_row(row)


def update_project_risk(
    session: Session, project_id: int, risk_score: float
) -> PortfolioProject:
    row = session.get(PortfolioProjectRow, project_id)
    if row is None:
        raise LookupError(f"项目不存在: {project_id}")
    row.latest_risk_score = float(risk_score)
    row.latest_risk_level = risk_level_of(float(risk_score))
    session.commit()
    session.refresh(row)
    return _project_from_row(row)


# ---------------------------------------------------------------------------
# 风险聚合
# ---------------------------------------------------------------------------
def aggregate_risk(projects: list[PortfolioProject]) -> PortfolioRiskSnapshot:
    """聚合多个项目的风险，返回 PortfolioRiskSnapshot（未持久化）。"""
    if not projects:
        return PortfolioRiskSnapshot(
            portfolio_id="",
            portfolio_risk_score=0.0,
            portfolio_risk_level="LOW",
        )

    total_weight = sum(p.weight for p in projects)
    if total_weight <= 0:
        # 等权退路
        total_weight = float(len(projects))
        weighted = sum(p.latest_risk_score for p in projects) / total_weight
    else:
        weighted = sum(p.weight * p.latest_risk_score for p in projects) / total_weight

    # 公司风险排名（按 risk_score 降序）
    ranked = sorted(projects, key=lambda p: p.latest_risk_score, reverse=True)
    ranking: list[CompanyRankingItem] = []
    for idx, p in enumerate(ranked, start=1):
        ranking.append(
            CompanyRankingItem(
                company=p.company,
                stock_code=p.stock_code,
                risk_score=p.latest_risk_score,
                risk_level=risk_level_of(p.latest_risk_score),
                rank=idx,
            )
        )

    # 风险分布
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for p in projects:
        counts[risk_level_of(p.latest_risk_score)] += 1
    n = len(projects)
    distribution = [
        RiskDistributionItem(
            risk_level=lvl,
            count=counts[lvl],
            share=counts[lvl] / n if n else 0.0,
        )
        for lvl in ("HIGH", "MEDIUM", "LOW")
    ]

    # 最高风险 Findings（取排名前若干项作为摘要）
    highest: list[HighestRiskFinding] = []
    for p in ranked[:5]:
        lvl = risk_level_of(p.latest_risk_score)
        highest.append(
            HighestRiskFinding(
                company=p.company,
                finding=f"组合内风险分 {p.latest_risk_score:.1f}（{lvl}）",
                risk_score=p.latest_risk_score,
                risk_level=lvl,
                evidence=f"持仓权重 {p.weight:.2%}",
            )
        )

    portfolio_id = projects[0].portfolio_id
    return PortfolioRiskSnapshot(
        portfolio_id=portfolio_id,
        portfolio_risk_score=weighted,
        portfolio_risk_level=risk_level_of(weighted),
        company_ranking=ranking,
        risk_distribution=distribution,
        highest_risk_findings=highest,
        projects=projects,
    )


# ---------------------------------------------------------------------------
# 快照持久化与查询
# ---------------------------------------------------------------------------
def build_snapshot(session: Session, portfolio_id: str) -> PortfolioRiskSnapshot:
    """构建并保存组合风险快照。"""
    projects = list_projects(session, portfolio_id)
    snapshot = aggregate_risk(projects)
    snapshot.created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    row = PortfolioRiskSnapshotRow(
        portfolio_id=portfolio_id,
        portfolio_risk_score=snapshot.portfolio_risk_score,
        portfolio_risk_level=snapshot.portfolio_risk_level,
        company_ranking_json=json.dumps(
            [c.to_dict() for c in snapshot.company_ranking], ensure_ascii=False
        ),
        risk_distribution_json=json.dumps(
            [d.to_dict() for d in snapshot.risk_distribution], ensure_ascii=False
        ),
        highest_risk_findings_json=json.dumps(
            [f.to_dict() for f in snapshot.highest_risk_findings], ensure_ascii=False
        ),
        snapshot_json=json.dumps(snapshot.to_dict(), ensure_ascii=False),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    snapshot.id = row.id
    return snapshot


def list_snapshots(session: Session, portfolio_id: str) -> list[PortfolioRiskSnapshot]:
    rows = (
        session.query(PortfolioRiskSnapshotRow)
        .filter(PortfolioRiskSnapshotRow.portfolio_id == portfolio_id)
        .order_by(PortfolioRiskSnapshotRow.id.desc())
        .all()
    )
    return [_snapshot_from_row(r) for r in rows]


def get_snapshot(session: Session, snapshot_id: int) -> PortfolioRiskSnapshot:
    row = session.get(PortfolioRiskSnapshotRow, snapshot_id)
    if row is None:
        raise LookupError(f"快照不存在: {snapshot_id}")
    return _snapshot_from_row(row)


# ---------------------------------------------------------------------------
# Row → dataclass 转换
# ---------------------------------------------------------------------------
def _project_from_row(row: PortfolioProjectRow) -> PortfolioProject:
    return PortfolioProject(
        project_id=row.id,
        portfolio_id=row.portfolio_id,
        company=row.company,
        stock_code=row.stock_code or "",
        weight=row.weight,
        audit_id=row.audit_id,
        committee_report_id=row.committee_report_id,
        latest_risk_score=row.latest_risk_score,
        latest_risk_level=row.latest_risk_level or "LOW",
    )


def _snapshot_from_row(row: PortfolioRiskSnapshotRow) -> PortfolioRiskSnapshot:
    ranking = [
        CompanyRankingItem(
            company=c.get("company", ""),
            stock_code=c.get("stock_code", ""),
            risk_score=c.get("risk_score", 0.0),
            risk_level=c.get("risk_level", "LOW"),
            rank=c.get("rank", 0),
        )
        for c in json.loads(row.company_ranking_json or "[]")
    ]
    distribution = [
        RiskDistributionItem(
            risk_level=d.get("risk_level", "LOW"),
            count=d.get("count", 0),
            share=d.get("share", 0.0),
        )
        for d in json.loads(row.risk_distribution_json or "[]")
    ]
    highest = [
        HighestRiskFinding(
            company=f.get("company", ""),
            finding=f.get("finding", ""),
            risk_score=f.get("risk_score", 0.0),
            risk_level=f.get("risk_level", "LOW"),
            evidence=f.get("evidence", ""),
        )
        for f in json.loads(row.highest_risk_findings_json or "[]")
    ]
    return PortfolioRiskSnapshot(
        id=row.id,
        portfolio_id=row.portfolio_id,
        portfolio_risk_score=row.portfolio_risk_score,
        portfolio_risk_level=row.portfolio_risk_level,
        company_ranking=ranking,
        risk_distribution=distribution,
        highest_risk_findings=highest,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z"
        if row.created_at
        else "",
    )


__all__ = [
    "add_project",
    "list_projects",
    "get_project",
    "update_project_risk",
    "aggregate_risk",
    "build_snapshot",
    "list_snapshots",
    "get_snapshot",
]
