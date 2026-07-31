"""Phase 4B.1 核验引擎专项测试：数值/增长率/期间/证据/安全。"""

from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)
from app.services.verification.evidence_checker import verify_multi_evidence, verify_semantic
from app.services.verification.growth_verifier import verify_growth_rate
from app.services.verification.numeric_verifier import verify_exact_value
from app.services.verification.period_verifier import verify_period_quarter


# ---------- 数值 ----------

def test_numeric_unit_conversions():
    """亿元/千元/元/万元统一换算核验。"""
    for evidence, value, unit in [
        ("营业收入（千元） 456,451,731 407,149,600", 4564.52, "亿元"),
        ("营业收入 252,331万元", 25.2331, "亿元"),
        ("营业收入 252331000000元", 2523.31, "亿元"),
    ]:
        r = verify_exact_value({"claim_id": "C", "value": value, "unit": unit}, [evidence])
        assert r.verification_status == STATUS_SUPPORTED, (evidence, r.to_dict())
        assert r.calculation_detail  # calculation_detail 必须保存


def test_numeric_negative_and_thousand_separator():
    """负数（括号）与千分位解析。"""
    r = verify_exact_value({"claim_id": "C", "value": 4564.52, "unit": "亿元"},
                           ["营业收入（千元） 456,451,731 407,149,600"])
    assert r.verification_status == STATUS_SUPPORTED
    r2 = verify_exact_value({"claim_id": "C2", "value": 10.8, "unit": "亿元"},
                            ["公允价值变动损失 (1,081,776) 千元"])
    assert r2.verification_status == STATUS_SUPPORTED


def test_numeric_wrong_value_refuted():
    r = verify_exact_value({"claim_id": "C", "value": 4564.52, "unit": "亿元"},
                           ["营业收入（千元） 405,285,097 402,713,468"])
    assert r.verification_status == STATUS_REFUTED


# ---------- 增长率 ----------

def test_growth_correct():
    r = verify_growth_rate({"claim_id": "C", "claim_type": "GROWTH_RATE", "value": 12.11, "unit": "PERCENT"},
                           ["营业收入（千元） 456,451,731 407,149,600"])
    assert r.verification_status == STATUS_SUPPORTED


def test_growth_wrong():
    r = verify_growth_rate({"claim_id": "C", "claim_type": "GROWTH_RATE", "value": 38.02, "unit": "PERCENT"},
                           ["营业收入（千元） 456,451,731 407,149,600"])
    assert r.verification_status == STATUS_REFUTED


def test_growth_rounding_tolerance():
    """四舍五入误差在 ±0.5pp 内 → SUPPORTED。"""
    r = verify_growth_rate({"claim_id": "C", "claim_type": "GROWTH_RATE", "value": 15.07, "unit": "PERCENT"},
                           ["营业收入 2523.31亿元 2193亿元"])
    assert r.verification_status == STATUS_SUPPORTED


# ---------- 期间 ----------

def test_period_q1_h1_fy_quarter():
    """Q2 = H1 − Q1 单季推算。"""
    r = verify_period_quarter({"claim_id": "C", "period": "2025Q2", "value": 1244.92, "unit": "亿元"},
                              ["2025年上半年营业总收入2523.31亿元", "2025年第一季度营业收入1278.39亿元"])
    assert r.verification_status == STATUS_SUPPORTED
    assert r.calculation_detail["formula"] == "Q2 = H1 − Q1"


def test_period_q2_wrong():
    r = verify_period_quarter({"claim_id": "C", "period": "2025Q2", "value": 1500.0, "unit": "亿元"},
                              ["2025年上半年营业总收入2523.31亿元", "2025年第一季度营业收入1278.39亿元"])
    assert r.verification_status == STATUS_REFUTED


# ---------- 证据 ----------

