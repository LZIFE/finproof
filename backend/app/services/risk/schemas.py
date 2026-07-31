"""风险评分数据模型（Phase 6）。"""

from dataclasses import dataclass, field


@dataclass
class RiskAssessment:
    """单条主张的风险评估结果。"""

    claim_id: str
    risk_score: float
    risk_level: str  # LOW | MEDIUM | HIGH
    risk_type: str  # FINANCIAL_ERROR | EVIDENCE_RISK | SEMANTIC_RISK | FORECAST_RISK
    risk_reason: list[str] = field(default_factory=list)
    verification_status: str = ""
    verification_type: str = ""
    confidence: float = 0.0
    evidence_quality: float = 0.3
    claim_importance: str = "MEDIUM"

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "risk_type": self.risk_type,
            "risk_reason": self.risk_reason,
            "verification_status": self.verification_status,
            "verification_type": self.verification_type,
            "confidence": round(self.confidence, 3),
            "evidence_quality": round(self.evidence_quality, 3),
            "claim_importance": self.claim_importance,
        }


@dataclass
class AuditRiskReport:
    """一次审计的整体风险报告。"""

    audit_id: int
    overall_risk_score: float
    overall_risk_level: str
    risk_distribution: dict = field(default_factory=dict)
    top_risks: list = field(default_factory=list)
    claim_details: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "overall_risk_score": round(self.overall_risk_score, 1),
            "overall_risk_level": self.overall_risk_level,
            "risk_distribution": self.risk_distribution,
            "top_risks": self.top_risks,
            "claim_details": self.claim_details,
        }
