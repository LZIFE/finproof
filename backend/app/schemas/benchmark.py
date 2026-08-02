"""Benchmark API Schema（Phase 11）。"""

from pydantic import BaseModel, Field


class BenchmarkRunRequest(BaseModel):
    """运行评测请求。"""

    dataset_name: str | None = Field(default=None)  # None 则用预置案例
    models: list[str] | None = Field(default=None)  # None 则 [FINPROOF, BASELINE_LLM]
    use_seed: bool = Field(default=True)  # 若 dataset_name 为 None，是否使用预置 50 条


class SeedDatasetRequest(BaseModel):
    """预置 Dataset 载入请求。"""

    dataset_name: str = Field(default="finproof_seed_v1")
