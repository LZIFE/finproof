"""FinProof Financial Reasoning 数据模型（Phase 16，任务书 §6）。

数据库表：
- reasoning_runs     推理运行（claim / 输入引用 / 规则版本 / results_count）
- reasoning_results  推理结果（reasoning_type / status / premises / assumptions /
                                   counter_evidence / logical_gap / 结论）

任务书 §6 字段必须保存：输入引用、规则版本、premises、assumptions、
counter_evidence、logical_gap 和结论。
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReasoningRunRow(Base):
    """推理运行。"""

    __tablename__ = "reasoning_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # REASON-RUN-XXXX
    claim_text: Mapped[str] = mapped_column(Text, default="")
    input_ref_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 输入引用（claim/verification/evidence/KG/risk）
    rule_version: Mapped[str] = mapped_column(String(40), default="r2025-phase16")
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ReasoningResultRow(Base):
    """推理结果：保存 premises / assumptions / counter_evidence / logical_gap / 结论。

    任务书 §6 要求字段均在此表：premises / assumptions / counter_evidence / logical_gap。
    """

    __tablename__ = "reasoning_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("reasoning_runs.id", ondelete="CASCADE"), index=True
    )
    result_id: Mapped[str] = mapped_column(String(40), index=True)  # RR-XXXX
    reasoning_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="OK", index=True)
    premises_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    counter_evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    logical_gap: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    explanation: Mapped[str] = mapped_column(Text, default="")  # 可解释说明
    suggested_safe_wording: Mapped[str] = mapped_column(Text, default="")  # 安全措辞
    triggered_rules_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_version: Mapped[str] = mapped_column(String(40), default="r2025-phase16")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
