"""FinProof Red Team 数据模型（Phase 14）。

数据库表：
- red_team_runs      Red Team 运行（run_id / metrics / reliability_score）
- red_team_cases     攻击案例（original_claim / attacked_claim / attack_type / expected_risk）
- red_team_results   检测结果（detected / error_type / evidence / risk_score）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RedTeamRunRow(Base):
    """Red Team 运行。"""

    __tablename__ = "red_team_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # RT-RUN-XXXX
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reliability_score_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attack_distribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class RedTeamCaseRow(Base):
    """攻击案例。"""

    __tablename__ = "red_team_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("red_team_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    original_claim: Mapped[str] = mapped_column(Text)
    attacked_claim: Mapped[str] = mapped_column(Text)
    attack_type: Mapped[str] = mapped_column(String(40), index=True)
    expected_risk: Mapped[float] = mapped_column(Float, default=60.0)
    company: Mapped[str] = mapped_column(String(120), default="")
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    metric: Mapped[str] = mapped_column(String(80), default="")
    original_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    attacked_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    period_original: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_attacked: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RedTeamResultRow(Base):
    """检测结果。"""

    __tablename__ = "red_team_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("red_team_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    detected: Mapped[bool] = mapped_column(Boolean, default=False)
    error_type: Mapped[str] = mapped_column(String(40), default="NONE")
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    verification_status: Mapped[str] = mapped_column(String(40), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
