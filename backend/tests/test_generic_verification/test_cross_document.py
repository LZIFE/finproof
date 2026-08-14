"""backend/tests/test_generic_verification/test_cross_document.py"""
from app.services.generic_verification.schemas import GenericClaim
from app.services.generic_verification.verifiers.cross_document import verify_claim_cross_document
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)


def _claim(numbers, entities=("公司A",), text="营收 1.2 亿元"):
    return GenericClaim(
        claim_id="GCLM-001", source_text=text, claim_kind="NUMERIC", page_number=1,
        block_index=0, entities=list(entities), numbers=numbers, dates=[],
        cross_refs=[], extraction_method="rules", confidence=0.5,
    )


def test_supported_by_matching_evidence():
    claim = _claim([{"value": 1.2, "unit": "亿", "context": "营业收入"}])
    blocks = [
        {"text": "公司A 2024年营业收入 1.2 亿元", "page_number": 3, "document_id": 9},
    ]
    out = verify_claim_cross_document(claim, blocks)
    assert out.verdict == STATUS_SUPPORTED
    assert out.mode_used == ["cross_doc"]
    assert out.evidence


def test_refuted_by_conflicting_evidence():
    claim = _claim([{"value": 1.2, "unit": "亿", "context": "营业收入"}])
    blocks = [
        {"text": "公司A 2024年营业收入 1.2 万元", "page_number": 3, "document_id": 9},
    ]
    out = verify_claim_cross_document(claim, blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "CROSS_DOC_CONFLICT"


def test_insufficient_when_no_evidence():
    claim = _claim([{"value": 1.2, "unit": "亿", "context": "营业收入"}])
    out = verify_claim_cross_document(claim, [])
    assert out.verdict == STATUS_INSUFFICIENT


def test_supported_even_with_unrelated_growth_percentage():
    """证据块含匹配值 + 无关增长率百分比 → SUPPORTED 而非 REFUTED（P2 回归）。"""
    claim = _claim([{"value": 1.2, "unit": "亿", "context": "营业收入"}])
    blocks = [
        {"text": "公司A 2024年营业收入 1.2 亿元，同比增长 30%", "page_number": 3, "document_id": 9},
    ]
    out = verify_claim_cross_document(claim, blocks)
    assert out.verdict == STATUS_SUPPORTED
    assert out.error_type is None
