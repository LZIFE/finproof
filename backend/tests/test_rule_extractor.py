"""规则候选提取器单元测试：复合主张拆分 / 指标继承 / 不过度拆分 / 过滤。"""

from types import SimpleNamespace

from app.services.claims.rule_extractor import RuleBasedCandidateExtractor


def _block(text: str, block_id: int = 1, block_type: str = "paragraph") -> SimpleNamespace:
    return SimpleNamespace(
        id=block_id, block_type=block_type, text=text,
        page_number=1, heading_level=None,
    )


def _extract(text: str, report_year: int = 2025, block_type: str = "paragraph"):
    extractor = RuleBasedCandidateExtractor(
        entity_name="美的集团", stock_code="000333", report_year=report_year
    )
    return extractor.extract([_block(text, block_type=block_type)])


def test_compound_sentence_split():
    """复合句拆分为多条主张（增长 + 占比 + 因果）。"""
    text = "美的集团2025年上半年收入同比增长15%，并且海外收入占比超过50%，主要由智能家居业务推动。"
    result = _extract(text)
    types = [c.claim_type for c in result.candidates]
    assert "GROWTH_RATE" in types
    assert "BUSINESS_SHARE" in types
    assert "CAUSAL_CLAIM" in types
    assert len(result.candidates) >= 3


def test_metric_inheritance():
    """增长率子句继承前一子句指标。"""
    text = "公司2025年实现营业收入4564.52亿元，同比增长12.11%。"
    result = _extract(text)
    codes = {c.metric_code for c in result.candidates}
    assert "revenue" in codes
    assert "yoy_growth_revenue" in codes
    growth = next(c for c in result.candidates if c.metric_code == "yoy_growth_revenue")
    assert growth.reported_value == 12.11
    assert growth.period == "2025"
    assert growth.comparison_type == "YEAR_OVER_YEAR"


def test_no_over_split_single_fact():
    """简单数值句只产生一条主张（不拆成"公司有收入/时间是2025/收入是X"）。"""
    text = "公司2025年上半年收入为2523.31亿元。"
    result = _extract(text)
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.reported_value == 2523.31
    assert c.period == "2025H1"


def test_heading_blocks_skipped():
    result = _extract("美的集团（000333.SZ）2025年年报点评", block_type="heading")
    assert len(result.candidates) == 0


def test_meta_lines_skipped():
    meta = "> 公司评级：买入 ｜ 报告日期：2026-04-15 ｜ 分析师：FinProof 研究团队"
    assert len(_extract(meta).candidates) == 0
    assert len(_extract("---").candidates) == 0
    assert len(_extract("本报告由AI辅助生成，仅供演示用途，不构成投资建议。").candidates) == 0


def test_transition_sentence_skipped():
    text = "一季度实现开门红，整体来看公司基本面扎实。"
    assert len(_extract(text).candidates) == 0


def test_forecast_classification():
    text = "展望2026年，公司营业收入将突破5000亿元。"
    result = _extract(text)
    forecast = [c for c in result.candidates if c.claim_type == "FORECAST"]
    assert len(forecast) == 1
    assert forecast[0].reported_value == 5000
    assert forecast[0].period == "2026FY"


def test_year_inheritance_from_sentence():
    text = "上半年扣非归母净利润262亿元，同比增长30.0%。"
    result = _extract(text)
    assert any(c.metric_code == "deducted_net_profit" and c.period == "2025H1" for c in result.candidates)


def test_period_context_propagation():
    text = "2025年上半年，公司营业总收入2523.31亿元，同比增长15.7%。"
    result = _extract(text)
    rev = next(c for c in result.candidates if c.metric_code == "total_operating_revenue")
    assert rev.period == "2025H1"


def test_different_metrics_same_value_not_deduped():
    """不同指标相同数值不应被去重。"""
    from app.services.claims.dedup import deduplicate

    text = "2025年收入为100亿元，净利润为100亿元。"
    result = _extract(text)
    deduped = deduplicate(result.candidates)
    codes = {c.metric_code for c in deduped.unique}
    assert "revenue" in codes and "net_profit" in codes
