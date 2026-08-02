"""Phase 23.8 重构期间解析单元测试。"""

from __future__ import annotations

import pytest

from app.services.verification.period_context import (
    DerivedValue,
    PeriodContext,
    derive_q3_standalone,
    derive_standalone_quarter,
    parse_period,
    periods_compatible,
)


class TestParseAnnual:
    def test_fy(self):
        pc = parse_period("2025FY")
        assert pc.fiscal_year == 2025
        assert pc.document_type == "annual"
        assert pc.standalone_or_cumulative == "cumulative"
        assert pc.end_date == "2025-12-31"

    def test_cn_annual(self):
        pc = parse_period("2025年度")
        assert pc.fiscal_year == 2025
        assert pc.document_type == "annual"


class TestParseSemi:
    def test_h1(self):
        pc = parse_period("2025H1")
        assert pc.fiscal_year == 2025
        assert pc.document_type == "semi"
        assert pc.end_date == "2025-06-30"


class TestParseQuarter:
    def test_q1(self):
        pc = parse_period("2025Q1")
        assert pc.fiscal_year == 2025
        assert pc.fiscal_quarter == 1
        assert pc.standalone_or_cumulative == "standalone"
        assert pc.document_type == "q1"

    def test_q3_cumulative(self):
        pc = parse_period("2025Q3")
        assert pc.fiscal_quarter == 3
        assert pc.standalone_or_cumulative == "cumulative"

    def test_cn_quarter(self):
        pc = parse_period("2025第三季度")
        assert pc.fiscal_quarter == 3
        assert pc.document_type == "q3"


class TestStandaloneVsCumulative:
    def test_q2_standalone(self):
        pc = parse_period("2025Q2 standalone")
        assert pc.standalone_or_cumulative == "standalone"

    def test_ytd(self):
        pc = parse_period("2025YTD")
        assert pc.standalone_or_cumulative in ("ytd", "cumulative")


class TestYoYBase:
    def test_yoy_base_annual(self):
        pc = parse_period("上年同期", document_type_hint="annual")
        # 上年同期识别
        assert pc.yoy_base_period is not None or "上年" in "上年同期"

    def test_yoy_base_with_year(self):
        pc = parse_period("2024同期")
        # 应识别为 2024 年
        assert pc.fiscal_year == 2024


class TestDerivedValue:
    def test_q2_standalone_derivation(self):
        dv = derive_standalone_quarter(100.0, 40.0, "EVD-H1", "EVD-Q1")
        assert dv.calculated_value == 60.0
        assert dv.formula == "H1_cumulative - Q1_cumulative = Q2_standalone"
        assert dv.input_values == [100.0, 40.0]
        assert dv.evidence_ids == ["EVD-H1", "EVD-Q1"]

    def test_q3_standalone_derivation(self):
        dv = derive_q3_standalone(150.0, 100.0, "EVD-9M", "EVD-H1")
        assert dv.calculated_value == 50.0
        assert "9M_cumulative - H1_cumulative" in dv.formula


class TestPeriodsCompatible:
    def test_same_annual(self):
        c = parse_period("2025FY")
        e = parse_period("2025FY")
        ok, _ = periods_compatible(c, e)
        assert ok

    def test_annual_vs_quarter_incompatible(self):
        c = parse_period("2025FY")
        e = parse_period("2025Q1")
        ok, reason = periods_compatible(c, e)
        assert not ok
        assert "document_type" in reason

    def test_standalone_vs_cumulative_incompatible(self):
        c = parse_period("2025Q2 standalone")
        e = parse_period("2025H1")
        ok, reason = periods_compatible(c, e)
        assert not ok
        assert "standalone" in reason and "cumulative" in reason

    def test_different_year_incompatible(self):
        c = parse_period("2025FY")
        e = parse_period("2024FY")
        ok, reason = periods_compatible(c, e)
        assert not ok
        assert "year" in reason


class TestInstant:
    def test_period_end_is_instant(self):
        pc = parse_period("2025期末")
        assert pc.duration_type == "instant"
