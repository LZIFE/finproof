"""FinProof Demo Mode 数据模型（Phase 22，任务书 §数据库）。

demo_runs  / demo_steps 表：比赛演示模式运行与步骤记录。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DemoRunRow(Base):
    """演示运行。"""

    __tablename__ = "demo_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    demo_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # DEMO-XXXX
    company: Mapped[str] = mapped_column(String(120), index=True)
    report_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)  # PENDING / RUNNING / DONE / ERROR
    current_step: Mapped[str] = mapped_column(String(40), default="")
    reliability_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    arena_run_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    dashboard_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    audit_replay_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    risk_findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_replay_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DemoStepRow(Base):
    """演示步骤记录（任务书 §DemoStep）。"""

    __tablename__ = "demo_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    demo_id: Mapped[int] = mapped_column(
        ForeignKey("demo_runs.id", ondelete="CASCADE"), index=True
    )
    step_number: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(40), index=True)  # extract_claims / retrieve_evidence / ...
    frontend_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)  # PENDING / RUNNING / OK / SKIPPED / ERROR
    duration: Mapped[int] = mapped_column(Integer, default=0)  # ms
    input_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
