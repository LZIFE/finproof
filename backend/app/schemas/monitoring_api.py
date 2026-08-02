"""Monitoring API Schema（Phase 12）。"""

from pydantic import BaseModel, Field


class ThesisCreate(BaseModel):
    thesis_id: str = Field(min_length=1, max_length=40)
    company: str = Field(min_length=1, max_length=120)
    claim: str = Field(min_length=1)
    metric: str = ""
    metric_value: float | None = Field(default=None, ge=0.0)
    metric_unit: str = ""
    source: str = ""
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    portfolio_id: str | None = Field(default=None, max_length=40)
    project_id: int | None = Field(default=None, ge=1)
    metadata: dict = Field(default_factory=dict)


class NewFactItem(BaseModel):
    thesis_id: str
    new_fact: str
    new_metric_value: float | None = Field(default=None, ge=0.0)


class MonitoringRunRequest(BaseModel):
    portfolio_id: str | None = Field(default=None, max_length=40)
    new_facts: list[NewFactItem] = Field(min_length=1)


class AlertStatusUpdate(BaseModel):
    status: str = Field(pattern="^(OPEN|RESOLVED|IGNORED)$")
    note: str = ""