def test_evidence_single_and_missing():
    """单证据充足 → SUPPORTED；缺证据 → INSUFFICIENT。"""
    r = verify_exact_value({"claim_id": "C", "value": 100.0, "unit": "亿元"}, ["营业收入 100亿元"])
    assert r.verification_status == STATUS_SUPPORTED
    r2 = verify_exact_value({"claim_id": "C2", "value": 100.0, "unit": "亿元"}, ["公司经营稳健"])
    assert r2.verification_status == STATUS_INSUFFICIENT


def test_evidence_conflict_refuted():
    """冲突证据（数值不符）→ REFUTED。"""
    r = verify_exact_value({"claim_id": "C", "value": 100.0, "unit": "亿元"}, ["营业收入 90亿元 80亿元"])
    assert r.verification_status == STATUS_REFUTED


def test_multi_evidence_dimensions():
    """多证据组合：三维（数值+同比+业务）覆盖判定。"""
    meta = [{"value_score": 1}, {"value_score": 0}, {"value_score": 0}]
    r = verify_multi_evidence(
        {"claim_id": "C", "original_text": "海外业务成为主要增长动力"},
        ["海外收入 300亿元 同比增长30%", "海外业务成为公司利润增长的核心引擎", "全球化布局"],
        [1, 2, 3], meta,
    )
    assert r.verification_status in (STATUS_SUPPORTED, STATUS_PARTIALLY_SUPPORTED)


def test_semantic_insufficient():
    """语义主张只有收入数字、无业务描述 → INSUFFICIENT_EVIDENCE（不强制判断）。"""
    r = verify_semantic({"claim_id": "C", "original_text": "海外业务成为主要增长动力"}, ["海外收入 300亿元"])
    assert r.verification_status == STATUS_INSUFFICIENT


# ---------- 安全 ----------

def test_security_no_gold_verifications(tmp_path):
    """核验引擎不读取 gold_verifications（源码检查 + 行为验证：篡改答案不影响核验结果）。"""
    import inspect
    import re
    from pathlib import Path

    from app.services import verification as vpkg

    # 剔除文档字符串与注释后检查实际代码（文档中的说明性提及不算）
    src = "".join(
        p.read_text(encoding="utf-8")
        for p in Path(vpkg.__file__).parent.rglob("*.py")
    )
    src_code = re.sub(r'("""|\'\'\')(.*?)\1', "", src, flags=re.S)
    src_code = "\n".join(l for l in src_code.splitlines() if not l.lstrip().startswith("#"))
    assert "gold_verifications" not in src_code
    # 行为验证：篡改 gold_verifications 内容不影响直接核验输出
    gold_path = Path(__file__).resolve().parents[2] / "data" / "demo" / "annotations" / "gold_verifications.json"
    original = gold_path.read_text(encoding="utf-8")
    before = verify_exact_value({"claim_id": "C", "value": 4564.52, "unit": "亿元"},
                                ["营业收入（千元） 456,451,731 407,149,600"]).verification_status
    gold_path.write_text('{"verifications": [{"claim_id": "FAKE", "expected_verdict": "REFUTED"}]}', encoding="utf-8")
    try:
        after = verify_exact_value({"claim_id": "C", "value": 4564.52, "unit": "亿元"},
                                   ["营业收入（千元） 456,451,731 407,149,600"]).verification_status
        assert before == after == STATUS_SUPPORTED
    finally:
        gold_path.write_text(original, encoding="utf-8")


# ---------- Phase 4B.2：语义核验与证据充分性 ----------

def test_semantic_overseas_growth_supported():
    """海外收入增长（BUSINESS_FACT）：证据含数值+增长 → SUPPORTED。"""
    from app.services.verification.semantic_verifier import verify_semantic_support

    r = verify_semantic_support(
        {"claim_id": "S1", "claim_type": "BUSINESS_FACT", "original_text": "海外市场收入增长"},
        ["海外市场收入300亿元，同比增长30%"],
    )
    assert r.verification_status == STATUS_SUPPORTED
    assert r.verification_type == "SEMANTIC_SUPPORT_CHECK"


