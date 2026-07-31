"""主张提取服务层单元测试：运行编排 / force 语义 / 角色拒绝 / 回滚 / 人工审核。"""

import pytest

from app.core.exceptions import AppError
from app.db import SessionLocal
from app.models import Claim, Document, ExtractionRun
from app.services import claim_service as csvc
from app.services import document_service as dsvc

REPORT_TEXT = "# 标题\n\n公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n\n归母净利润439.45亿元。\n"


def _register_report(session, role="REPORT_TO_VERIFY") -> int:
    doc, _ = dsvc.register_document(
        session, filename="report.md", data=REPORT_TEXT.encode("utf-8"),
        document_role=role, company_name="美的集团", stock_code="000333",
        report_period="2025FY",
    )
    return doc.id


def test_run_mock_extraction():
    with SessionLocal() as s:
        doc_id = _register_report(s)
        run, created = csvc.run_claim_extraction(s, doc_id, mode="mock", force=False)
        assert created and run.status == "COMPLETED"
        assert run.mode == "mock" and run.provider == "mock"
        claims = s.query(Claim).filter(Claim.extraction_run_id == run.id).all()
        assert len(claims) > 0
        assert all(c.claim_uid.startswith(f"CLM-RUN{run.id}-") for c in claims)
        assert all(c.source_block_id is not None for c in claims)  # 可追溯


def test_force_false_reuses_existing_run():
    with SessionLocal() as s:
        doc_id = _register_report(s)
        run1, _ = csvc.run_claim_extraction(s, doc_id, mode="mock", force=False)
        run2, created = csvc.run_claim_extraction(s, doc_id, mode="mock", force=False)
        assert created is False and run2.id == run1.id


def test_force_true_creates_new_run():
    with SessionLocal() as s:
        doc_id = _register_report(s)
        run1, _ = csvc.run_claim_extraction(s, doc_id, mode="mock", force=False)
        run2, created = csvc.run_claim_extraction(s, doc_id, mode="mock", force=True)
        assert created and run2.id != run1.id


def test_non_report_document_rejected():
    with SessionLocal() as s:
        doc_id = _register_report(s, role="SOURCE_DOCUMENT")
        with pytest.raises(AppError) as ei:
            csvc.run_claim_extraction(s, doc_id, mode="mock")
        assert ei.value.code == "INVALID_DOCUMENT_ROLE"


def test_missing_document_404():
    with SessionLocal() as s:
        with pytest.raises(AppError) as ei:
            csvc.run_claim_extraction(s, 99999, mode="mock")
        assert ei.value.code == "DOCUMENT_NOT_FOUND"


def test_failure_rollback_keeps_failed_run(monkeypatch):
    class Boom:
        def extract_claims(self, ctx, blocks):
            raise AppError("模拟失败", 500, "BOOM")

    monkeypatch.setattr(csvc, "get_claim_provider", lambda mode: Boom())
    with SessionLocal() as s:
        doc_id = _register_report(s)
        with pytest.raises(AppError) as ei:
            csvc.run_claim_extraction(s, doc_id, mode="mock", force=True)
        assert ei.value.code == "BOOM"
        failed = s.query(ExtractionRun).filter(ExtractionRun.status == "FAILED").first()
        assert failed is not None and failed.error_code == "BOOM"
        assert s.query(Claim).filter(Claim.extraction_run_id == failed.id).count() == 0


def test_review_status_and_changes_preserve_original():
    with SessionLocal() as s:
        doc_id = _register_report(s)
        run, _ = csvc.run_claim_extraction(s, doc_id, mode="mock")
        claim = s.query(Claim).filter(Claim.extraction_run_id == run.id).first()
        original_value = claim.reported_value
        csvc.review_claim(s, claim.id, "APPROVED", comment="人工确认")
        c2 = s.get(Claim, claim.id)
        assert c2.review_status == "APPROVED" and c2.review_comment == "人工确认"
        assert c2.reviewed_at is not None
        csvc.review_claim(s, claim.id, "EDITED", comment="修正", changes={"reported_value": 1.0})
        c3 = s.get(Claim, claim.id)
        assert c3.review_status == "EDITED"
        assert "1.0" in c3.review_changes
        assert c3.reported_value == original_value  # 原始系统输出未被覆盖


def test_list_claims_filters():
    with SessionLocal() as s:
        doc_id = _register_report(s)
        run, _ = csvc.run_claim_extraction(s, doc_id, mode="mock")
        total, _ = csvc.list_claims(s, doc_id, page=1, page_size=10)
        assert total > 0
        total_high, _ = csvc.list_claims(s, doc_id, risk_level="HIGH")
        assert 0 < total_high <= total
        total_growth, _ = csvc.list_claims(s, doc_id, claim_type="GROWTH_RATE")
        assert total_growth >= 1
