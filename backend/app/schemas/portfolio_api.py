"""Portfolio Risk Dashboard Schema（Phase 12）。"""

from pydantic import BaseModel, Field


class PortfolioProjectCreate(BaseModel):
    portfolio_id: str = Field(min_length=1, max_length=40)
    company: str = Field(min_length=1, max_length=120)
    stock_code: str = ""
    weight: float = Field(default=0.0, ge=0.0, le=1.0)
    audit_id: int | None = Field(default=None, ge=1)
    committee_report_id: int | None = Field(default=None, ge=1)
    latest_risk_score: float = Field(default=0.0, ge=0.0, le=100.0)


class PortfolioProjectUpdate(BaseModel):
    latest_risk_score: float = Field(ge=0.0, le=100.0)


class SnapshotBuildRequest(BaseModel):
    portfolio_id: str = Field(min_length=1, max_length=40)