def test_semantic_core_growth_insufficient():
    """海外成为核心增长动力（STRATEGIC_CLAIM）：只有海外增长（缺整体比较）→ PARTIALLY。"""
    from app.services.verification.semantic_verifier import verify_semantic_support

    r = verify_semantic_support(
        {"claim_id": "S2", "claim_type": "OPINION", "original_text": "海外业务成为公司增长核心动力"},
        ["海外市场收入300亿元，同比增长30%"],
    )
    assert r.verification_status == STATUS_PARTIALLY_SUPPORTED
    assert r.calculation_detail["covered"] == 2 and r.calculation_detail["required"] == 3


def test_semantic_causal_insufficient():
    """由于业务调整导致利润提升（CAUSAL）：仅相关性（财务结果）无原因披露 → INSUFFICIENT。"""
    from app.services.verification.semantic_verifier import verify_causal

    r = verify_causal(
        {"claim_id": "S3", "claim_type": "CAUSAL_CLAIM", "original_text": "由于业务调整，公司利润提升"},
        ["公司利润100亿元，同比增长20%"],
    )
    assert r.verification_status == STATUS_INSUFFICIENT
    r2 = verify_causal(
        {"claim_id": "S3", "claim_type": "CAUSAL_CLAIM", "original_text": "由于业务调整，公司利润提升"},
        ["公司利润100亿元，同比增长20%", "利润提升主要系业务调整所致"],
    )
    assert r2.verification_status == STATUS_PARTIALLY_SUPPORTED


def test_semantic_comparative_no_peer_insufficient():
    """行业领先（COMPARATIVE）：无比较数据 → INSUFFICIENT；含行业排名 → PARTIALLY。"""
    from app.services.verification.semantic_verifier import verify_comparison

    r = verify_comparison(
        {"claim_id": "S4", "claim_type": "COMPARISON", "original_text": "公司竞争优势领先行业"},
        ["公司产品销量100万台"],
    )
    assert r.verification_status == STATUS_INSUFFICIENT
    r2 = verify_comparison(
        {"claim_id": "S4", "claim_type": "COMPARISON", "original_text": "公司竞争优势领先行业"},
        ["公司市场份额位居行业第一，市占率25%"],
    )
    assert r2.verification_status == STATUS_PARTIALLY_SUPPORTED


def test_semantic_partial_support_full_coverage():
    """完整覆盖 3/3（数值+增长+占比）→ SUPPORTED（部分支持 vs 完整支持区分）。"""
    from app.services.verification.semantic_verifier import verify_semantic_support

    r = verify_semantic_support(
        {"claim_id": "S5", "claim_type": "OPINION", "original_text": "海外业务成为公司增长核心动力"},
        ["海外收入300亿元同比增长30%", "海外收入占公司总收入40%"],
    )
    assert r.verification_status == STATUS_SUPPORTED
    assert r.calculation_detail["covered"] == 3


def test_semantic_no_numeric_evidence_insufficient():
    """语义主张无数字证据 → INSUFFICIENT。"""
    from app.services.verification.semantic_verifier import verify_semantic_support

    r = verify_semantic_support(
        {"claim_id": "S6", "claim_type": "BUSINESS_FACT", "original_text": "海外市场收入增长"},
        ["公司经营稳健"],
    )
    assert r.verification_status == STATUS_INSUFFICIENT


def test_semantic_unknown_kept():
    """UNKNOWN/无法判定结果保持（不删除）：无数值且无证据 → INSUFFICIENT 保留。"""
    from app.services.verification.numeric_verifier import verify_exact_value

    r = verify_exact_value({"claim_id": "S7", "value": None}, ["公司经营稳健"])
    assert r.verification_status == "UNABLE_TO_DETERMINE"  # 主张无数值 → 保持 UNABLE
    r2 = verify_semantic_support_scenario_no_evidence()
    assert r2.verification_status == STATUS_INSUFFICIENT


def verify_semantic_support_scenario_no_evidence():
    from app.services.verification.semantic_verifier import verify_semantic_support

    return verify_semantic_support(
        {"claim_id": "S7", "claim_type": "BUSINESS_FACT", "original_text": "海外市场收入增长"},
        [],
    )
