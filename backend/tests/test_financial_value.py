"""Phase 23.8 重构金融数值解析单元测试。

覆盖：
- 1,234.56 与 1234.56（千分位，中英文逗号）
- 亿元/万元/千元/元/百万/十亿/million/billion
- 百分比 / 百分点 / basis points
- 正负号 / 括号负数 (1,081,776)
- 同比增长/下降/亏损扩大/收窄
- 多数字同时出现在 Evidence 中（metric+period+unit+scope 绑定）
- 表格行名/列名与数字的就近绑定
- 不简单选 Evidence 中第一个数字
"""

from __future__ import annotations

import pytest

from app.services.verification.financial_value import (
    FinancialValue,
    UNIT_SCALE,
    extract_financial_values,
    find_best_match,
    values_match,
)


# ---------------------------------------------------------------------------
# 千分位解析
# ---------------------------------------------------------------------------
class TestThousandSeparator:
    def test_english_comma(self):
        fvs = extract_financial_values("1,234.56 亿元")
        assert len(fvs) == 1
        assert fvs[0].normalized_value == 1234.56
        assert fvs[0].unit == "亿元"
        assert fvs[0].scale == 1e8

    def test_no_comma(self):
        fvs = extract_financial_values("1234.56 亿元")
        assert len(fvs) == 1
        assert fvs[0].normalized_value == 1234.56

    def test_multi_comma(self):
        fvs = extract_financial_values("1,234,567 万元")
        assert len(fvs) == 1
        assert fvs[0].normalized_value == 1234567.0

    def test_fullwidth_comma(self):
        # 全角逗号､（U+FF64）
        fvs = extract_financial_values("1､234､567 万元")
        assert len(fvs) == 1
        assert fvs[0].normalized_value == 1234567.0


# ---------------------------------------------------------------------------
# 单位换算
# ---------------------------------------------------------------------------
class TestUnitConversion:
    @pytest.mark.parametrize("unit,expected_scale", [
        ("亿元", 1e8), ("万元", 1e4), ("千元", 1e3), ("元", 1.0),
        ("百万", 1e6), ("十亿", 1e9), ("百亿", 1e10),
        ("million", 1e6), ("billion", 1e9),
    ])
    def test_scale(self, unit, expected_scale):
        assert UNIT_SCALE[unit] == expected_scale

    def test_yi_to_yuan(self):
        fv = extract_financial_values("4564.52 亿元")[0]
        assert fv.absolute_value_in_yuan == pytest.approx(4564.52e8)

    def test_qianyuan_to_yi(self):
        # Evidence 用千元，claim 用亿元：换算后应匹配
        # 456,451,731 千元 = 456451731000 元 = 4564.52 亿元
        fv = extract_financial_values("456,451,731 千元")[0]
        assert fv.absolute_value_in_yuan == pytest.approx(456451731000.0)

    def test_cross_unit_match(self):
        # claim=4564.52 亿元，evidence=456,451,731 千元 → 换算后应匹配
        ev_fv = extract_financial_values("456,451,731 千元")[0]
        matched, reason = values_match(4564.52, "亿元", ev_fv, tolerance=0.005)
        assert matched, f"cross-unit match failed: {reason}"

    def test_currency_detection(self):
        fv_cn = extract_financial_values("100 亿元")[0]
        assert fv_cn.currency == "CNY"
        fv_us = extract_financial_values("100 million")[0]
        assert fv_us.currency == "USD"


# ---------------------------------------------------------------------------
# 百分比 / 百分点 / basis points
# ---------------------------------------------------------------------------
class TestPercentage:
    def test_percentage(self):
        fvs = extract_financial_values("12.11%")
        assert len(fvs) == 1
        assert fvs[0].percentage_type == "percentage"
        assert fvs[0].normalized_value == 12.11

    def test_percentage_point(self):
        fvs = extract_financial_values("上升 3.5 个百分点")
        # "3.5 个百分点" 中的数值应被抽取
        assert any(fv.percentage_type == "percentage_point" for fv in fvs)

    def test_basis_points(self):
        fvs = extract_financial_values("下调 25 basis points")
        assert any(fv.percentage_type == "basis_point" for fv in fvs)

    def test_bp_abbreviation(self):
        fvs = extract_financial_values("上调 50bp")
        assert any(fv.percentage_type == "basis_point" for fv in fvs)

    def test_percent_vs_pp_not_confused(self):
        # 12.11% 是百分比，不是百分点
        fv = extract_financial_values("12.11%")[0]
        assert fv.percentage_type == "percentage"
        assert fv.percentage_type != "percentage_point"


