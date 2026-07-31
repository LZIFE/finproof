"""Investment Analyzer（Phase 7）：从 Audit + Risk 结果生成 Investment Risk Memo。

流程：audit 报告（verification_results/evidence_chain）→ 风险评分（risk_engine）→
投资风险分类聚合（risk_summary）→ Investment Risk Memo（Company/Overall/Key Risks/
Evidence Chain/Claims Requiring Review + 人工审核 NEED_REVIEW 初始化）。

不改变已有 Verification/Risk 逻辑；不输出投资建议或自动决策。
"""

import json

from sqlalchemy.orm import Session

from app.models import Document
from app.models.audit import AuditReport
from app.services.investment.risk_summary import build_risk_summary
from app.services.investment.schemas import REVIEW_NEED, InvestmentMemo, ReviewRecord
from app.services.risk.risk_engine import assess_audit

# 进入人工审核列表的分数阈值
REVIEW_SCORE_THRESHOLD = 60.0


def create_investment_memo(session: Session, audit_id: int) -> InvestmentMemo:
    """生成并持久化 Investment Risk Memo（含 NEED_REVIEW 审核记录），返回 memo（带 id）。"""
    memo = generate_investment_memo(session, audit_id)

    from app.models.investment import InvestmentMemoRow, InvestmentReviewRow

    row = InvestmentMemoRow(
        document_id=memo.document_id,
        audit_id=memo.audit_id,
        company=memo.company,
        stock_code=memo.stock_code,
        report_period=memo.report_period,
        overall_risk_score=memo.overall_risk_score,
        overall_risk_level=memo.overall_risk_level,
        key_risks_json=json.dumps(memo.key_risks, ensure_ascii=False),
        memo_json=json.dumps(memo.to_dict(), ensure_ascii=False),
    )
    session.add(row)
    session.flush()
    for r in memo.reviews:
        session.add(
            InvestmentReviewRow(
                memo_id=row.id,
                claim_id=r.claim_id,
                review_status=r.review_status,
                risk_score=r.risk_score,
                risk_type=r.risk_type,
            )
        )
    session.commit()
    memo.id = row.id
    return memo


def get_investment_memo(session: Session, memo_id: int) -> InvestmentMemo:
    """读取持久化的 memo（含最新审核记录）。"""
    from app.models.investment import InvestmentMemoRow, InvestmentReviewRow

    row = session.get(InvestmentMemoRow, memo_id)
    if row is None:
        raise LookupError(f"Investment Memo 不存在: {memo_id}")
    memo_dict = json.loads(row.memo_json or "{}")
    memo = InvestmentMemo(
        id=row.id,
        document_id=memo_dict.get("document_id", row.document_id),
        audit_id=memo_dict.get("audit_id", row.audit_id),
        company=row.company,
        stock_code=row.stock_code or "",
        report_period=row.report_period or "",
        overall_risk_score=row.overall_risk_score,
        overall_risk_level=row.overall_risk_level,
        key_risks=json.loads(row.key_risks_json or "[]"),
        evidence_chain=memo_dict.get("evidence_chain", []),
        claims_requiring_review=memo_dict.get("claims_requiring_review", []),
    )
    reviews = (
        session.query(InvestmentReviewRow)
        .filter(InvestmentReviewRow.memo_id == memo_id)
        .order_by(InvestmentReviewRow.id)
        .all()
    )
    memo.reviews = [
        ReviewRecord(
            claim_id=r.claim_id,
            review_status=r.review_status,
            note=r.note or "",
            reviewer=r.reviewer or "",
            risk_score=r.risk_score,
            risk_type=r.risk_type or "",
        )
        for r in reviews
    ]
    return memo


