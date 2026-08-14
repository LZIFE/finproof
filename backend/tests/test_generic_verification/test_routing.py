"""backend/tests/test_generic_verification/test_routing.py"""
from app.services.generic_verification.routing import (
    ROUTE_CROSS_DOC,
    ROUTE_EXTERNAL,
    ROUTE_INTERNAL,
    route_claim,
)
from app.services.generic_verification.schemas import GenericClaim


def _claim(**kw) -> GenericClaim:
    base = dict(claim_id="GCLM-001", source_text="x", claim_kind="FACT",
                page_number=1, block_index=0, entities=["公司A"], numbers=[],
                dates=[], cross_refs=[], extraction_method="rules", confidence=0.5)
    base.update(kw)
    return GenericClaim(**base)


def test_opinion_not_verifiable():
    assert route_claim(_claim(claim_kind="OPINION"), has_evidence=False) == []


def test_prediction_not_verifiable():
    assert route_claim(_claim(claim_kind="PREDICTION"), has_evidence=False) == []


def test_cross_ref_routes_internal():
    c = _claim(cross_refs=["第 3 章"])
    assert ROUTE_INTERNAL in route_claim(c, has_evidence=False)


def test_evidence_routes_cross_doc():
    c = _claim(entities=["公司A"], numbers=[{"value": 1.2, "unit": "亿", "context": "营收"}])
    assert ROUTE_CROSS_DOC in route_claim(c, has_evidence=True)


def test_plain_fact_routes_external():
    c = _claim(claim_kind="FACT", entities=["北京"])
    routes = route_claim(c, has_evidence=False)
    assert ROUTE_EXTERNAL in routes
    assert ROUTE_INTERNAL not in routes


def test_combination_internal_and_cross_doc():
    c = _claim(cross_refs=["表 1"], entities=["公司A"],
               numbers=[{"value": 1.2, "unit": "亿", "context": "营收"}])
    routes = route_claim(c, has_evidence=True)
    assert ROUTE_INTERNAL in routes
    assert ROUTE_CROSS_DOC in routes


def test_force_mode():
    c = _claim(claim_kind="OPINION")
    assert route_claim(c, has_evidence=False, force_mode="internal") == ["internal"]
