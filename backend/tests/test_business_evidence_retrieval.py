"""Regression tests for the strict Business Evidence Layer."""
from __future__ import annotations

import hashlib

import pytest

from app.db import SessionLocal
from app.models import Document, DocumentBlock, DocumentPage
from app.services.claim_router import route_claim
from app.services.evidence_retrieval.business_evidence import (
    is_business_evidence_claim,
)
from app.services.evidence_retrieval.service import retrieve_for_claim
from app.services.verification.verification_service import (
    verify_claim_production,
    verify_evidence_set,
)
from app.services.verification_context import VerificationContext


def _add_document(session, company: str, stock_code: str, filename: str, pages: dict[int, list[str]]) -> int:
    digest = hashlib.sha256(f"{company}:{filename}".encode()).hexdigest()
    doc = Document(
        original_filename=filename,
        stored_filename=filename,
        document_type="pdf",
        document_role="SOURCE_DOCUMENT",
        company_name=company,
        stock_code=stock_code,
        report_period="2025FY",
        publication_date=None,
        mime_type="application/pdf",
        file_size=1,
        sha256=digest,
        page_count=len(pages),
        parse_status="COMPLETED",
        extraction_method="test",
    )
    session.add(doc)
    session.flush()
    for page_index, (page_number, texts) in enumerate(sorted(pages.items())):
        page_text = "\n".join(texts)
        page = DocumentPage(
            document_id=doc.id,
            page_index=page_index,
            page_number=page_number,
            printed_page_label=None,
            text=page_text,
            character_count=len(page_text),
            text_sha256=hashlib.sha256(page_text.encode()).hexdigest(),
        )
        session.add(page)
        session.flush()
        for block_index, text in enumerate(texts):
            session.add(
                DocumentBlock(
                    document_id=doc.id,
                    page_id=page.id,
                    block_index=block_index,
                    block_type="text",
                    text=text,
                    reading_order=block_index,
                )
            )
    session.flush()
    return doc.id


@pytest.fixture()
def business_documents():
    with SessionLocal() as session:
        _add_document(
            session,
            "美的集团",
            "000333",
            "midea_2025.pdf",
            {
                17: [
                    "1、深化落实科技领先战略，支撑国内高端品牌和海外OBM优先战略",
                    "公司持续推动产品创新与全球业务发展。",
                ],
                41: ["2025年中央空调销售额占比超过20%，保持行业第一。"],
                135: ["营业收入 458,502,407 千元 2025年度"],
            },
        )
        _add_document(
            session,
            "五粮液",
            "000858",
            "wuliangye_2025.pdf",
            {
                1: [
                    "宜宾五粮液股份有限公司",
                    "2025 年度报告",
                    "董事长 华涛（代）（签名）",
                    "2026 年4 月30 日",
                ],
                6: [
                    "股票简称 五粮液 股票代码 000858",
                    "股票上市证券交易所 深圳证券交易所",
                ],
                85: ["消费税 酒类产品计税价格或出厂价格 10%、20%；0.5元/500ml"],
            },
        )
        session.commit()
    return True


def _official_style_verify(session, claim: dict):
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


def test_strategy_evidence_enters_top3_and_supports(business_documents):
    claim = {
        "claim_id": "BUS-STRATEGY",
        "entity": "美的集团",
        "metric": "overseas_obm_strategy",
        "claim_type": "business_fact",
        "period": "2025FY",
        "scope": "consolidated",
        "original_text": '公司持续深化"国内高端品牌和海外OBM优先"战略',
    }
    with SessionLocal() as session:
        candidates, result = _official_style_verify(session, claim)
    assert candidates
    assert candidates[0]["retrieval_method"] == "business_evidence"
    assert "海外OBM" in candidates[0]["block_text"]
    assert result.verification_status == "SUPPORTED"


def test_publication_cover_window_refutes_wrong_date(business_documents):
    claim = {
        "claim_id": "BUS-DATE",
        "entity": "五粮液",
        "metric": "publication_date",
        "claim_type": "business_fact",
        "period": "2025FY",
        "scope": "consolidated",
        "original_text": "根据公司2025年3月31日发布的2025年年度报告",
    }
    with SessionLocal() as session:
        candidates, result = _official_style_verify(session, claim)
        production = verify_claim_production(claim, session, top_k=10)
    assert len(candidates) == 1
    assert "2025 年度报告" in candidates[0]["evidence_text"]
    assert "2026 年4 月30 日" in candidates[0]["evidence_text"]
    assert result.verification_status == "REFUTED"
    assert production.verification_status == "REFUTED"


def test_listing_components_are_reconstructed_across_blocks(business_documents):
    claim = {
        "claim_id": "BUS-LISTING",
        "entity": "五粮液",
        "metric": "listing_info",
        "claim_type": "business_fact",
        "scope": "consolidated",
        "original_text": "宜宾五粮液股份有限公司在深圳证券交易所上市，股票代码000858",
    }
    with SessionLocal() as session:
        candidates, result = _official_style_verify(session, claim)
    assert len(candidates) == 1
    assert len(candidates[0]["source_block_ids"]) == 2
    assert "000858" in candidates[0]["block_text"]
    assert "深圳证券交易所" in candidates[0]["block_text"]
    assert result.verification_status == "SUPPORTED"


@pytest.mark.parametrize(
    ("claim", "expected_metric"),
    [
        (
            {
                "claim_id": "BUS-COMPARISON",
                "entity": "美的集团",
                "metric": "robot_margin_vs_industry",
                "claim_type": "comparison",
                "period": "2025FY",
                "value": 20,
                "unit": "个百分点",
                "scope": "consolidated",
                "original_text": "机器人业务毛利率高于行业平均水平20个百分点",
            },
            "robot_margin_vs_industry",
        ),
        (
            {
                "claim_id": "BUS-PRICE",
                "entity": "五粮液",
                "metric": "avg_selling_price",
                "claim_type": "business_fact",
                "period": "2025FY",
                "value": 1000,
                "unit": "元",
                "scope": "consolidated",
                "original_text": "公司2025年单瓶产品平均出厂价超过1000元",
            },
            "avg_selling_price",
        ),
    ],
)
def test_unsupported_business_numeric_claims_abstain(
    business_documents,
    claim,
    expected_metric,
):
    assert claim["metric"] == expected_metric
    with SessionLocal() as session:
        candidates, result = _official_style_verify(session, claim)
    assert candidates == []
    assert result.verification_status == "INSUFFICIENT_EVIDENCE"


def test_financial_claim_stays_on_financial_path(business_documents):
    claim = {
        "claim_id": "FIN-REVENUE",
        "entity": "美的集团",
        "metric": "revenue",
        "claim_type": "raw_number",
        "period": "2025FY",
        "value": 4585.02407,
        "unit": "亿元",
        "scope": "consolidated",
        "original_text": "2025年度营业收入4585.02407亿元",
    }
    assert is_business_evidence_claim(claim) is False
    with SessionLocal() as session:
        candidates = retrieve_for_claim(session, claim, top_k=5)
    assert candidates
    assert all(candidate.get("retrieval_method") != "business_evidence" for candidate in candidates)