def update_review(
    session: Session,
    memo_id: int,
    claim_id: str,
    review_status: str,
    note: str = "",
    reviewer: str = "",
) -> ReviewRecord:
    """更新单条主张的审核状态（NEED_REVIEW / APPROVED / REJECTED）。"""
    from app.models.investment import InvestmentReviewRow

    if review_status not in ("NEED_REVIEW", "APPROVED", "REJECTED"):
        raise ValueError(f"非法审核状态: {review_status}")
    row = (
        session.query(InvestmentReviewRow)
        .filter(InvestmentReviewRow.memo_id == memo_id, InvestmentReviewRow.claim_id == claim_id)
        .first()
    )
    if row is None:
        raise LookupError(f"审核记录不存在: memo={memo_id} claim={claim_id}")
    row.review_status = review_status
    row.note = note
    row.reviewer = reviewer
    session.commit()
    return ReviewRecord(
        claim_id=row.claim_id,
        review_status=row.review_status,
        note=row.note or "",
        reviewer=row.reviewer or "",
        risk_score=row.risk_score,
        risk_type=row.risk_type or "",
    )


def generate_investment_memo(session: Session, audit_id: int) -> InvestmentMemo:
    """生成 Investment Risk Memo（不持久化，由调用方入库）。"""
    audit = session.get(AuditReport, audit_id)
    if audit is None:
        raise LookupError(f"审计任务不存在: {audit_id}")
    doc = session.get(Document, audit.document_id)

    report = json.loads(audit.report_json or "{}")
    verification_results = report.get("verification_results", [])
    evidence_chain = report.get("evidence_chain", [])

    # 风险评分（确定性重建，不重复入库）
    risk_report = assess_audit(session, audit_id, persist=False).to_dict()
    overall_score = risk_report["overall_risk_score"]
    overall_level = risk_report["overall_risk_level"]

    # claims 输入（来自 evidence_chain 的文本 + verification_type 推导 claim_type）
    chain_by_id = {c["claim_id"]: c for c in evidence_chain}
    claims: list[dict] = []
    for v in verification_results:
        cid = v.get("claim_id")
        chain = chain_by_id.get(cid, {})
        vtype = v.get("verification_type") or ""
        ct = "COMPARISON" if vtype == "COMPARISON_CHECK" else (
            "FINANCIAL_VALUE" if vtype in ("EXACT_VALUE_CHECK", "GROWTH_RATE_CHECK", "PERIOD_CHECK") else "OPINION"
        )
        claims.append(
            {
                "claim_id": cid,
                "claim_type": ct,
                "original_text": chain.get("claim") or cid,
            }
        )

    # 投资风险分类摘要
    summary = build_risk_summary(claims, verification_results, risk_report["claim_details"])

    # Claims Requiring Review：高优先级风险主张（risk_score ≥ 阈值）→ NEED_REVIEW
    requiring_review = []
    for item in summary["key_risks"]:
        if item["risk_score"] >= REVIEW_SCORE_THRESHOLD and item["verification_status"] != "SUPPORTED":
            requiring_review.append(
                {
                    "claim_id": item["claim_id"],
                    "claim": item["claim"],
                    "risk_score": item["risk_score"],
                    "risk_level": item["risk_level"],
                    "risk_type": item["risk_type"],
                    "category": item["category"],
                    "category_label": item["category_label"],
                    "review_status": REVIEW_NEED,
                }
            )

    memo = InvestmentMemo(
        document_id=audit.document_id,
        audit_id=audit_id,
        company=doc.company_name if doc else "",
        stock_code=doc.stock_code if doc else "",
        report_period=doc.report_period if doc else "",
        overall_risk_score=overall_score,
        overall_risk_level=overall_level,
        key_risks=summary["key_risks"],
        evidence_chain=evidence_chain,
        claims_requiring_review=requiring_review,
        reviews=[
            ReviewRecord(
                claim_id=r["claim_id"],
                review_status=REVIEW_NEED,
                risk_score=r["risk_score"],
                risk_type=r["risk_type"],
            )
            for r in requiring_review
        ],
    )
    return memo
