"""Continuous Monitoring 数据模型（Phase 12）。

数据库表：
- investment_theses   历史投资观点（claim + 时间戳 + 关联项目）
- monitoring_alerts   监控告警（Thesis Conflict：新 Fact 与历史 Claim 冲突）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestmentThesisRow(Base):
    """历史投资观点：可被 Continuous Monitoring 追踪核对的 claim。"""

    __tablename__ = "investment_theses"

    id: Mapped[int] = mapped_column(primary_key=True)
    thesis_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # THS-XXXX
    portfolio_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    company: Mapped[str] = mapped_column(String(120), default="")
    claim: Mapped[str] = mapped_column(Text)  # 历史观点（claim）
    metric: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 关键指标名
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonitoringAlertRow(Base):
    """监控告警：新 Fact 与历史 Claim 出现 Thesis Conflict。"""

    __tablename__ = "monitoring_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # ALT-XXXX
    portfolio_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    thesis_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    company: Mapped[str] = mapped_column(String(120), default="")
    claim: Mapped[str] = mapped_column(Text)  # 历史 claim
    new_fact: Mapped[str] = mapped_column(Text)  # 新 Fact
    difference: Mapped[str] = mapped_column(Text, default="")  # 差异描述
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(10), default="LOW")
    conflict_type: Mapped[str] = mapped_column(String(30), default="METRIC_DRIFT")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN/RESOLVED/IGNORED
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
