"""Autonomous Investigation Agent 数据模型（Phase 13）。

数据库表（任务书 §7）：
- investigation_runs       调查运行（trace_id / claim_context / plan / steps / evidence / conclusion）
- investigation_steps       调查步骤（step / tool / input / output / timestamp / reasoning / evidence_source）
- investigation_memory      Agent 记忆（company / historical_risk / previous_findings / resolved_issues）

字段必须包含（任务书 §7）：
- trace_id
- tool_name
- result
- evidence_source
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestigationRunRow(Base):
    """自主调查运行。"""

    __tablename__ = "investigation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # TRACE-XXXX
    run_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # INV-XXXX
    claim_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    conclusion_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class InvestigationStepRow(Base):
    """自主调查步骤（execution_trace）。

    任务书 §4 字段：step / tool / input / output / timestamp
    任务书 §7 字段：trace_id / tool_name / result / evidence_source
    """

    __tablename__ = "investigation_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"), index=True
    )
    trace_id: Mapped[str] = mapped_column(String(60), index=True)  # 关联 run.trace_id
    step: Mapped[int] = mapped_column(Integer, default=0)
    tool: Mapped[str] = mapped_column(String(40), index=True)  # tool_name
    purpose: Mapped[str] = mapped_column(Text, default="")
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    result: Mapped[str] = mapped_column(String(80), default="")  # 简要结果
    evidence_source_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InvestigationMemoryRow(Base):
    """Agent 记忆（任务书 §5）。"""

    __tablename__ = "investigation_memory"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    historical_risk_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_issues_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
