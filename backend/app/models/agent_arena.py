"""FinProof Agent Arena 数据模型（Phase 19，任务书 §Workflow §数据库）。

数据库表：
- arena_runs      竞技运行（run_id / company / research_question / phase）
- arena_messages  辩论消息（role / phase / viewpoints / challenges / audit / evidence）
- arena_results   竞技结果（analyst_viewpoints / skeptic_challenges / auditor_report / score / winner）
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ArenaRunRow(Base):
    """竞技运行。"""

    __tablename__ = "arena_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # ARENA-XXXX
    company: Mapped[str] = mapped_column(String(120), index=True)
    research_question: Mapped[str] = mapped_column(Text, default="")
    phase: Mapped[str] = mapped_column(String(30), default="Analyst Generates", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ArenaMessageRow(Base):
    """辩论消息：role / phase / content / viewpoints / challenges / audit / evidence。"""

    __tablename__ = "arena_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("arena_runs.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str] = mapped_column(String(20), index=True)  # MSG-001
    role: Mapped[str] = mapped_column(String(20), index=True)  # Analyst / Skeptic / Auditor / Judge
    phase: Mapped[str] = mapped_column(String(30), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    viewpoints_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # list[AnalystViewpoint]
    challenges_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # list[SkepticChallenge]
    audit_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # AuditorReport
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ArenaResultRow(Base):
    """竞技结果：双方观点/挑战/审计 + 评分 + 辩论胜负。"""

    __tablename__ = "arena_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("arena_runs.id", ondelete="CASCADE"), index=True
    )
    result_id: Mapped[str] = mapped_column(String(40), index=True)  # AR-XXXX
    analyst_viewpoints_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skeptic_challenges_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    auditor_report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # ArenaScore
    final_arena_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    winner: Mapped[str] = mapped_column(String(20), default="", index=True)  # analyst / skeptic / tie
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
