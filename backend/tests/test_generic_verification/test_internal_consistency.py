"""backend/tests/test_generic_verification/test_internal_consistency.py"""
from app.services.generic_verification.schemas import GenericClaim
from app.services.generic_verification.verifiers.internal_consistency import (
    VALUE_TOLERANCE,
    numbers_equal,
    values_compatible,
    verify_claim_internal,
)
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)


def _claim(text="营收 1.2 亿元", kind="NUMERIC", cross_refs=None, numbers=None):
    return GenericClaim(
        claim_id="GCLM-001", source_text=text, claim_kind=kind, page_number=1,
        block_index=0, entities=["公司A"],
        numbers=numbers if numbers is not None else [{"value": 1.2, "unit": "亿", "context": "营收"}],
        dates=[], cross_refs=cross_refs or [], extraction_method="rules", confidence=0.5,
    )


def test_numbers_equal():
    assert numbers_equal(1.2, 1.2)
    assert numbers_equal(100, 100.5, tol=0.01)  # 0.5% 相对误差在 1% 内
    assert not numbers_equal(100, 110, tol=0.01)


def test_values_compatible_unit_conversion():
    assert values_compatible(1.2, "亿", 12000, "万")
    assert values_compatible(30, "%", 30, "%")
    assert not values_compatible(1.2, "亿", 1.2, "万")


def test_verify_conflict_detected():
    blocks = [
        {"index": 0, "text": "营业收入 1.2 万元", "page_number": 2},
    ]
    out = verify_claim_internal(_claim(), blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "NUMERIC_CONFLICT"


def test_verify_consistent_supported():
    blocks = [
        {"index": 0, "text": "营业收入 1.2 亿元，较上年增长", "page_number": 2},
    ]
    out = verify_claim_internal(_claim(), blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_verify_broken_reference():
    c = _claim(cross_refs=["第 9 章"], numbers=[])
    blocks = [{"index": 0, "text": "第一章 概述", "page_number": 1}]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "REFERENCE_BROKEN"


def test_verify_no_evidence_insufficient():
    c = _claim(numbers=[], cross_refs=[])
    blocks = [{"index": 0, "text": "无关段落", "page_number": 1}]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_INSUFFICIENT
