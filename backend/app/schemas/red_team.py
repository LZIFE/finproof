"""FinProof Red Team API Schemas（Phase 14）。"""

from pydantic import BaseModel, Field


class AttackGenerateRequest(BaseModel):
    """生成攻击案例请求。"""

    original_claim: str = Field(min_length=1, max_length=500)
    attack_type: str = Field(min_length=1, max_length=40)
    company: str = Field(default="", max_length=120)
    stock_code: str = Field(default="", max_length=20)


class DetectionRequest(BaseModel):
    """检测请求。"""

    case_id: str | None = Field(default=None, max_length=40)
    original_claim: str = Field(min_length=1, max_length=500)
    attacked_claim: str = Field(min_length=1, max_length=500)
    attack_type: str = Field(default="", max_length=40)
    expected_risk: float = Field(default=60.0, ge=0.0, le=100.0)
    company: str = Field(default="", max_length=120)
    stock_code: str = Field(default="", max_length=20)


class BaseClaimItem(BaseModel):
    """基础主张条目。"""

    text: str = Field(min_length=1, max_length=500)
    company: str = Field(default="", max_length=120)
    stock_code: str = Field(default="", max_length=20)
    attack_types: list[str] = Field(default_factory=list)


class StressTestRequest(BaseModel):
    """压力测试请求。"""

    base_claims: list[BaseClaimItem] = Field(min_length=1)
    count_per_type: int = Field(default=20, ge=1, le=200)
    seed: int = Field(default=42, ge=0)
