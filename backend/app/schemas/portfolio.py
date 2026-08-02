"""Portfolio Risk Dashboard Schemas（Phase 12）。

企业投资组合风险汇总：聚合多个投资项目的风险评分与 Findings。

数据结构：
- PortfolioProject       投资组合中的单个项目（公司/标的）
- PortfolioRiskSnapshot  组合风险快照（portfolio risk score / company ranking /
                         risk distribution / highest risk findings）
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 风险等级阈值（与 Phase 6/7/8/9/10/11 保持一致）
# ---------------------------------------------------------------------------
def risk_level_of(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"


# ---------------------------------------------------------------------------
# PortfolioProject
# ---------------------------------------------------------------------------
@dataclass
class PortfolioProject:
    """投资组合中的单个项目。"""

    project_id: int
    portfolio_id: str
    company: str = ""
    stock_code: str = ""
    weight: float = 0.0
    audit_id: int | None = None
    committee_report_id: int | None = None
    latest_risk_score: float = 0.0
    latest_risk_level: str = "LOW"

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "portfolio_id": self.portfolio_id,
            "company": self.company,
            "stock_code": self.stock_code,
            "weight": round(self.weight, 4),
            "audit_id": self.audit_id,
            "committee_report_id": self.committee_report_id,
            "latest_risk_score": round(self.latest_risk_score, 1),
            "latest_risk_level": self.latest_risk_level,
        }


# ---------------------------------------------------------------------------
# CompanyRankingItem：公司风险排名条目
# ---------------------------------------------------------------------------
@dataclass
class CompanyRankingItem:
    company: str
    stock_code: str = ""
    risk_score: float = 0.0
    risk_level: str = "LOW"
    rank: int = 0  # 1 = 风险最高

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "company": self.company,
            "stock_code": self.stock_code,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
        }


# ---------------------------------------------------------------------------
# RiskDistributionItem：风险分布条目
# ---------------------------------------------------------------------------
@dataclass
class RiskDistributionItem:
    risk_level: str
    count: int
    share: float = 0.0  # 0-1

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "count": self.count,
            "share": round(self.share, 4),
        }


# ---------------------------------------------------------------------------
# HighestRiskFinding：最高风险 Finding
# ---------------------------------------------------------------------------
@dataclass
class HighestRiskFinding:
    company: str
    finding: str
    risk_score: float = 0.0
    risk_level: str = "LOW"
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "finding": self.finding,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# PortfolioRiskSnapshot
# ---------------------------------------------------------------------------
@dataclass
class PortfolioRiskSnapshot:
    """组合风险快照。"""

    id: int | None = None
    portfolio_id: str = ""
    portfolio_risk_score: float = 0.0
    portfolio_risk_level: str = "LOW"
    company_ranking: list[CompanyRankingItem] = field(default_factory=list)
    risk_distribution: list[RiskDistributionItem] = field(default_factory=list)
    highest_risk_findings: list[HighestRiskFinding] = field(default_factory=list)
    projects: list[PortfolioProject] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "portfolio_id": self.portfolio_id,
            "portfolio_risk_score": round(self.portfolio_risk_score, 1),
            "portfolio_risk_level": self.portfolio_risk_level,
            "company_ranking": [c.to_dict() for c in self.company_ranking],
            "risk_distribution": [d.to_dict() for d in self.risk_distribution],
            "highest_risk_findings": [f.to_dict() for f in self.highest_risk_findings],
            "projects": [p.to_dict() for p in self.projects],
            "created_at": self.created_at,
        }


__all__ = [
    "risk_level_of",
    "PortfolioProject",
    "CompanyRankingItem",
    "RiskDistributionItem",
    "HighestRiskFinding",
    "PortfolioRiskSnapshot",
]
