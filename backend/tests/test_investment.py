"""Phase 7 Investment Due Diligence 专项测试：workflow / risk summary / review status / API。"""

import json

import pytest

from app.db import SessionLocal
from app.services.investment.investment_analyzer import (
    create_investment_memo,
    generate_investment_memo,
    get_investment_memo,
    update_review,
)
from app.services.investment.risk_summary import categorize_claim, build_risk_summary
from app.services.investment.schemas import (
    RISK_CATEGORY_BUSINESS,
    RISK_CATEGORY_COMPETITIVE,
    RISK_CATEGORY_FINANCIAL,
    RISK_CATEGORY_MANAGEMENT,
    REVIEW_APPROVED,
    REVIEW_NEED,
    REVIEW_REJECTED,
)


@pytest.fixture()
def audit_doc():
    """注册 REPORT_TO_VERIFY 研报并生成审计（供 memo 使用）。"""
    from app.services import document_service as dsvc
    from app.services.agent.executor import run_audit

    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="dd_report.md",
            data="# 尽调测试研报\n\n公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n归母净利润439.45亿元，同比增长38.02%。\n公司竞争优势领先行业。\n海外业务已成为公司利润增长的核心引擎。".encode("utf-8"),
            document_role="REPORT_TO_VERIFY",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        result = run_audit(s, doc.id, mode="mock")
        return result["audit_id"]


def test_investment_workflow(audit_doc):
    """投资尽调流程运行：audit → memo（公司/整体/Key Risks/证据链/待审核）+ 入库。"""
    with SessionLocal() as s:
        memo = create_investment_memo(s, audit_doc)
        d = memo.to_dict()
        assert d["company"] == "美的集团" and d["overall_risk_score"] > 0
        assert len(d["key_risks"]) > 0 and len(d["evidence_chain"]) > 0
        assert len(d["claims_requiring_review"]) > 0
        assert len(d["reviews"]) == len(d["claims_requiring_review"])
        assert all(r["review_status"] == REVIEW_NEED for r in d["reviews"])
        # 读回一致
        m2 = get_investment_memo(s, memo.id)
        assert m2.company == memo.company and len(m2.reviews) == len(memo.reviews)


def test_risk_summary_categories(audit_doc):
    """投资风险分类：Financial/Business/Competitive/Management 正确聚合。"""
    with SessionLocal() as s:
        memo = generate_investment_memo(s, audit_doc)
    categories = {k["category"] for k in memo.key_risks}
    # 研报含财务错误（增长 38.02%）与语义主张
    assert RISK_CATEGORY_FINANCIAL in categories
    assert RISK_CATEGORY_BUSINESS in categories or RISK_CATEGORY_COMPETITIVE in categories
    # 分类规则单测
    assert categorize_claim({}, {"verification_type": "GROWTH_RATE_CHECK"}, {"risk_type": "FINANCIAL_ERROR"}) == RISK_CATEGORY_FINANCIAL
    assert categorize_claim({"claim_type": "OPINION", "original_text": "业务持续改善"},
                            {"verification_type": "SEMANTIC_SUPPORT_CHECK"}, {}) == RISK_CATEGORY_BUSINESS
    assert categorize_claim({"claim_type": "COMPARISON", "original_text": "领先行业"},
                            {"verification_type": "COMPARISON_CHECK"}, {}) == RISK_CATEGORY_COMPETITIVE
    assert categorize_claim({"original_text": "管理层治理能力提升"},
                            {"verification_type": "SEMANTIC_SUPPORT_CHECK"}, {}) == RISK_CATEGORY_MANAGEMENT


def test_review_status(audit_doc):
    """人工审核：NEED_REVIEW → APPROVED / REJECTED 持久化。"""
    with SessionLocal() as s:
        memo = create_investment_memo(s, audit_doc)
        cid1 = memo.reviews[0].claim_id
        cid2 = memo.reviews[1].claim_id
        r1 = update_review(s, memo.id, cid1, REVIEW_APPROVED, note="核实一致", reviewer="投资经理A")
        r2 = update_review(s, memo.id, cid2, REVIEW_REJECTED, note="计算基数有误", reviewer="投资经理B")
        assert r1.review_status == REVIEW_APPROVED and r2.review_status == REVIEW_REJECTED
        m = get_investment_memo(s, memo.id)
        statuses = {r.claim_id: r.review_status for r in m.reviews}
        assert statuses[cid1] == REVIEW_APPROVED and statuses[cid2] == REVIEW_REJECTED
        with pytest.raises(ValueError):
            update_review(s, memo.id, cid1, "INVALID_STATUS")


def test_investment_api(audit_doc):
    """Investment API：POST memo / GET memo / POST reviews / 404 / 422。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    r = client.post("/api/v1/investment/memos", json={"audit_id": audit_doc})
    assert r.status_code == 201
    body = r.json()
    memo_id = body["id"]
    for k in ("company", "overall_risk_score", "key_risks", "evidence_chain", "claims_requiring_review", "reviews"):
        assert k in body

    r2 = client.get(f"/api/v1/investment/memos/{memo_id}")
    assert r2.status_code == 200 and r2.json()["id"] == memo_id

    cid = body["reviews"][0]["claim_id"]
    r3 = client.post(f"/api/v1/investment/memos/{memo_id}/reviews",
                     json={"claim_id": cid, "review_status": "APPROVED", "note": "ok", "reviewer": "经理"})
    assert r3.status_code == 200 and r3.json()["review_status"] == "APPROVED"

    assert client.get("/api/v1/investment/memos/99999").status_code == 404
    assert client.post(f"/api/v1/investment/memos/{memo_id}/reviews",
                       json={"claim_id": cid, "review_status": "BAD"}).status_code == 422
