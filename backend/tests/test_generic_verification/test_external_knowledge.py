"""backend/tests/test_generic_verification/test_external_knowledge.py"""
from app.services.generic_verification.schemas import GenericClaim
from app.services.generic_verification.verifiers.external_knowledge import verify_claim_external
from app.services.verification.base import (
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)


def _claim(text="北京是中国首都", kind="FACT", entities=("北京", "中国"), numbers=()):
    return GenericClaim(
        claim_id="GCLM-001", source_text=text, claim_kind=kind, page_number=1,
        block_index=0, entities=list(entities), numbers=list(numbers), dates=[],
        cross_refs=[], extraction_method="rules", confidence=0.5,
    )


def _llm_supported(messages):
    return '{"verdict": "SUPPORTED", "reason": "常识确认"}'


def _llm_refuted(messages):
    return '{"verdict": "REFUTED", "reason": "常识否认"}'


def test_user_materials_support():
    out = verify_claim_external(_claim(), user_materials=["北京是中华人民共和国的首都。"])
    assert out.verdict == STATUS_SUPPORTED
    assert out.mode_used == ["external"]


def test_llm_support_when_no_materials():
    out = verify_claim_external(_claim(), llm_caller=_llm_supported)
    assert out.verdict == STATUS_SUPPORTED


def test_llm_refute_when_no_materials():
    out = verify_claim_external(_claim(), llm_caller=_llm_refuted)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "EXTERNAL_CONFLICT"


def test_unable_when_nothing_available():
    out = verify_claim_external(_claim())
    assert out.verdict == STATUS_UNABLE


def test_user_materials_with_unrelated_percentage_not_conflict():
    """支持性资料含匹配值 + 无关百分比 → SUPPORTED 而非 REFUTED（P2 回归）。"""
    claim = _claim(
        text="公司A 营收 1.2 亿元，同比增长 30%",
        entities=("公司A",),
        numbers=[{"value": 1.2, "unit": "亿", "context": "营业收入"},
                 {"value": 30, "unit": "%", "context": "同比增长"}],
    )
    out = verify_claim_external(claim, user_materials=["公司A 2024年营业收入 1.2 亿元，同比增长 30%"])
    assert out.verdict == STATUS_SUPPORTED
    assert out.error_type is None
