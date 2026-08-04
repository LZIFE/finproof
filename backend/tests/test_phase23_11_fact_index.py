"""Phase 23.11 Financial Fact Index tests (Task 4).

Tests build + query for Channel A. Verifies no forbidden gold fields.
"""
import pytest

from app.db import SessionLocal
from app.models.financial_fact import (
    FinancialFact,
    ensure_financial_fact_table,
)
from app.services.financial_fact_index import query_facts


@pytest.fixture
def session():
    s = SessionLocal()
    ensure_financial_fact_table(s)
    # Clean any existing test facts
    s.query(FinancialFact).filter(
        FinancialFact.fact_id.like("FF-TEST-%")
    ).delete()
    yield s
    s.query(FinancialFact).filter(
        FinancialFact.fact_id.like("FF-TEST-%")
    ).delete()
    s.commit()
    s.close()


def _make_fact(session, **kwargs):
    defaults = {
        "fact_id": "FF-TEST-1", "company": "五粮液", "document_id": 1,
        "document_type": "annual_report", "page": 5,
        "table_id": "T-1-5-0", "section_title": "主要会计数据",
        "table_title": "营业收入", "row_header": "营业收入",
        "parent_row_header": "", "column_header": "2025年",
        "period_header": "2025年", "metric": "营业收入",
        "metric_canonical": "revenue", "period": "2025FY",
        "period_type": "FY", "unit": "亿元", "currency": "CNY",
        "scope": "consolidated", "raw_value": "931.8",
        "normalized_value": 931.8, "source_block_ids": [1, 2],
        "neighboring_context": {},
    }
    defaults.update(kwargs)
    fact = FinancialFact(**defaults)
    session.add(fact)
    session.commit()
    return fact


def test_fact_insert(session):
    fact = _make_fact(session)
    assert fact.id is not None
    assert fact.fact_id == "FF-TEST-1"
    assert fact.metric_canonical == "revenue"


def test_query_facts_by_company_metric(session):
    _make_fact(session)
    claim = {
        "entity": "五粮液", "metric_code": "revenue", "period": "2025FY",
        "unit": "亿元", "scope": "consolidated",
    }
    from app.services.claim_router import route_claim
    routing = route_claim(claim)
    facts = query_facts(session, claim, routing, top_k=5)
    assert len(facts) >= 1
    assert any(f["page"] == 5 for f in facts)
    assert facts[0]["evidence_id"]


def test_query_facts_filters_wrong_company(session):
    _make_fact(session, fact_id="FF-TEST-2", company="美的集团",
               document_id=2)
    claim = {"entity": "五粮液", "metric_code": "revenue",
             "period": "2025FY"}
    from app.services.claim_router import route_claim
    routing = route_claim(claim)
    facts = query_facts(session, claim, routing, top_k=5)
    # Should not return 美的集团 facts when querying 五粮液
    assert all(f.get("company", "") != "美的集团" for f in facts)


def test_query_facts_returns_expected_fields(session):
    _make_fact(session)
    claim = {"entity": "五粮液", "metric_code": "revenue",
             "period": "2025FY"}
    from app.services.claim_router import route_claim
    routing = route_claim(claim)
    facts = query_facts(session, claim, routing, top_k=5)
    assert len(facts) >= 1
    f = facts[0]
    required = ["evidence_id", "text", "page", "document_id",
                "table_id", "row_header", "period_header", "unit",
                "scope", "normalized_value", "final_score"]
    for field in required:
        assert field in f, f"missing field {field}"


def test_fact_index_has_no_gold_fields(session):
    """FinancialFact must NOT have gold_page, gold_block_id, expected_verdict."""
    cols = [c.name for c in FinancialFact.__table__.columns]
    forbidden = ["gold_page", "gold_block_id", "expected_verdict",
                 "is_correct_answer", "dev_set_label", "claim_id_weight"]
    for f in forbidden:
        assert f not in cols, f"forbidden field {f} present in FinancialFact"


def test_rebuild_for_document_returns_count(session):
    """rebuild_for_document returns fact count (0 for nonexistent doc)."""
    from app.services.financial_fact_index import rebuild_for_document
    # Nonexistent document
    count = rebuild_for_document(session, doc_id=999999)
    assert count == 0
