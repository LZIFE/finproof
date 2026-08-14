"""通用 PDF 核验结果数据模型（Phase 24）。

一次 /api/v1/generic-verify 调用产生一条 GenericVerificationRun，
result_json 保存完整核验报告（verdicts / claims / error_report），
供历史查询与回放。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GenericVerificationRun(Base):
    """一次通用 PDF 核验运行。"""

    __tablename__ = "generic_verification_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(20), default="auto")
    total_claims: Mapped[int] = mapped_column(Integer, default=0)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    # 完整核验报告 JSON（verdicts / claims / error_report）
    result_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
