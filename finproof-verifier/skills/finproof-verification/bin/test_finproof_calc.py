#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finproof_calc.py 的单元测试（自包含，纯标准库，无需 pytest）。

运行：
    python3 bin/test_finproof_calc.py
    # 或
    python3 -m unittest bin/test_finproof_calc.py

覆盖：单位/币种换算、文本抽取（括号负数/千分位/方向词符号）、数值匹配容差、
同比增长率、累计转单季推导、各类比率、CAGR/EPS/ROE/资产负债率/现金流差异、期间归一化。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finproof_calc as fc  # noqa: E402


class TestUnitScale(unittest.TestCase):
    def test_yuan_scale(self):
        self.assertAlmostEqual(float(fc.convert_to_yuan(60, "亿元")), 6e9)
        self.assertAlmostEqual(float(fc.convert_to_yuan(100, "万元")), 1e6)
        self.assertAlmostEqual(float(fc.convert_to_yuan(456, "千元")), 456e3)

    def test_english_unit_is_usd(self):
        r = fc.convert_to_yuan(1, "million")
        self.assertAlmostEqual(float(r), 1e6)
        # currency 判定走 extract，这里只验换算值

    def test_no_unit_identity(self):
        self.assertAlmostEqual(float(fc.convert_to_yuan(1234.5, "")), 1234.5)


class TestExtract(unittest.TestCase):
    def test_bracket_negative_and_thousand_separator(self):
        vals = fc.extract_financial_values("营业收入(千元) 456,451,731；(1,081,776) 千元，同比下降 12.11%")
        # 括号负数
        neg = [v for v in vals if v["sign"] == "negative_paren"]
        self.assertEqual(len(neg), 1)
        self.assertAlmostEqual(neg[0]["value"], 1081776.0)
        self.assertAlmostEqual(neg[0]["value_in_yuan"], -1081776000.0)
        self.assertEqual(neg[0]["unit"], "千元")
        # 千分位剥离
        plain = [v for v in vals if v["raw_text"].startswith("456")]
        self.assertEqual(len(plain), 1)
        self.assertAlmostEqual(plain[0]["value"], 456451731.0)

    def test_yoy_decline_sign_on_percentage(self):
        vals = fc.extract_financial_values("同比下降 12.11%")
        pct = [v for v in vals if v["raw_text"] == "12.11%"]
        self.assertEqual(len(pct), 1)
        self.assertEqual(pct[0]["sign"], "yoy_decline")
        self.assertEqual(pct[0]["percentage_type"], "percentage")
        self.assertAlmostEqual(pct[0]["value_in_yuan"], -12.11)

    def test_empty_text(self):
        self.assertEqual(fc.extract_financial_values(""), [])


class TestMatch(unittest.TestCase):
    def test_match_within_tolerance(self):
        ok, _ = fc.values_match(60, "亿元", 6e9, fc.VALUE_TOLERANCE)
        self.assertTrue(ok)

    def test_mismatch_outside_tolerance(self):
        ok, _ = fc.values_match(60, "亿元", 3.2e9, fc.VALUE_TOLERANCE)
        self.assertFalse(ok)

    def test_both_zero(self):
        ok, _ = fc.values_match(0, "元", 0.0, fc.VALUE_TOLERANCE)
        self.assertTrue(ok)

    def test_tolerance_is_point_one_percent(self):
        # 修正记录（v2.0.0）：本断言原为 0.005（0.5%），与测试名"0.1%"、
        # calc-engine.md 所述设计意图（Phase 23.7 由 0.5% 收紧到 0.1% 以消除
        # 假阳性支持）均矛盾。经确认 0.1% 为设计意图，已统一为 0.001。
        self.assertAlmostEqual(fc.VALUE_TOLERANCE, 0.001)

    def test_rounding_exemption_cap(self):
        # 披露舍入豁免上限须与容差分离：容差 0.1% 用于自动匹配，
        # 0.5% 仅用于"差异可由声明舍入精度解释"的人工豁免判定。
        self.assertAlmostEqual(fc.ROUNDING_EXEMPTION_CAP, 0.005)
        self.assertLess(fc.VALUE_TOLERANCE, fc.ROUNDING_EXEMPTION_CAP)


class TestYoy(unittest.TestCase):
    def test_basic(self):
        val, _ = fc.yoy(32, 28)
        self.assertAlmostEqual(val, 100 * (32 - 28) / 28, places=6)

    def test_zero_previous_returns_none(self):
        val, detail = fc.yoy(10, 0)
        self.assertIsNone(val)
        self.assertIn("0", detail)

    def test_growth_tolerance_constant(self):
        self.assertAlmostEqual(fc.GROWTH_TOLERANCE_PP, 0.5)


