"""Financial AI Benchmark 数据模型（Phase 11）。

数据库表：
- benchmark_cases     评测案例（claim/category/gold_evidence/gold_result/risk_type）
- benchmark_runs     评测运行（dataset/models/error_distribution/comparison）
- benchmark_results  评测结果（逐案例逐模型的预测结论）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BenchmarkCaseRow(Base):
    """评测案例：AI 生成的金融主张 + 金标准结论。"""

    __tablename__ = "benchmark_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # CASE-XXXXX
    dataset_name: Mapped[str] = mapped_column(String(80), default="finproof_seed_v1", index=True)
    claim: Mapped[str] = mapped_column(Text)  # AI 生成的金融主张
    category: Mapped[str] = mapped_column(String(40), index=True)  # ERROR_TYPES
    company: Mapped[str] = mapped_column(String(120), default="")
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_period: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # 金标准字段
    gold_evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    gold_result: Mapped[str] = mapped_column(String(40), default="")  # GOLD_RESULTS
    gold_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_type: Mapped[str] = mapped_column(String(40), default="")

    is_error_case: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BenchmarkRunRow(Base):
    """评测运行：Dataset + 模型列表 + 错误分布 + 对比摘要。"""

    __tablename__ = "benchmark_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # RUN-YYYYMMDDHHMMSS
    dataset_name: Mapped[str] = mapped_column(String(80), default="")
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    models_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    error_distribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON dict
    comparison_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON dict
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BenchmarkResultRow(Base):
    """评测结果：逐案例逐模型的预测结论。"""

    __tablename__ = "benchmark_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(40), index=True)  # FINPROOF / BASELINE_LLM

    # 预测字段
    predicted_result: Mapped[str] = mapped_column(String(40), default="")  # GOLD_RESULTS
    predicted_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_risk_type: Mapped[str] = mapped_column(String(40), default="")
    detected_error: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
