"""Audit Trail 数据模型（Phase 12）。

数据库表：
- audit_trail_logs  审计日志：user/action/timestamp/model_version/rule_version/evidence_used
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditTrailLogRow(Base):
    """审计日志：记录关键操作的执行人与上下文，用于合规审计与回溯。"""

    __tablename__ = "audit_trail_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    log_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # LOG-XXXX
    user: Mapped[str] = mapped_column(String(80), default="system", index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)  # e.g. RUN_COMMITTEE
    target_type: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    model_version: Mapped[str] = mapped_column(String(40), default="")
    rule_version: Mapped[str] = mapped_column(String(40), default="")
    evidence_used_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