class TestQuarterDerivation(unittest.TestCase):
    def test_q2_from_h1_q1(self):
        val, formula, _ = fc.derive_quarter(h1=60, q1=28)
        self.assertAlmostEqual(val, 32.0)
        self.assertEqual(formula, "Q2 = H1 − Q1")

    def test_q4_from_fy(self):
        val, formula, _ = fc.derive_quarter(fy=100, q1=28, q2=32, q3=25)
        self.assertAlmostEqual(val, 15.0)
        self.assertEqual(formula, "Q4 = FY − Q1 − Q2 − Q3")

    def test_h1_from_q1_q2(self):
        val, formula, _ = fc.derive_quarter(q1=28, q2=32)
        self.assertAlmostEqual(val, 60.0)
        self.assertEqual(formula, "H1 = Q1 + Q2")

    def test_insufficient_inputs(self):
        val, formula, _ = fc.derive_quarter(h1=60)
        self.assertIsNone(val)


class TestMargins(unittest.TestCase):
    def test_gross_margin(self):
        m = fc.margin(100, cost=60)
        self.assertAlmostEqual(m["gross_margin_pct"], 40.0)

    def test_net_margin(self):
        m = fc.margin(100, net_profit=15)
        self.assertAlmostEqual(m["net_margin_pct"], 15.0)

    def test_expense_ratio_and_business_share(self):
        m = fc.margin(100, expense=10, segment_revenue=20)
        self.assertAlmostEqual(m["expense_ratio_pct"], 10.0)
        self.assertAlmostEqual(m["business_share_pct"], 20.0)


class TestRatios(unittest.TestCase):
    def test_cagr(self):
        val, _ = fc.cagr(200, 100, 3)
        self.assertAlmostEqual(val, 25.992104989487316, places=6)

    def test_eps(self):
        self.assertAlmostEqual(fc.eps(15, 10), 1.5)

    def test_roe(self):
        self.assertAlmostEqual(fc.roe(15, 100), 15.0)

    def test_debt_ratio(self):
        self.assertAlmostEqual(fc.debt_ratio(50, 100), 50.0)

    def test_cashflow_diff(self):
        val, _ = fc.cashflow_diff(20, 15)
        self.assertAlmostEqual(val, 5.0)


class TestPeriodNormalization(unittest.TestCase):
    def test_q2_standalone(self):
        p = fc.parse_period("2025Q2 standalone")
        self.assertEqual(p["fiscal_year"], 2025)
        self.assertEqual(p["fiscal_quarter"], 2)
        self.assertEqual(p["standalone_or_cumulative"], "standalone")

    def test_h1_cumulative(self):
        p = fc.parse_period("2025H1")
        self.assertEqual(p["document_type"], "semi")
        self.assertEqual(p["standalone_or_cumulative"], "cumulative")

    def test_fy_annual(self):
        p = fc.parse_period("2025FY")
        self.assertEqual(p["document_type"], "annual")
        self.assertEqual(p["standalone_or_cumulative"], "cumulative")

    def test_yoy_base(self):
        p = fc.parse_period("2025Q1 同比增长")
        self.assertEqual(p["yoy_base_period"], "2024Q1")


