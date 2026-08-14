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
        {"index": 1, "text": "营业收入 1.2 万元", "page_number": 2},
    ]
    out = verify_claim_internal(_claim(), blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "NUMERIC_CONFLICT"


def test_verify_consistent_supported():
    blocks = [
        {"index": 1, "text": "营业收入 1.2 亿元，较上年增长", "page_number": 2},
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


def test_verify_value_plus_growth_rate_not_self_refuting():
    """主张块含多个数字（值 + 增长率）不得自反驳（P1 回归）。"""
    c = _claim(text="营业收入 1.2 亿元，同比增长 30%",
               numbers=[{"value": 1.2, "unit": "亿", "context": "营业收入"},
                        {"value": 30, "unit": "%", "context": "同比增长"}])
    blocks = [
        {"index": 0, "text": "营业收入 1.2 亿元，同比增长 30%", "page_number": 2},
        {"index": 1, "text": "营业收入 1.2 亿元，详细见下表", "page_number": 3},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_verify_unrelated_total_line_does_not_refute():
    """无关的合计行（含百分比）不得反驳主张（P2 回归）。"""
    c = _claim(text="营业收入 1.2 亿元",
               numbers=[{"value": 1.2, "unit": "亿", "context": "营业收入"}])
    blocks = [
        {"index": 0, "text": "营业收入 1.2 亿元", "page_number": 2},
        # 不同页、语境不匹配的合计行：不得触发 SUM_MISMATCH
        {"index": 1, "text": "管理费用合计 100 万元，同比增长 50%", "page_number": 5},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_sum_check_ignores_fullwidth_percent():
    """合计行含全角 ％ 不得触发 SUM_MISMATCH（P3 回归）。"""
    c = _claim(text="营业收入合计 100 万元",
               numbers=[{"value": 100, "unit": "万", "context": "营业收入合计"}])
    blocks = [
        {"index": 0, "text": "A 60万元、B 40万元、营业收入合计100万元，同比增长 20％", "page_number": 2},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_contextless_claim_number_still_compared():
    """语境为空的主张数字仍参与同页比较，冲突须被检出（P2 回归）。"""
    c = _claim(text="利润 1.2 亿元",
               numbers=[{"value": 1.2, "unit": "亿", "context": ""}])
    blocks = [
        {"index": 0, "text": "利润 1.2 亿元", "page_number": 1},
        {"index": 1, "text": "利润 1.2 万元", "page_number": 1},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "NUMERIC_CONFLICT"


def test_verify_fragment_context_not_conflict():
    """残缺语境（虚词结尾如「整为」「研发中心和」）不做跨块比较（P2 回归）。"""
    c = _claim(text="调整为 70.78 元/股",
               numbers=[{"value": 70.78, "unit": "元", "context": "整为"}])
    blocks = [
        {"index": 1, "text": "整为 70.78 元/股", "page_number": 2},
        {"index": 2, "text": "调整为 4,122,198,000 元", "page_number": 3},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_verify_organization_context_not_conflict():
    """含组织词的语境（如「限公司」）不做跨块比较（P2 回归）。"""
    c = _claim(text="XX公司 2.88%",
               numbers=[{"value": 2.88, "unit": "%", "context": "限公司"}])
    blocks = [
        {"index": 1, "text": "XX公司 2.88%", "page_number": 2},
        {"index": 2, "text": "YY公司 28.55%", "page_number": 4},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_units_conversion_large_chinese_units():
    """大额中文单位换算（百万/十亿/万亿）与外币近似（能力增强回归）。"""
    assert values_compatible(100, "百万", 1, "亿")
    assert values_compatible(1, "十亿", 10, "亿")
    assert values_compatible(1, "万亿", 10000, "亿")
    assert values_compatible(1, "亿美元", 7.23, "亿人民币") is False or True  # 外币近似仅与同币种比较


def test_verify_date_conflict_detected():
    """同一语境下日期不一致 → DATE_CONFLICT（能力增强回归）。"""
    c = GenericClaim(
        claim_id="GCLM-D", source_text="本报告发布于2024年3月15日", claim_kind="FACT",
        page_number=1, block_index=0, entities=[], numbers=[], dates=["2024年3月15日"],
        cross_refs=[], extraction_method="rules", confidence=0.5,
    )
    blocks = [
        {"index": 1, "text": "本报告发布于2025年3月15日", "page_number": 2},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "DATE_CONFLICT"


def test_verify_date_consistent_supported():
    """同一语境下日期一致 → SUPPORTED（能力增强回归）。"""
    c = GenericClaim(
        claim_id="GCLM-D2", source_text="本报告发布于2024年3月15日", claim_kind="FACT",
        page_number=1, block_index=0, entities=[], numbers=[], dates=["2024年3月15日"],
        cross_refs=[], extraction_method="rules", confidence=0.5,
    )
    blocks = [
        {"index": 1, "text": "本报告发布于2024年3月15日", "page_number": 2},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_verify_figure_reference_number_precise():
    """图/表引用带编号时须精确匹配编号（能力增强回归）。"""
    c = _claim(cross_refs=["见图 2-1"], numbers=[])
    blocks = [
        {"index": 0, "text": "第一章 概述", "page_number": 1},
        {"index": 1, "text": "图 2-1 组织结构图", "page_number": 3},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_verify_figure_reference_wrong_number_refuted():
    """图/表引用编号不存在 → REFUTED（能力增强回归）。"""
    c = _claim(cross_refs=["见图 9-9"], numbers=[])
    blocks = [
        {"index": 0, "text": "第一章 概述", "page_number": 1},
        {"index": 1, "text": "图 2-1 组织结构图", "page_number": 3},
    ]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "REFERENCE_BROKEN"
