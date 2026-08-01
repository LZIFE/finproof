"""FinProof FinSim API Schemas（Phase 18）。"""

from pydantic import BaseModel, Field


class SimulationRunRequest(BaseModel):
    """模拟启动请求。"""

    scenario_type: str = Field(min_length=1, max_length=60)  # SCENARIO_TYPES
    company: str = Field(min_length=1, max_length=120)
    industry: str = Field(default="综合", max_length=60)
    difficulty: str = Field(default="Easy", max_length=10)  # DIFFICULTY_LEVELS
