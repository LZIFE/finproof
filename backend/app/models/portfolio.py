"""Portfolio Risk Dashboard 数据模型（Phase 12）。

数据库表：
- portfolio_projects        投资组合中的项目（公司/标的）
- portfolio_risk_snapshots  组合风险快照（聚合多个项目的风险评分）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PortfolioProjectRow(Base):
    """投资组合项目：一家公司在某个组合中的持仓与关联审计报告。"""

    __tablename__ = "portfolio_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(40), index=True)  # 组合标识 PF-XXXX
    company: Mapped[str] = mapped_column(String(120), default="")
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)  # 持仓权重 0-1
    audit_id: Mapped[int | None] = mapped_column(
        ForeignKey("audit_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    committee_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("committee_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    latest_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    latest_risk_level: Mapped[str] = mapped_column(String(10), default="LOW")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PortfolioRiskSnapshotRow(Base):
    """组合风险快照：一次聚合多个项目的风险评分结果。"""

    __tablename__ = "portfolio_risk_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(40), index=True)
    portfolio_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    portfolio_risk_level: Mapped[str] = mapped_column(String(10), default="LOW")
    company_ranking_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 排名列表
    risk_distribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 分布
    highest_risk_findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 完整快照
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
