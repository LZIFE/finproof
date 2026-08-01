"""FinProof FinSim 数据模型（Phase 18，任务书 §3）。

数据库表：
- simulation_runs      模拟运行（run_id / scenario_id / scenario_json / phase / agent_name）
- simulation_steps     模拟步骤（step_id / phase / tool / evidence_count / findings_count）
- simulation_results   模拟结果（detected/missed/hallucination + score_json + final_score + success）
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SimulationRunRow(Base):
    """模拟运行。"""

    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # SIM-RUN-XXXX
    scenario_id: Mapped[str] = mapped_column(String(40), index=True)
    scenario_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # SimulationScenario
    agent_name: Mapped[str] = mapped_column(String(60), default="FinProof Research Agent")
    phase: Mapped[str] = mapped_column(String(30), default="Scenario", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SimulationStepRow(Base):
    """模拟步骤：phase / tool / input / output / evidence_count / findings_count。"""

    __tablename__ = "simulation_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str] = mapped_column(String(20), index=True)  # STEP-001
    phase: Mapped[str] = mapped_column(String(30), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SimulationResultRow(Base):
    """模拟结果：detected/missed/hallucination + 5 项评分 + success。"""

    __tablename__ = "simulation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), index=True
    )
    result_id: Mapped[str] = mapped_column(String(40), index=True)  # SIMRES-XXXX
    agent_run_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # AgentRunRecord
    detected_findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    missed_findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hallucination_findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # SimulationScore
    fin_agent_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