# ---------------------------------------------------------------------------
# 正负号 / 括号负数
# ---------------------------------------------------------------------------
class TestSign:
    def test_paren_negative(self):
        fvs = extract_financial_values("(1,081,776) 千元")
        assert len(fvs) == 1
        assert fvs[0].sign == "negative_paren"
        assert fvs[0].absolute_value_in_yuan < 0
        assert fvs[0].absolute_value_in_yuan == pytest.approx(-1081776000.0)

    def test_minus_sign(self):
        fvs = extract_financial_values("-54.55%")
        assert len(fvs) == 1
        assert fvs[0].sign == "negative_sign"
        assert fvs[0].normalized_value == 54.55
        assert fvs[0].percentage_type == "percentage"

    def test_yoy_decline(self):
        fvs = extract_financial_values("同比下降 54.55%")
        # 找到 54.55%，sign 应为 yoy_decline
        pct_fv = [fv for fv in fvs if fv.percentage_type == "percentage"][0]
        assert pct_fv.sign == "yoy_decline"

    def test_yoy_growth(self):
        fvs = extract_financial_values("同比增长 12.11%")
        pct_fv = [fv for fv in fvs if fv.percentage_type == "percentage"][0]
        assert pct_fv.sign == "positive"

    def test_loss_expanding(self):
        fvs = extract_financial_values("亏损扩大 15.7%")
        pct_fv = [fv for fv in fvs if fv.percentage_type == "percentage"][0]
        assert pct_fv.sign == "yoy_decline"


# ---------------------------------------------------------------------------
# 多数字歧义 + metric/period 绑定
# ---------------------------------------------------------------------------
class TestMultipleNumbers:
    def test_multiple_values_extracted(self):
        # Evidence 含多个数字：本期 + 上期 + 同比
        fvs = extract_financial_values("456,451,731 407,149,600 12.11%")
        assert len(fvs) >= 3

    def test_metric_binding(self):
        # 上下文 metric 绑定
        fvs = extract_financial_values(
            "456,451,731 千元",
            context_metric="revenue",
            context_period="2025FY",
        )
        assert fvs[0].metric == "revenue"
        assert fvs[0].period == "2025FY"

    def test_best_match_not_first(self):
        # claim=4564.52 亿元 revenue 2025FY
        # evidence 含多个数字，应选匹配 metric/period 的，不是第一个
        ev_fvs = extract_financial_values(
            "营业收入 456,451,731 千元 同比 12.11% 上期 407,149,600 千元",
            context_metric="revenue",
            context_period="2025FY",
        )
        # 至少抽取 3 个数字
        assert len(ev_fvs) >= 3
        # find_best_match 应选 456,451,731 千元（匹配 4564.52 亿元）
        best, reason = find_best_match(
            4564.52, "亿元", "revenue", "2025FY", ev_fvs, tolerance=0.005,
        )
        assert best is not None
        assert best.absolute_value_in_yuan == pytest.approx(4564.52e8, rel=0.005)

    def test_wrong_unit_not_matched(self):
        # claim=4564.52 亿元，evidence=407,149,600 千元（不匹配，是上期值）
        ev_fv = extract_financial_values("407,149,600 千元")[0]
        matched, reason = values_match(4564.52, "亿元", ev_fv, tolerance=0.005)
        assert not matched, f"wrong value should not match: {reason}"


# ---------------------------------------------------------------------------
# 表格行名/列名就近绑定
# ---------------------------------------------------------------------------
class TestTableContextBinding:
    def test_row_name_near_value(self):
        # "营业收入（千元） 456,451,731" 行名紧邻数值
        fvs = extract_financial_values("营业收入（千元） 456,451,731", context_metric="revenue")
        assert len(fvs) == 1
        assert fvs[0].normalized_value == 456451731.0
        # context_metric 应绑定
        assert fvs[0].metric == "revenue"

    def test_column_header_unit(self):
        # 列标题含单位，数值无单位时用 context_unit 回退
        fvs = extract_financial_values("456,451,731", context_unit="千元")
        assert len(fvs) == 1
        assert fvs[0].unit == "千元"
        assert fvs[0].scale == 1e3


# ---------------------------------------------------------------------------
# source_span 与 extraction_confidence
# ---------------------------------------------------------------------------
class TestSpanAndConfidence:
    def test_source_span(self):
        fvs = extract_financial_values("前缀 123.45 亿元 后缀")
        assert len(fvs) == 1
        span = fvs[0].source_span
        assert span[0] < span[1]
        assert span[1] > 0

    def test_confidence_with_unit(self):
        fv_unit = extract_financial_values("100 亿元")[0]
        fv_no_unit = extract_financial_values("100")[0]
        assert fv_unit.extraction_confidence > fv_no_unit.extraction_confidence

    def test_confidence_paren_negative(self):
        fv = extract_financial_values("(1,081,776) 千元")[0]
        assert fv.extraction_confidence >= 0.9


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_text(self):
        assert extract_financial_values("") == []
        assert extract_financial_values(None) == []

    def test_no_numbers(self):
        assert extract_financial_values("纯文本无数字") == []

    def test_multiple_paren_negatives(self):
        fvs = extract_financial_values("(1,081,776) 千元 (2,000,000) 万元")
        assert len(fvs) == 2
        assert all(fv.sign == "negative_paren" for fv in fvs)

    def test_value_with_unit_and_percent(self):
        # 12.11% 无单位，仅百分比
        fvs = extract_financial_values("12.11%")
        assert len(fvs) == 1
        assert fvs[0].unit == ""
        assert fvs[0].percentage_type == "percentage"

    def test_negative_value_with_unit(self):
        fvs = extract_financial_values("-54.55%")
        assert fvs[0].sign == "negative_sign"
        assert fvs[0].percentage_type == "percentage"

    def test_normalize_fullwidth(self):
        # 全角数字归一化（NFKC）
        fvs = extract_financial_values("４５６４．５２ 亿元")
        # 全角数字应归一化为半角
        assert any(fv.normalized_value == 4564.52 for fv in fvs)
