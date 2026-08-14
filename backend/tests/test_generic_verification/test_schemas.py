"""backend/tests/test_generic_verification/test_schemas.py"""
import pytest
from pydantic import ValidationError

from app.services.generic_verification.schemas import (
    ErrorItem,
    GenericClaim,
    GenericClaimCreate,
    VerificationOutcome,
)
from app.services.verification.base import STATUS_REFUTED, STATUS_SUPPORTED


def test_generic_claim_to_dict():
    c = GenericClaim(
        claim_id="GCLM-001",
        source_text="营收 1.2 亿元，同比增长 30%",
        claim_kind="NUMERIC",
        page_number=5,
        block_index=3,
        entities=["公司A"],
        numbers=[{"value": 1.2, "unit": "亿", "context": "营收"}],
        dates=[],
        cross_refs=[],
        extraction_method="rules",
        confidence=0.8,
    )
    d = c.to_dict()
    assert d["claim_id"] == "GCLM-001"
    assert d["numbers"][0]["value"] == 1.2


def test_generic_claim_create_valid():
    g = GenericClaimCreate(
        claim_id="GCLM-001",
        source_text="x",
        claim_kind="FACT",
        page_number=1,
        block_index=0,
        entities=[],
        numbers=[],
        dates=[],
        cross_refs=[],
        extraction_method="rules",
        confidence=0.5,
    )
    assert g.claim_kind == "FACT"


def test_generic_claim_create_rejects_bad_kind():
    with pytest.raises(ValidationError):
        GenericClaimCreate(
            claim_id="GCLM-002", source_text="x", claim_kind="BOGUS",
            page_number=1, block_index=0, entities=[], numbers=[],
            dates=[], cross_refs=[], extraction_method="rules", confidence=0.5,
        )


def test_verification_outcome_to_dict():
    o = VerificationOutcome(
        claim_id="GCLM-001", verdict=STATUS_REFUTED, confidence=0.9,
        mode_used=["internal"], evidence=[{"text": "1.2 万", "page_number": 5}],
        reason="数字不一致", error_type="NUMERIC_CONFLICT",
    )
    d = o.to_dict()
    assert d["verdict"] == STATUS_REFUTED
    assert d["error_type"] == "NUMERIC_CONFLICT"


def test_error_item_to_dict():
    e = ErrorItem(page_number=5, source_text="营收 1.2 亿", verdict=STATUS_SUPPORTED,
                  error_type="NUMERIC_CONFLICT", detail="1.2 亿 vs 1.2 万")
    assert e.to_dict()["page_number"] == 5
