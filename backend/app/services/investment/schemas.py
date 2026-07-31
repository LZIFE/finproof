"""投资尽调数据模型（Phase 7）。"""

from dataclasses import dataclass, field

# 人工审核状态
REVIEW_NEED = "NEED_REVIEW"
REVIEW_APPROVED = "APPROVED"
REVIEW_REJECTED = "REJECTED"

REVIEW_STATUSES = {REVIEW_NEED, REVIEW_APPROVED, REVIEW_REJECTED}

# 投资风险分类
RISK_CATEGORY_FINANCIAL = "FINANCIAL_RISK"
RISK_CATEGORY_BUSINESS = "BUSINESS_RISK"
RISK_CATEGORY_COMPETITIVE = "COMPETITIVE_RISK"
RISK_CATEGORY_MANAGEMENT = "MANAGEMENT_RISK"

RISK_CATEGORIES = {
    RISK_CATEGORY_FINANCIAL,
    RISK_CATEGORY_BUSINESS,
    RISK_CATEGORY_COMPETITIVE,
    RISK_CATEGORY_MANAGEMENT,
}


@dataclass
class ReviewRecord:
    """单条主张的人工审核记录。"""

    claim_id: str
    review_status: str = REVIEW_NEED
    note: str = ""
    reviewer: str = ""
    risk_score: float = 0.0
    risk_type: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "review_status": self.review_status,
            "note": self.note,
            "reviewer": self.reviewer,
            "risk_score": round(self.risk_score, 1),
            "risk_type": self.risk_type,
        }


@dataclass
class InvestmentMemo:
    """Investment Risk Memo：公司尽调风险备忘录。"""

    id: int | None = None
    document_id: int = 0
    audit_id: int = 0
    company: str = ""
    stock_code: str = ""
    report_period: str = ""
    overall_risk_score: float = 0.0
    overall_risk_level: str = "LOW"
    key_risks: list = field(default_factory=list)  # 按风险分类聚合
    evidence_chain: list = field(default_factory=list)
    claims_requiring_review: list = field(default_factory=list)  # 高优先级风险主张
    reviews: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "audit_id": self.audit_id,
            "company": self.company,
            "stock_code": self.stock_code,
            "report_period": self.report_period,
            "overall_risk_score": round(self.overall_risk_score, 1),
            "overall_risk_level": self.overall_risk_level,
            "key_risks": self.key_risks,
            "evidence_chain": self.evidence_chain,
            "claims_requiring_review": self.claims_requiring_review,
            "reviews": [r.to_dict() if isinstance(r, ReviewRecord) else r for r in self.reviews],
        }
