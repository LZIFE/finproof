"""Regression tests for attributable-profit scope and summary recovery."""
from __future__ import annotations

import hashlib

import pytest

from app.db import SessionLocal
from app.models import Document, DocumentBlock, DocumentPage
from app.services.claim_router import route_claim
from app.services.evidence_retrieval.service import retrieve_for_claim
from app.services.verification.verification_service import verify_evidence_set
from app.services.verification_context import VerificationContext


@pytest.fixture()
def attributable_summary_document():
    with SessionLocal() as session:
        filename = "scope_summary_recovery_2025.pdf"
        document = Document(
            original_filename=filename,
            stored_filename=filename,
            document_type="pdf",
            document_role="SOURCE_DOCUMENT",
            company_name="范围测试公司",
            stock_code="009999",
            report_period="2025FY",
            publication_date=None,
            mime_type="application/pdf",
            file_size=1,
            sha256=hashlib.sha256(filename.encode()).hexdigest(),
            page_count=1,
            parse_status="COMPLETED",
            extraction_method="test",
        )
        session.add(document)
        session.flush()
        texts = [
            "范围测试公司2025 年度报告全文",
            "2025 年 2024 年 本年比上年增减 2023 年",
            "归属于上市公司股东的净利润（千元）\n12,422,233\n9,000,007\n38.02%",
            "归属于上市公司股东的\n扣除非经常性损益的净\n利润（元）",
            "8,815,635,943.27\n31,741,959,276.27\n-72.23%",
        ]
        page_text = "\n".join(texts)
        page = DocumentPage(
            document_id=document.id,
            page_index=0,
            page_number=7,
            printed_page_label=None,
            text=page_text,
            character_count=len(page_text),
            text_sha256=hashlib.sha256(page_text.encode()).hexdigest(),
        )
        session.add(page)
        session.flush()
        for index, text in enumerate(texts):
            session.add(
                DocumentBlock(
                    document_id=document.id,
                    page_id=page.id,
                    block_index=index,
                    block_type="text",
                    text=text,
                    reading_order=index,
                )
            )
        session.commit()
    return True


def _verify_official_style(session, claim: dict):
    raw = retrieve_for_claim(session, claim, top_k=10)
    candidates = [
        {
            "evidence_id": str(candidate.get("block_id") or "?"),
            "block_id": candidate.get("block_id"),
            "text": candidate.get("block_text") or "",
            "page": candidate.get("page_number"),
            "document_id": candidate.get("document_id"),
        }
        for candidate in raw
    ]
    result = verify_evidence_set(
        claim,
        candidates,
        route_claim(claim),
        VerificationContext(evidence_source="real_e2e"),
    )
    return raw, result


@pytest.mark.parametrize(
    "claim",
    [
        {
            "claim_id": "SCOPE-PARENT",
            "entity": "范围测试公司",
            "metric": "net_profit_attributable",
            "metric_code": "net_profit_attributable",
            "claim_type": "raw_number",
            "period": "2025FY",
            "value": 124.22,
            "unit": "亿元",
            "scope": "consolidated",
            "original_text": "归母净利润124.22亿元",
        },
        {
            "claim_id": "SCOPE-ADJUSTED",
            "entity": "范围测试公司",
            "metric": "deducted_net_profit",
            "metric_code": "deducted_net_profit",
            "claim_type": "raw_number",
            "period": "2025FY",
            "value": 88.16,
            "unit": "亿元",
            "scope": "consolidated",
            "original_text": "扣非归母净利润88.16亿元",
        },
    ],
)
def test_intrinsic_scope_summary_evidence_supports(
    attributable_summary_document,
    claim,
):
    with SessionLocal() as session:
        candidates, result = _verify_official_style(session, claim)
    assert candidates[0]["retrieval_method"] == "financial_summary_evidence"
    assert candidates[0]["financial_fact"] is None
    assert result.verification_status == "SUPPORTED"


def test_summary_recovery_requires_current_value_match(
    attributable_summary_document,
):
    claim = {
        "claim_id": "SCOPE-NO-MATCH",
        "entity": "范围测试公司",
        "metric": "deducted_net_profit",
        "metric_code": "deducted_net_profit",
        "claim_type": "raw_number",
        "period": "2025FY",
        "value": 99.99,
        "unit": "亿元",
        "scope": "consolidated",
        "original_text": "扣非归母净利润99.99亿元",
    }
    with SessionLocal() as session:
        candidates = retrieve_for_claim(session, claim, top_k=10)
    assert all(
        candidate.get("retrieval_method") != "financial_summary_evidence"
        for candidate in candidates
    )