class TestTemporal(unittest.TestCase):
    """v2.6.2 引用时序检查：'时序不可能'由模型语义判定收敛为确定性输出。"""

    def test_annual_report_vs_next_year_h1_impossible(self):
        # E5 原型：2025 年报不可能披露 2026H1 数据
        r = fc.temporal_check("2025年年度报告", "2026年上半年")
        self.assertEqual(r["verdict"], "IMPOSSIBLE")

    def test_annual_report_vs_next_year_q1_impossible(self):
        r = fc.temporal_check("2025年年度报告", "2026Q1")
        self.assertEqual(r["verdict"], "IMPOSSIBLE")

    def test_semi_report_covers_h1(self):
        r = fc.temporal_check("2026年半年度报告", "2026年上半年")
        self.assertEqual(r["verdict"], "COVERED")

    def test_annual_report_covers_q1(self):
        r = fc.temporal_check("2025年年度报告", "2025年第一季度")
        self.assertEqual(r["verdict"], "COVERED")

    def test_semi_report_vs_july_impossible(self):
        # 月粒度：半年报（至 6-30）不可能披露 7 月数据
        r = fc.temporal_check("2026年半年度报告", "2026年7月")
        self.assertEqual(r["verdict"], "IMPOSSIBLE")

    def test_snapshot_date_before_data_impossible(self):
        r = fc.temporal_check("2025-12-31", "2026-06-30")
        self.assertEqual(r["verdict"], "IMPOSSIBLE")

    def test_data_extends_beyond_source_partial(self):
        # 数据期间超出来源覆盖：超出部分不可能来自该来源
        r = fc.temporal_check("2026年半年度报告", "2026年")
        self.assertEqual(r["verdict"], "PARTIAL")

    def test_q3_report_covers_q3_standalone(self):
        # 三季报为累计口径（1-1~9-30），覆盖第三季度单季（7-1~9-30）
        r = fc.temporal_check("2026年三季报", "2026年第三季度")
        self.assertEqual(r["verdict"], "COVERED")

    def test_bare_year_vs_next_h1_impossible(self):
        r = fc.temporal_check("2026", "2027年上半年")
        self.assertEqual(r["verdict"], "IMPOSSIBLE")

    def test_unparseable_source_unclear(self):
        r = fc.temporal_check("某来源", "2026年上半年")
        self.assertEqual(r["verdict"], "UNCLEAR")

    def test_impossible_reason_mentions_no_evidence_needed(self):
        r = fc.temporal_check("2025年年度报告", "2026年上半年")
        self.assertIn("无需证据闭环", r["reason"])
        self.assertIn("G1 不得收容", r["reason"])

    def test_h2_not_misread_as_h1(self):
        # "下半年"不得被"半年"关键词抢先命中
        s, e, k = fc.period_window("2026年下半年")
        self.assertEqual((s, e, k), ("2026-07-01", "2026-12-31", "h2"))


class TestSumCheck(unittest.TestCase):
    """v2.8.0 总和一致性：SOTP/成本明细/分部收入的确定性核对。"""

    def test_sotp_consistent(self):
        r = fc.sum_check(["117.0", "88.9"], 205.9)
        self.assertTrue(r["matched"])
        self.assertAlmostEqual(r["abs_diff"], 0.0)

    def test_denominator_swap_detected(self):
        # 第一轮测评 E8 原型：分项真、合计基数错拿（117/88.9 vs 171.0）
        r = fc.sum_check(["117.0", "88.9"], 171.0)
        self.assertFalse(r["matched"])
        self.assertGreater(r["rel_diff_pct"], 20.0)

    def test_single_part(self):
        r = fc.sum_check(["52.06"], 52.06)
        self.assertTrue(r["matched"])

    def test_negative_parts(self):
        r = fc.sum_check(["100", "-30"], 70)
        self.assertTrue(r["matched"])

    def test_zero_total_zero_diff(self):
        r = fc.sum_check(["0", "0"], 0)
        self.assertTrue(r["matched"])
        self.assertAlmostEqual(r["rel_diff_pct"], 0.0)

    def test_custom_tolerance(self):
        r = fc.sum_check(["100", "1"], 100, tolerance=0.02)
        self.assertTrue(r["matched"])  # 1% 偏差在 2% 容差内

    def test_rejects_nonnumeric(self):
        # 输入错误应是可读 ValueError，而不是裸 decimal.InvalidOperation
        with self.assertRaises(ValueError):
            fc.sum_check(["abc"], 10)

    def test_default_tolerance_is_engine_standard(self):
        r = fc.sum_check(["100", "0.2"], 100)
        self.assertFalse(r["matched"])  # 0.2% > 0.1% 默认容差


class TestCliContract(unittest.TestCase):
    """CLI 契约：v2.8.0 的 sum_check help 串含未转义 %，曾使 `--help` 直接崩溃。"""

    def test_parser_help_renders(self):
        text = fc.build_parser().format_help()
        self.assertIn("sum_check", text)
        self.assertIn("0.1%", text)  # %% 转义后应还原为单个百分号

    def test_cli_help_exits_zero(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
            fc.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("sum_check", buf.getvalue())

    def test_invalid_input_returns_error_json(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fc.main(["sum_check", "--values", "a,b", "--total", "10"])
        self.assertEqual(code, 2)          # 引擎契约：输入错误 → 退出码 2
        self.assertIn("非数字", buf.getvalue())  # 且为 JSON，可被 agent 解析

    def test_cli_no_args_is_usage_error(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            fc.main([])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("cmd", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
