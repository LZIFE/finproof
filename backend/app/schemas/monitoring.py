"""Continuous Monitoring Schemas（Phase 12）。

投资观点追踪与新 Fact 对账。

数据结构：
- InvestmentThesis     历史投资观点（claim + metric/value/source）
- MonitoringAlert      监控告警（Thesis Conflict：新 Fact 与历史 Claim 冲突）
- ThesisConflict       检测器输出（claim / new_fact / difference / risk_score）
"""

from dataclasses import dataclass, field
from datetime import datetime


# ---------------------------------------------------------------------------
# 风险等级阈值（与各 Phase 一致）
# ---------------------------------------------------------------------------
def risk_level_of(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"


# ---------------------------------------------------------------------------
# InvestmentThesis
# ---------------------------------------------------------------------------
@dataclass
class InvestmentThesis:
    """历史投资观点：可被 Continuous Monitoring 追踪核对的 claim。"""

    thesis_id: str  # THS-XXXX
    company: str = ""
    claim: str = ""
    metric: str = ""  # 关键指标名（如 "毛利率"）
    metric_value: float | None = None
    metric_unit: str = ""  # "%" / "亿元" 等
    source: str = ""
    risk_score: float = 0.0
    portfolio_id: str | None = None
    project_id: int | None = None
    metadata: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "thesis_id": self.thesis_id,
            "company": self.company,
            "claim": self.claim,
            "metric": self.metric,
            "metric_value": self.metric_value,
            "metric_unit": self.metric_unit,
            "source": self.source,
            "risk_score": round(self.risk_score, 1),
            "portfolio_id": self.portfolio_id,
            "project_id": self.project_id,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# ThesisConflict：检测器输出
# ---------------------------------------------------------------------------
@dataclass
class ThesisConflict:
    """Thesis Conflict：新 Fact 与历史 claim 不一致或方向相反。"""

    thesis_id: str
    company: str = ""
    claim: str = ""  # 历史 claim
    new_fact: str = ""  # 新 Fact
    difference: str = ""  # 差异描述
    risk_score: float = 0.0  # 冲突风险分
    conflict_type: str = "METRIC_DRIFT"  # METRIC_DRIFT / DIRECTION_REVERSAL / NEW_RISK
    portfolio_id: str | None = None
    project_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "thesis_id": self.thesis_id,
            "company": self.company,
            "claim": self.claim,
            "new_fact": self.new_fact,
            "difference": self.difference,
            "risk_score": round(self.risk_score, 1),
            "conflict_type": self.conflict_type,
            "portfolio_id": self.portfolio_id,
            "project_id": self.project_id,
        }


# ---------------------------------------------------------------------------
# MonitoringAlert：告警记录（含 ThesisConflict + 状态）
# ---------------------------------------------------------------------------
@dataclass
class MonitoringAlert:
    alert_id: str  # ALT-XXXX
    thesis_id: str
    company: str = ""
    claim: str = ""
    new_fact: str = ""
    difference: str = ""
    risk_score: float = 0.0
    risk_level: str = "LOW"
    conflict_type: str = "METRIC_DRIFT"
    status: str = "OPEN"  # OPEN / RESOLVED / IGNORED
    portfolio_id: str | None = None
    project_id: int | None = None
    metadata: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "thesis_id": self.thesis_id,
            "company": self.company,
            "claim": self.claim,
            "new_fact": self.new_fact,
            "difference": self.difference,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "conflict_type": self.conflict_type,
            "status": self.status,
            "portfolio_id": self.portfolio_id,
            "project_id": self.project_id,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


__all__ = [
    "risk_level_of",
    "InvestmentThesis",
    "ThesisConflict",
    "MonitoringAlert",
]
