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


class TestForecastScan(unittest.TestCase):
    """v2.8.1 预测事实化：确定性措辞 + 依据披露（第一轮 E7 丢分的确定性补丁）。"""

    def test_certainty_forecast_flagged(self):
        r = fc.forecast_scan("2026 年归母净利润达 12 亿元已无悬念")
        self.assertTrue(r["forecast_as_fact"])
        self.assertEqual(r["verdict"], "FLAG")
        self.assertIn("已无悬念", r["strong_hits"])

    def test_basis_disclosed_not_flagged(self):
        r = fc.forecast_scan("预计 2026 年净利润 12 亿元已无悬念", evidence_ids=["E05"])
        self.assertFalse(r["forecast_as_fact"])
        self.assertTrue(r["basis_disclosed"])

    def test_has_method_not_flagged(self):
        r = fc.forecast_scan("预计 2026 年净利润 12 亿元已无悬念", has_method=True)
        self.assertFalse(r["forecast_as_fact"])

    def test_negation_masked(self):
        r = fc.forecast_scan("毛利率不一定提升，存在一定不确定性")
        self.assertFalse(r["forecast_as_fact"])

    def test_non_forecast_is_clean(self):
        r = fc.forecast_scan("公司 2025 年营业收入 60.00 亿元")
        self.assertFalse(r["forecast_like"])
        self.assertEqual(r["verdict"], "CLEAN")

    def test_weak_certainty_needs_forecast_context(self):
        # "确定"在非预测语境（确定了供应商）不应误报
        r = fc.forecast_scan("董事会确定了新的供应商名单")
        self.assertFalse(r["forecast_as_fact"])


class TestCiteCheck(unittest.TestCase):
    """v2.8.1 引用真伪：链接可达 / 摘录逐字命中 / 来源日期与数据期间一致。"""

    def _tmp_html(self, html_text):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_text)
        self.addCleanup(os.unlink, path)
        return path

    def test_match_ignores_html_tags_and_whitespace(self):
        p = self._tmp_html("<p>归母净利润 <b>2.8 亿元</b>，同比增长 12.4%</p><script>var x=1</script>")
        r = fc.cite_check(file=p, excerpt="归母净利润2.8亿元，同比增长12.4%")
        self.assertTrue(r["excerpt_found"])
        self.assertEqual(r["verdict"], "PASS")

    def test_ellipsis_requires_all_segments(self):
        p = self._tmp_html("<p>营收 60 亿元；归母净利润 2.8 亿元；同比增长 12.4%</p>")
        ok = fc.cite_check(file=p, excerpt="营收 60 亿元…归母净利润 2.8 亿元")
        bad = fc.cite_check(file=p, excerpt="营收 60 亿元…净利润 3.9 亿元")
        self.assertTrue(ok["excerpt_found"])
        self.assertFalse(bad["excerpt_found"])

    def test_missing_excerpt_fails_as_misattribution(self):
        p = self._tmp_html("<p>同比增长 12.4%</p>")
        r = fc.cite_check(file=p, excerpt="同比增长 19.9%")
        self.assertEqual(r["verdict"], "FAIL")
        self.assertIn("摘录未命中", r["reason"])

    def test_temporal_impossible_when_source_predates_period(self):
        p = self._tmp_html("<p>归母净利润 2.8 亿元</p>")
        r = fc.cite_check(file=p, excerpt="归母净利润 2.8 亿元",
                          source_date="2026-04-24", period="2026H1")
        self.assertFalse(r["date_ok"])
        self.assertEqual(r["verdict"], "FAIL")
        self.assertIn("时序不可能", r["reason"])

    def test_temporal_ok_for_q1_report(self):
        p = self._tmp_html("<p>归母净利润 2.8 亿元</p>")
        r = fc.cite_check(file=p, excerpt="归母净利润 2.8 亿元",
                          source_date="2026-04-24", period="2026Q1")
        self.assertTrue(r["date_ok"])
        self.assertEqual(r["verdict"], "PASS")

    def test_unreachable_snapshot_fails(self):
        r = fc.cite_check(file="/nonexistent/never.html", excerpt="任意")
        self.assertFalse(r["reachable"])
        self.assertEqual(r["verdict"], "FAIL")
        self.assertIn("不可达", r["reason"])

    def test_fullwidth_digits_normalized(self):
        p = self._tmp_html("<p>净利润 2.8 亿元</p>")
        r = fc.cite_check(file=p, excerpt="净利润 ２.８ 亿元")
        self.assertTrue(r["excerpt_found"])


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

    def test_cite_check_cli_json(self):
        import contextlib
        import io
        import json as _json
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("<p>净利润 2.8 亿元，同比增长 12.4%</p>")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = fc.main(["cite_check", "--file", path, "--excerpt", "净利润 2.8 亿元"])
            self.assertEqual(code, 0)
            data = _json.loads(buf.getvalue())
            self.assertEqual(data["verdict"], "PASS")
        finally:
            os.unlink(path)

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


class TestCoverageScan(unittest.TestCase):
    """拆解覆盖率下界（v2.9.0）：只回答"有没有整段没看"，不判主张对错。"""

    def test_counts_flagged_sentences(self):
        t = "2025 年营业收入 52.06 亿元，同比增长 12%。\n毛利率 25.31%，同比改善。"
        r = fc.coverage_scan(t)
        self.assertGreaterEqual(r["min_claim_floor"], 2)
        self.assertEqual(r["flagged_sentences"], r["min_claim_floor"])
        self.assertIn("NUM", r["by_type"])

    def test_year_alone_is_not_a_claim(self):
        r = fc.coverage_scan("本报告期覆盖 2025 年度。")
        self.assertEqual(r["min_claim_floor"], 0)

    def test_under_covered_status(self):
        t = "营收 10 亿元，同比增 5%。\n净利 2 亿元，同比增 8%。\n毛利 30%，提升 2 个百分点。"
        r = fc.coverage_scan(t, claims=1)
        self.assertEqual(r["claims_check"]["status"], "UNDER_COVERED")
        self.assertGreater(r["claims_check"]["gap"], 0)
        self.assertIn("漏拆", r["claims_check"]["action"])

    def test_ok_status_when_claims_meet_floor(self):
        t = "营收 10 亿元，同比增 5%。"
        r = fc.coverage_scan(t, claims=5)
        self.assertEqual(r["claims_check"]["status"], "OK")
        self.assertEqual(r["claims_check"]["gap"], 0)

    def test_table_rows_flagged(self):
        t = "| 2026H1 | 5.13 | 2.42 | 2.71 |"
        r = fc.coverage_scan(t)
        self.assertEqual(r["table_rows"], 1)
        self.assertIn("TABLE_ROW", r["by_type"])

    def test_truncation_reports_remainder(self):
        t = "\n".join(f"第{i}项营收 {i} 亿元，同比增长 3%。" for i in range(1, 11))
        r = fc.coverage_scan(t, max_points=3)
        self.assertEqual(len(r["points"]), 3)
        self.assertEqual(r["points_truncated"], r["min_claim_floor"] - 3)

    def test_sampling_plan_budget_and_disclosure(self):
        t = "\n".join(f"第{i}项营收 {i} 亿元，同比增长 3%。" for i in range(1, 21))
        t += "\n评级：买入，目标价 20 元。"
        r = fc.coverage_scan(t, budget=3)
        sp = r["sampling_plan"]
        self.assertEqual(sp["selected"], 3)
        self.assertLess(sp["coverage_of_floor_pct"], 100)
        self.assertIn("覆盖率", sp["must_disclose"])

    def test_sampling_plan_prefers_bearing_conclusion(self):
        """承重结论句（评级/目标价）必须优先于普通数值句进入抽样。"""
        t = "\n".join(f"第{i}项营收 {i} 亿元，同比增长 3%。" for i in range(1, 21))
        t += "\n评级：买入，目标价 20 元。"
        r = fc.coverage_scan(t, budget=1)
        self.assertIn("买入", r["sampling_plan"]["points"][0]["text"])

    def test_priority_anchor_beats_plain_number(self):
        self.assertGreater(fc._priority_score(["NUM"], "评级：买入"),
                           fc._priority_score(["NUM"], "营收 10 亿元"))

    def test_stratified_pick_keeps_qualitative_quota(self):
        """纯数值密度排序会漏掉定性错误，分层必须给因果/预测类保底名额。"""
        pts = [{"line": i, "types": ["NUM", "PCT", "GROWTH"], "text": f"营收{i}亿", "priority": 60}
               for i in range(1, 21)]
        pts += [{"line": 30, "types": ["CAUSAL"], "text": "已成核心引擎", "priority": 20},
                {"line": 31, "types": ["FORECAST"], "text": "将突破", "priority": 10}]
        picked = fc._stratified_pick(pts, 12)
        lines = {p["line"] for p in picked}
        self.assertEqual(len(picked), 12)
        self.assertIn(30, lines)
        self.assertIn(31, lines)

    def test_stratified_pick_respects_budget(self):
        pts = [{"line": i, "types": ["NUM"], "text": "x", "priority": 50} for i in range(10)]
        self.assertEqual(len(fc._stratified_pick(pts, 3)), 3)
        self.assertEqual(len(fc._stratified_pick(pts, 100)), 10)


class TestArtifactAudit(unittest.TestCase):
    """结构化产物缺陷检查（v2.12.0 起）：9 类基础可判 + 2 类按设计弃权。

    图表/文档结构域 13 类（v2.17.0）另见 TestArtifactAuditGraphDomain。
    """

    def test_reconcile_unit_scale_flip(self):
        r = fc.artifact_audit({"kind": "reconcile", "reported": 101930, "source": 101.93,
                               "tol_kind": "currency", "unit_reported": "USD_M",
                               "unit_source": "USD_B"})
        self.assertEqual(r["verdict"], "violation")

    def test_reconcile_within_tolerance(self):
        r = fc.artifact_audit({"kind": "reconcile", "reported": 15.49, "source": 15.0,
                               "tol_kind": "ratio_pp", "unit_reported": "percent",
                               "unit_source": "percent"})
        self.assertEqual(r["verdict"], "consistent")

    def test_reconcile_just_over_tolerance(self):
        r = fc.artifact_audit({"kind": "reconcile", "reported": 15.51, "source": 15.0,
                               "tol_kind": "ratio_pp", "unit_reported": "percent",
                               "unit_source": "percent"})
        self.assertEqual(r["verdict"], "violation")

    def test_reconcile_string_amount_with_symbol(self):
        """字符串数值 + 货币符号 + 全称单位。"""
        r = fc.artifact_audit({"kind": "reconcile", "reported": "8.4", "source": "$8,400 million",
                               "tol_kind": "currency", "unit_reported": "USD billions",
                               "unit_source": "USD millions"})
        # 单位表述不同 → 按主集口径判 violation（数据集内部冲突，见 README）
        self.assertEqual(r["verdict"], "violation")

    def test_reconcile_fullwidth_and_cjk_unit(self):
        """中文单位 8.4亿 = 840 百万，报告写 8400 百万 → 10 倍错。"""
        r = fc.artifact_audit({"kind": "reconcile", "reported": "8400", "source": "8.4亿",
                               "tol_kind": "currency", "unit_reported": "CNY millions",
                               "unit_source": "CNY"})
        self.assertEqual(r["verdict"], "violation")

    def test_waterfall_bridge_not_closed(self):
        r = fc.artifact_audit({"kind": "waterfall", "bars": [
            {"label": "b", "type": "baseline", "value": 100, "start": 0, "end": 100},
            {"label": "d", "type": "negative", "value": -10, "start": 100, "end": 90},
            {"label": "r", "type": "result", "value": 95, "start": 0, "end": 95}]})
        self.assertEqual(r["verdict"], "violation")

    def test_waterfall_clean(self):
        r = fc.artifact_audit({"kind": "waterfall", "bars": [
            {"label": "b", "type": "baseline", "value": 100, "start": 0, "end": 100},
            {"label": "d", "type": "negative", "value": -10, "start": 100, "end": 90},
            {"label": "r", "type": "result", "value": 90, "start": 0, "end": 90}]})
        self.assertEqual(r["verdict"], "consistent")

    def test_waterfall_missing_start_end(self):
        r = fc.artifact_audit({"kind": "waterfall", "bars": [
            {"label": "b", "type": "baseline", "value": 100, "start": 0, "end": 100},
            {"label": "d", "type": "negative", "value": 4.3},
            {"label": "r", "type": "result", "value": 104.3, "start": 0, "end": 104.3}]})
        self.assertEqual(r["verdict"], "violation")

    def test_sankey_orphan_node(self):
        r = fc.artifact_audit({"kind": "sankey", "nodes": ["A", "B", "C"],
                               "links": [{"source": "A", "target": "B", "value": 10}]})
        self.assertEqual(r["verdict"], "violation")

    def test_period_natural_language(self):
        """'three months ended' 是季度，配 FY 年度数字 → 不一致。"""
        r = fc.artifact_audit({"kind": "period",
                               "copy_period": "for the three months ended March 31, 2026",
                               "current_year_period": "FY2026"})
        self.assertEqual(r["verdict"], "violation")

    def test_period_fiscal_year_end_mismatch(self):
        r = fc.artifact_audit({"kind": "period",
                               "copy_period": "fiscal year ended January 28, 2026",
                               "current_year_period": "FY ended December 31, 2025"})
        self.assertEqual(r["verdict"], "violation")

    def test_period_key_drift(self):
        """期间值落在 current_period 而非 current_year_period 时也要读到。"""
        r = fc.artifact_audit({"kind": "period", "copy_period": "Q4 2025",
                               "current_year_period": None, "current_period": "FY2025"})
        self.assertEqual(r["verdict"], "violation")

    def test_metrics_table_verdict_vocab(self):
        rows = [{"name": n, "cells": [n, 1, 2, "Stable"], "verdict": "Stable"}
                for n in fc._ART_METRIC_ROWS]
        rows[0]["verdict"] = "collapsed"
        self.assertEqual(fc.artifact_audit({"kind": "metrics_table", "rows": rows})["verdict"],
                         "violation")

    def test_metrics_table_na_row_allows_prose_verdict(self):
        """数值全为 N/A 的行（负净资产下的 ROE）允许描述性 verdict。"""
        rows = [{"name": n, "cells": [n, 1, 2, "Stable"], "verdict": "Stable"}
                for n in fc._ART_METRIC_ROWS]
        for r in rows:
            if r["name"] == "ROE":
                r["cells"] = ["N/A", "N/A", "N/A", "N/A"]
                r["verdict"] = "Equity deficit narrowed"
        self.assertEqual(fc.artifact_audit({"kind": "metrics_table", "rows": rows})["verdict"],
                         "consistent")

    def test_gate_source_case_and_space_normalized(self):
        for src in ("User_Response", " user_response "):
            r = fc.artifact_audit({"kind": "gate_source", "gate": "language", "source": src})
            self.assertEqual(r["verdict"], "consistent", src)

    def test_gate_source_invented(self):
        r = fc.artifact_audit({"kind": "gate_source", "gate": "palette", "source": "assumed"})
        self.assertEqual(r["verdict"], "violation")

    def test_user_agent_pii_leak(self):
        r = fc.artifact_audit({"kind": "user_agent", "url": "https://news.example.com/x",
                               "user_agent": "Skill/1.0 (a@b.com)"})
        self.assertEqual(r["verdict"], "violation")

    def test_user_agent_email_to_sec_ok(self):
        r = fc.artifact_audit({"kind": "user_agent",
                               "url": "https://data.sec.gov/api/xbrl/companyfacts/CIK1.json",
                               "user_agent": "Skill/1.0 (a@b.com)"})
        self.assertEqual(r["verdict"], "consistent")

    def test_narrative_abstains(self):
        self.assertEqual(fc.artifact_audit({"kind": "narrative", "text": "x"})["verdict"], "abstain")

    def test_unknown_kind_abstains(self):
        self.assertEqual(fc.artifact_audit({"kind": "brand_new"})["verdict"], "abstain")


class TestArtifactAuditGraphDomain(unittest.TestCase):
    """图表/文档结构域 13 类检查器（v2.17.0，OOD 盲评面板暴露的检出空白）。

    用例数据取自 AnamnesisBench OOD（ood.jsonl），正反例与盲评金标一致。
    """

    # ── sankey 方向（OOD-0055：质量守恒但 Total 被当作下游）──
    def test_sankey_total_node_receives_inflow(self):
        r = fc.artifact_audit({"kind": "sankey",
                               "nodes": ["Total Revenue", "North America", "International",
                                         "Recognized Revenue"],
                               "links": [{"source": "North America", "target": "Total Revenue",
                                          "value": 700},
                                         {"source": "International", "target": "Total Revenue",
                                          "value": 300},
                                         {"source": "Total Revenue", "target": "Recognized Revenue",
                                          "value": 1000}]})
        self.assertEqual(r["verdict"], "violation")
        self.assertIn("方向反转", r["reason"])

    def test_sankey_total_as_source_ok(self):
        r = fc.artifact_audit({"kind": "sankey",
                               "nodes": ["Total Revenue", "Americas", "EMEA",
                                         "Gross Profit", "COGS"],
                               "links": [{"source": "Total Revenue", "target": "Americas",
                                          "value": 500},
                                         {"source": "Total Revenue", "target": "EMEA",
                                          "value": 300},
                                         {"source": "Americas", "target": "Gross Profit",
                                          "value": 350},
                                         {"source": "Americas", "target": "COGS",
                                          "value": 150},
                                         {"source": "EMEA", "target": "Gross Profit",
                                          "value": 200},
                                         {"source": "EMEA", "target": "COGS",
                                          "value": 100}]})
        self.assertEqual(r["verdict"], "consistent")

    # ── cross_section_mismatch ──
    def test_cross_section_mismatch(self):
        r = fc.artifact_audit({"kind": "cross_section_mismatch", "metric": "Total revenue",
                               "stated_total": 1000.0, "unit": "USD millions",
                               "segments": [{"name": "Americas", "value": 450.0},
                                            {"name": "EMEA", "value": 300.0},
                                            {"name": "APAC", "value": 200.0}]})
        self.assertEqual(r["verdict"], "violation")

    def test_cross_section_rounding_within_tolerance(self):
        """分部舍入到 0.1 的合计缺口（0.05%）是披露舍入，不是截面错。"""
        r = fc.artifact_audit({"kind": "cross_section_mismatch", "metric": "Total revenue",
                               "stated_total": 1000.0, "unit": "USD millions",
                               "note": "segments rounded to nearest 0.1",
                               "segments": [{"name": "Americas", "value": 450.3},
                                            {"name": "EMEA", "value": 300.2},
                                            {"name": "APAC", "value": 249.0}]})
        self.assertEqual(r["verdict"], "consistent")

    # ── currency_mixing ──
    def test_currency_mixing_without_fx(self):
        """名义和相等（1000+500=1500）也不能跨币种相加。"""
        r = fc.artifact_audit({"kind": "currency_mixing", "metric": "Total revenue",
                               "stated_total": {"value": 1500.0, "unit": "USD millions"},
                               "components": [{"name": "US ops", "value": 1000.0,
                                               "unit": "USD millions"},
                                              {"name": "China ops", "value": 500.0,
                                               "unit": "CNY millions"}]})
        self.assertEqual(r["verdict"], "violation")

    def test_currency_uniform_sums_ok(self):
        r = fc.artifact_audit({"kind": "currency_mixing", "metric": "Total revenue",
                               "stated_total": {"value": 1500.0, "unit": "USD millions"},
                               "components": [{"name": "US ops", "value": 1000.0,
                                               "unit": "USD millions"},
                                              {"name": "EU ops", "value": 500.0,
                                               "unit": "USD millions"}]})
        self.assertEqual(r["verdict"], "consistent")

    # ── duplicate_row ──
    def test_duplicate_row_detected(self):
        r = fc.artifact_audit({"kind": "duplicate_row", "table": "Segment revenue",
                               "unit": "USD millions",
                               "rows": [{"name": "Cloud", "value": 400.0},
                                        {"name": "Advertising", "value": 350.0},
                                        {"name": "Cloud", "value": 420.0},
                                        {"name": "Hardware", "value": 150.0}]})
        self.assertEqual(r["verdict"], "violation")

    def test_duplicate_row_unique_ok(self):
        r = fc.artifact_audit({"kind": "duplicate_row", "table": "Segment revenue",
                               "rows": [{"name": "Cloud", "value": 400.0},
                                        {"name": "Hardware", "value": 150.0}]})
        self.assertEqual(r["verdict"], "consistent")

    # ── date_inconsistency ──
    def test_date_comparative_window_truncated(self):
        """对比期期末 12-30 vs 本期 12-31：窗口被截短一天。"""
        r = fc.artifact_audit({"kind": "date_inconsistency",
                               "period_label": "Fiscal year 2025",
                               "period_start": "2025-01-01", "period_end": "2025-12-31",
                               "comparative_label": "Prior year (FY2024)",
                               "comparative_start": "2024-01-01",
                               "comparative_end": "2024-12-30"})
        self.assertEqual(r["verdict"], "violation")

    def test_date_leap_year_drift_is_consistent(self):
        """2024 闰年 366 天 vs 2025 的 365 天：≤1 天漂移放行。"""
        r = fc.artifact_audit({"kind": "date_inconsistency",
                               "period_label": "FY2025",
                               "period_start": "01/01/2025", "period_end": "31/12/2025",
                               "comparative_label": "FY2024",
                               "comparative_start": "01/01/2024",
                               "comparative_end": "31/12/2024"})
        self.assertEqual(r["verdict"], "consistent")

    # ── negative_value_in_pie ──
    def test_pie_negative_slice(self):
        r = fc.artifact_audit({"kind": "negative_value_in_pie", "title": "Revenue by Segment",
                               "slices": [{"label": "Hardware", "value": 600},
                                          {"label": "Software", "value": 500},
                                          {"label": "Returns Adjustment", "value": -100}],
                               "total": 1000})
        self.assertEqual(r["verdict"], "violation")

    def test_pie_clean(self):
        r = fc.artifact_audit({"kind": "negative_value_in_pie", "title": "Revenue by Segment",
                               "slices": [{"label": "Hardware", "value": 600},
                                          {"label": "Software", "value": 300},
                                          {"label": "Services", "value": 100}],
                               "total": 1000})
        self.assertEqual(r["verdict"], "consistent")

    # ── axis_unit_mismatch ──
    def test_axis_unit_understated(self):
        """轴标 $Billions 但数值是 millions 口径：单点值超全年披露值。"""
        r = fc.artifact_audit({"kind": "axis_unit_mismatch", "title": "Quarterly Revenue",
                               "y_axis": {"label": "Revenue ($ Billions)", "unit": "B"},
                               "series": [{"period": "Q1", "value": 4200},
                                          {"period": "Q2", "value": 4350},
                                          {"period": "Q3", "value": 4500},
                                          {"period": "Q4", "value": 4810}],
                               "company_annual_revenue_usd": 17860000000})
        self.assertEqual(r["verdict"], "violation")

    def test_axis_unit_compatible(self):
        r = fc.artifact_audit({"kind": "axis_unit_mismatch", "title": "Quarterly Revenue",
                               "y_axis": {"label": "Revenue ($ Millions)", "unit": "M"},
                               "series": [{"period": "Q1", "value": 4200},
                                          {"period": "Q2", "value": 4350},
                                          {"period": "Q3", "value": 4500},
                                          {"period": "Q4", "value": 4810}],
                               "company_annual_revenue_usd": 17860000000})
        self.assertEqual(r["verdict"], "consistent")

    # ── double_counted_flow ──
    def test_double_counted_aggregate_plus_leaf(self):
        """Total→Subscription 与 Total→Subscription-Annual 并存：明细被计两次。"""
        r = fc.artifact_audit({"kind": "double_counted_flow",
                               "nodes": ["Total Revenue", "Subscription",
                                         "Subscription - Annual", "Subscription - Monthly",
                                         "Gross Profit"],
                               "links": [{"source": "Total Revenue", "target": "Subscription",
                                          "value": 800},
                                         {"source": "Subscription",
                                          "target": "Subscription - Annual", "value": 500},
                                         {"source": "Subscription",
                                          "target": "Subscription - Monthly", "value": 300},
                                         {"source": "Total Revenue",
                                          "target": "Subscription - Annual", "value": 500},
                                         {"source": "Total Revenue", "target": "Gross Profit",
                                          "value": 800}],
                               "stated_total_revenue": 800})
        self.assertEqual(r["verdict"], "violation")

    def test_double_counted_clean_branching(self):
        """兄弟分支共入下游不是重复计数。"""
        r = fc.artifact_audit({"kind": "double_counted_flow",
                               "nodes": ["Revenue", "Product", "Services", "Profit"],
                               "links": [{"source": "Revenue", "target": "Product",
                                          "value": 600},
                                         {"source": "Revenue", "target": "Services",
                                          "value": 400},
                                         {"source": "Product", "target": "Profit",
                                          "value": 600},
                                         {"source": "Services", "target": "Profit",
                                          "value": 400}],
                               "stated_total_revenue": 1000})
        self.assertEqual(r["verdict"], "consistent")

    # ── stacked_bar_total_mismatch ──
    def test_stacked_bar_total_mismatch(self):
        r = fc.artifact_audit({"kind": "stacked_bar_total_mismatch",
                               "title": "Revenue Mix by Year",
                               "bars": [{"year": 2024, "total": 700,
                                         "segments": [{"label": "A", "value": 300},
                                                      {"label": "B", "value": 400}]},
                                        {"year": 2025, "total": 750,
                                         "segments": [{"label": "A", "value": 350},
                                                      {"label": "B", "value": 450}]}]})
        self.assertEqual(r["verdict"], "violation")

    def test_stacked_bar_ok(self):
        r = fc.artifact_audit({"kind": "stacked_bar_total_mismatch",
                               "title": "Revenue Mix by Year",
                               "bars": [{"year": 2024, "total": 700,
                                         "segments": [{"label": "A", "value": 300},
                                                      {"label": "B", "value": 400}]}]})
        self.assertEqual(r["verdict"], "consistent")

    # ── dual_axis_scale_inversion ──
    def test_dual_axis_inverted_scale(self):
        r = fc.artifact_audit({"kind": "dual_axis_scale_inversion", "title": "Revenue vs Margin",
                               "left_axis": {"label": "Revenue ($M)", "min": 0, "max": 1000},
                               "right_axis": {"label": "Margin (%)", "min": 100, "max": 0},
                               "series": [{"period": "Q1", "revenue": 800, "margin": 25},
                                          {"period": "Q2", "revenue": 850, "margin": 30}]})
        self.assertEqual(r["verdict"], "violation")

    def test_dual_axis_normal(self):
        r = fc.artifact_audit({"kind": "dual_axis_scale_inversion", "title": "Revenue vs Margin",
                               "left_axis": {"label": "Revenue ($M)", "min": 0, "max": 1000},
                               "right_axis": {"label": "Margin (%)", "min": 0, "max": 100},
                               "series": [{"period": "Q1", "revenue": 800, "margin": 25}]})
        self.assertEqual(r["verdict"], "consistent")

    # ── retracted_citation ──
    def test_citation_withdrawn(self):
        r = fc.artifact_audit({"kind": "retracted_citation",
                               "claim": "FY25 revenue grew 18% YoY",
                               "citation": "https://www.sec.gov/Archives/aapl-8k-withdrawn.htm",
                               "citation_status": "withdrawn_by_filer"})
        self.assertEqual(r["verdict"], "violation")

    def test_citation_active(self):
        r = fc.artifact_audit({"kind": "retracted_citation",
                               "claim": "FY25 revenue grew 18% YoY",
                               "citation": "https://www.sec.gov/Archives/aapl-10k.htm",
                               "citation_status": "active"})
        self.assertEqual(r["verdict"], "consistent")

    # ── pii_in_body ──
    def test_pii_ssn_and_phone(self):
        r = fc.artifact_audit({"kind": "pii_in_body",
                               "body_excerpt": "Analyst of record: J. Okafor, mobile 415-555-0182, "
                                               "SSN 078-05-1120, see appendix."})
        self.assertEqual(r["verdict"], "violation")

    def test_pii_credit_card(self):
        r = fc.artifact_audit({"kind": "pii_in_body",
                               "body_excerpt": "Order ref for the data pull: 4111 1111 1111 1111 "
                                               "(corporate card), expiry 09/27."})
        self.assertEqual(r["verdict"], "violation")

    def test_pii_clean_prose(self):
        r = fc.artifact_audit({"kind": "pii_in_body",
                               "body_excerpt": "Analyst of record: J. Okafor, CFA. "
                                               "Contact via the firm's research desk."})
        self.assertEqual(r["verdict"], "consistent")

    # ── license_mismatch ──
    def test_license_mismatch(self):
        r = fc.artifact_audit({"kind": "license_mismatch", "asset": "embedded_chart_font",
                               "declared_license": "MIT",
                               "actual_license": "OFL-1.1-No-Derivatives",
                               "redistributed": True})
        self.assertEqual(r["verdict"], "violation")

    def test_license_match(self):
        r = fc.artifact_audit({"kind": "license_mismatch", "asset": "embedded_chart_font",
                               "declared_license": "MIT", "actual_license": "MIT License"})
        self.assertEqual(r["verdict"], "consistent")

    # ── stale_disclaimer ──
    def test_disclaimer_stale(self):
        r = fc.artifact_audit({"kind": "stale_disclaimer",
                               "disclaimer_text": "Coverage and ratings current as of FY2023; "
                                                  "not updated thereafter.",
                               "report_date": "2026-06-14"})
        self.assertEqual(r["verdict"], "violation")

    def test_disclaimer_dynamic_ok(self):
        r = fc.artifact_audit({"kind": "stale_disclaimer",
                               "disclaimer_text": "Information current as of the report date "
                                                  "shown on the cover; subject to change "
                                                  "without notice.",
                               "report_date": "2026-06-14"})
        self.assertEqual(r["verdict"], "consistent")

    def test_new_kind_cli_json(self):
        """CLI 入口对新 kind 同样可用（审计轨迹可直接落命令）。"""
        import contextlib
        import io
        import json as _json
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fc.main(["artifact_audit", "--json",
                            _json.dumps({"kind": "duplicate_row",
                                         "rows": [{"name": "A", "value": 1},
                                                  {"name": "A", "value": 2}]})])
        self.assertEqual(code, 0)
        self.assertEqual(_json.loads(buf.getvalue())["verdict"], "violation")


class TestNegativeBaseYoy(unittest.TestCase):
    """负基数下的同比方向（CFR-NumQA 386 道中文题暴露，v2.13.0 修）。

    分母必须取绝对值：亏损收窄 = 正增长，亏损扩大 = 负增长。
    分母用带符号的 prev 会把方向算反。
    """

    def test_loss_narrowing_is_positive_growth(self):
        # 上年 -86.2 亿，本期 -64.2 亿（亏损收窄）→ +25.5%
        v, _ = fc.yoy(-6419556843.85, -8617528506.44)
        self.assertAlmostEqual(v, 25.5058, places=3)

    def test_loss_widening_is_negative_growth(self):
        # 上年 -494.8 亿，本期 -885.6 亿（亏损扩大）→ -78.98%
        v, _ = fc.yoy(-88556470495.64, -49478429211.96)
        self.assertAlmostEqual(v, -78.98, places=2)

    def test_negative_to_positive_is_large_positive(self):
        # 上年 -47.2 亿，本期 +43.6 亿（转正）→ +192.3%
        v, _ = fc.yoy(4359382755.77, -4724978931.84)
        self.assertAlmostEqual(v, 192.2625, places=3)

    def test_positive_base_unchanged(self):
        v, _ = fc.yoy(439.45, 385.37)
        self.assertAlmostEqual(v, 14.0333, places=3)


class TestChineseCompositeUnits(unittest.TestCase):
    """带「元」的复合中文单位（CFR-NumQA 540 道抽取题暴露，v2.13.0 修）。

    原表只有「百万」没有「百万元」，convert 会静默按 1 倍处理，差 1e6。
    """

    def test_million_yuan_scale(self):
        self.assertAlmostEqual(float(fc.convert_to_yuan(1, "百万元")), 1e6)
        self.assertAlmostEqual(float(fc.convert_to_yuan(179895, "百万元")), 179895e6)

    def test_other_composite_units(self):
        cases = {"十万元": 1e5, "千万元": 1e7, "十亿元": 1e9,
                 "百亿元": 1e10, "千亿元": 1e11, "万亿元": 1e12}
        for u, want in cases.items():
            self.assertAlmostEqual(float(fc.convert_to_yuan(1, u)), want, msg=u)

    def test_extract_matches_convert_for_million(self):
        """extract 与 convert 对同一单位必须给出一致结果。"""
        got = fc.extract_financial_values("179,895百万元")[0]["value_in_yuan"]
        want = float(fc.convert_to_yuan(179895, "百万元"))
        self.assertAlmostEqual(got, want, delta=1.0)

    def test_accounting_paren_negative(self):
        got = fc.extract_financial_values("(49,478,429,211.96)元")[0]
        self.assertEqual(got["sign"], "negative_paren")
        self.assertAlmostEqual(got["value_in_yuan"], -49478429211.96, delta=1.0)

    def test_fullwidth_paren_negative(self):
        got = fc.extract_financial_values("（494.78）亿元")[0]
        self.assertEqual(got["sign"], "negative_paren")


class TestUnitParsingStrict(unittest.TestCase):
    """单位解析必须拒绝未知单位，不得静默按 1 倍（v2.15.0）。

    原先 `UNIT_SCALE.get(unit, 1.0)` 会把「亿美元」当成 1 倍，静默差 1e8。
    """

    def test_parsing_scales(self):
        for u, want, cur in [("亿美元", 1e8, "USD"), ("百万美元", 1e6, "USD"),
                             ("million USD", 1e6, "USD"), ("billion USD", 1e9, "USD"),
                             ("万元人民币", 1e4, "CNY"), ("千亿港元", 1e11, "HKD"),
                             ("万亿元", 1e12, "CNY"), ("USD millions", 1e6, "USD")]:
            s, c = fc.parse_unit(u)
            self.assertAlmostEqual(float(s), want, msg=u)
            self.assertEqual(c, cur, msg=u)

    def test_currency_longest_match_wins(self):
        """「港元」必须先于「元」命中，否则港股金额会按 CNY 解析。"""
        _, c = fc.parse_unit("亿港元")
        self.assertEqual(c, "HKD")

    def test_unknown_unit_raises(self):
        # 物理单位（吨/桶/公顷）已登记，不再算未知；未登记的单位仍必须拒绝。
        for u in ("widgets", "标准箱", "人次", "箱"):
            with self.assertRaises(ValueError, msg=u):
                fc.convert_to_yuan(1, u)

    def test_physical_units_are_recognized(self):
        for u, scale in [("吨", 1.0), ("万吨", 1e4), ("亿千瓦时", 1e8),
                         ("万千瓦", 1e4), ("万平方米", 1e4), ("吨/年", 1.0)]:
            s, cur = fc.parse_unit(u)
            self.assertAlmostEqual(float(s), scale, msg=u)
            self.assertIsNone(cur, msg=u)
            self.assertEqual(fc.unit_kind(u), "physical", msg=u)

    def test_physical_extract_keeps_unit(self):
        vals = fc.extract_financial_values("产量2.5万吨，单产2.5吨")
        units = [v["unit"] for v in vals]
        self.assertIn("万吨", units)
        self.assertIn("吨", units)
        self.assertTrue(all(v["unit_resolved"] for v in vals))

    def test_empty_unit_is_plain(self):
        self.assertAlmostEqual(float(fc.convert_to_yuan(1234.5, "")), 1234.5)

    def test_values_match_physical_unit(self):
        ok, reason = fc.values_match(2.5, "万吨", 25000.0)
        self.assertTrue(ok, reason)


class TestMeaninglessMetricsRefused(unittest.TestCase):
    """分母为负或为零时，比率类指标必须拒绝而非给一个看似合理的数。"""

    def test_roe_rejects_negative_equity(self):
        with self.assertRaises(ValueError):
            fc.roe(-50, -100)

    def test_roe_rejects_zero_equity(self):
        with self.assertRaises(ValueError):
            fc.roe(-50, 0)

    def test_debt_ratio_rejects_negative_assets(self):
        with self.assertRaises(ValueError):
            fc.debt_ratio(-50, -100)

    def test_debt_ratio_rejects_zero_assets(self):
        with self.assertRaises(ValueError):
            fc.debt_ratio(50, 0)

    def test_eps_rejects_zero_shares(self):
        with self.assertRaises(ValueError):
            fc.eps(-10, 0)

    def test_cagr_rejects_negative_base(self):
        val, reason = fc.cagr(-885.6, -494.8, 3)
        self.assertIsNone(val)
        self.assertIn("无意义", reason)

    def test_positive_paths_unchanged(self):
        self.assertAlmostEqual(fc.roe(15, 100), 15.0)
        self.assertAlmostEqual(fc.debt_ratio(50, 100), 50.0)
        self.assertAlmostEqual(fc.eps(-10, 100), -0.1)


class TestClaimGate(unittest.TestCase):
    """证据闸门：先判能不能判，再判对不对。"""

    def _payload(self, value=100, unit="亿元", period="2025FY", evidence=None, **kw):
        return {"claim": {"metric": "revenue", "value": value, "unit": unit, "period": period},
                "evidence": evidence if evidence is not None else [
                    {"id": "E1", "metric": "revenue", "value": 100, "unit": "亿元",
                     "period": "2025FY", "source_verified": True}], **kw}

    def test_pass_with_cross_unit(self):
        p = self._payload(evidence=[{"id": "E1", "metric": "revenue", "value": 1e10,
                                     "unit": "元", "period": "2025FY", "source_verified": True}])
        r = fc.claim_gate(p)
        self.assertEqual(r["decision"], "PASS")
        self.assertEqual(r["reason_code"], "VALUE_MATCH")

    def test_fail_when_value_differs(self):
        p = self._payload(evidence=[{"id": "E1", "metric": "revenue", "value": 90,
                                     "unit": "亿元", "period": "2025FY", "source_verified": True}])
        self.assertEqual(fc.claim_gate(p)["decision"], "FAIL")

    def test_abstain_without_evidence(self):
        self.assertEqual(fc.claim_gate(self._payload(evidence=[]))["reason_code"], "NO_EVIDENCE")

    def test_abstain_on_period_mismatch(self):
        p = self._payload(period="2025Q2", evidence=[{"id": "E1", "value": 100, "unit": "亿元",
                                                     "period": "2025Q1", "source_verified": True}])
        self.assertEqual(fc.claim_gate(p)["reason_code"], "PERIOD_MISMATCH")

    def test_abstain_on_conflict(self):
        p = self._payload(evidence=[
            {"id": "E1", "value": 100, "unit": "亿元", "period": "2025FY", "source_verified": True},
            {"id": "E2", "value": 120, "unit": "亿元", "period": "2025FY", "source_verified": True},
        ])
        self.assertEqual(fc.claim_gate(p)["reason_code"], "EVIDENCE_CONFLICT")

    def test_abstain_on_unverified_source(self):
        p = self._payload(evidence=[{"id": "E1", "value": 100, "unit": "亿元",
                                     "period": "2025FY", "source_verified": False}])
        self.assertEqual(fc.claim_gate(p)["reason_code"], "SOURCE_UNVERIFIED")

    def test_abstain_on_missing_value(self):
        self.assertEqual(fc.claim_gate({"claim": {"value": None, "unit": "亿元",
                                                   "period": "2025FY"}, "evidence": []})["reason_code"],
                         "CLAIM_VALUE_MISSING")

    def test_physical_unit_pass(self):
        p = {"claim": {"metric": "output", "value": 2.5, "unit": "万吨", "period": "2025FY"},
             "evidence": [{"id": "E1", "metric": "output", "value": 25000, "unit": "吨",
                           "period": "2025FY", "source_verified": True}]}
        self.assertEqual(fc.claim_gate(p)["decision"], "PASS")

    def test_currency_mismatch_fails(self):
        p = {"claim": {"metric": "revenue", "value": 100, "unit": "亿元", "period": "2025FY"},
             "evidence": [{"id": "E1", "metric": "revenue", "value": 100, "unit": "亿美元",
                           "period": "2025FY", "source_verified": True}]}
        r = fc.claim_gate(p)
        self.assertEqual(r["decision"], "FAIL")
        self.assertEqual(r["reason_code"], "CURRENCY_MISMATCH")

    def test_physical_dimension_mismatch_fails(self):
        p = {"claim": {"metric": "output", "value": 2.5, "unit": "万吨", "period": "2025FY"},
             "evidence": [{"id": "E1", "metric": "output", "value": 2.5, "unit": "万千瓦时",
                           "period": "2025FY", "source_verified": True}]}
        r = fc.claim_gate(p)
        self.assertEqual(r["decision"], "FAIL")
        self.assertEqual(r["reason_code"], "UNIT_DIMENSION_MISMATCH")

    def test_percent_vs_pp_fails(self):
        p = {"claim": {"metric": "margin", "value": 3.5, "unit": "%", "period": "2025FY"},
             "evidence": [{"id": "E1", "metric": "margin", "value": 3.5, "unit": "个百分点",
                           "period": "2025FY", "source_verified": True}]}
        r = fc.claim_gate(p)
        self.assertEqual(r["decision"], "FAIL")
        self.assertEqual(r["reason_code"], "RATIO_UNIT_MISMATCH")


class TestDualExtract(unittest.TestCase):
    def test_cross_unit_consistent(self):
        r = fc.dual_extract(
            {"metric": "revenue", "value": 100, "unit": "亿元", "period": "2025FY"},
            {"metric": "revenue", "value": 1e10, "unit": "元", "period": "2025FY"},
        )
        self.assertEqual(r["decision"], "CONSISTENT")

    def test_period_conflict_abstains(self):
        r = fc.dual_extract(
            {"metric": "revenue", "value": 100, "unit": "亿元", "period": "2025FY"},
            {"metric": "revenue", "value": 100, "unit": "亿元", "period": "2025Q1"},
        )
        self.assertEqual(r["decision"], "ABSTAIN")
        self.assertEqual(r["reason_code"], "EXTRACTION_CONFLICT")

    def test_missing_field_abstains(self):
        r = fc.dual_extract(
            {"metric": "revenue", "value": 100, "unit": "亿元", "period": "2025FY"},
            {"metric": "revenue", "unit": "亿元", "period": "2025FY"},
        )
        self.assertEqual(r["reason_code"], "EXTRACTION_INCOMPLETE")


class TestSaturationScan(unittest.TestCase):
    """规模饱和扫（v2.18.0）：零 token 机械复算全文自洽点。

    与 coverage_scan 组合：floor 是"该拆多少"，saturation 的 zero_token_verdicts
    是"其中多少不花 token 已判完"。只判句内/表内自洽，缺判据一律跳过不猜。
    """

    def _scan(self, text):
        return fc.saturation_scan(text)

    def _verdicts(self, r, check):
        return [f for f in r["findings"] if f["check"] == check]

    # ── 表内加总 ──
    def test_table_sum_violation(self):
        r = self._scan("| 分部 | 收入（亿元） |\n|---|---|\n| A | 600 |\n| B | 400 |\n| 合计 | 1050 |")
        v = self._verdicts(r, "table_sum")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["verdict"], "violation")
        self.assertAlmostEqual(v[0]["claimed"], 1050)

    def test_table_sum_consistent(self):
        r = self._scan("| 分部 | 收入（亿元） |\n|---|---|\n| A | 600 |\n| B | 400 |\n| 合计 | 1000 |")
        self.assertEqual(self._verdicts(r, "table_sum")[0]["verdict"], "consistent")

    def test_table_sum_skips_percent_cells(self):
        """数值列混入百分比单元格 → 不求和（跨量纲不可加）。"""
        r = self._scan("| 项 | 值 |\n|---|---|\n| 营收 | 100亿 |\n| 毛利率 | 25% |\n| 合计 | 125亿 |")
        self.assertEqual(len(self._verdicts(r, "table_sum")), 0)

    # ── 占比列 = 100% ──
    def test_table_share_sum_violation(self):
        r = self._scan("| 分部 | 收入 | 占比 |\n|---|---|---|\n| A | 600 | 50% |\n| B | 400 | 40% |\n| 合计 | 1000 | 90% |")
        v = self._verdicts(r, "table_share_sum")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["verdict"], "violation")  # 合计行的 90% 不计入分项

    def test_table_share_sum_consistent_excludes_total_row(self):
        r = self._scan("| 分部 | 收入 | 占比 |\n|---|---|---|\n| A | 600 | 60% |\n| B | 400 | 40% |\n| 合计 | 1000 | 100% |")
        v = self._verdicts(r, "table_share_sum")
        self.assertEqual(v[0]["verdict"], "consistent")

    def test_percent_column_without_share_header_not_checked(self):
        """毛利率列也是 % 值，但表头无占比语义 → 不做 =100% 检查。"""
        r = self._scan("| 指标 | 值 |\n|---|---|\n| 毛利率 | 25% |\n| 净利率 | 10% |")
        self.assertEqual(len(self._verdicts(r, "table_share_sum")), 0)

    # ── 同句同比 ──
    def test_yoy_from_to_violation(self):
        r = self._scan("新能源汽车业务收入从 80 亿元增长至 100 亿元，同比增长 30.0%。")
        v = self._verdicts(r, "yoy_from_to")
        self.assertEqual(v[0]["verdict"], "violation")
        self.assertAlmostEqual(v[0]["computed"], 25.0, places=2)

    def test_yoy_from_to_consistent(self):
        r = self._scan("新能源汽车业务收入从 80 亿元增长至 100 亿元，同比增长 25.0%。")
        self.assertEqual(self._verdicts(r, "yoy_from_to")[0]["verdict"], "consistent")

    def test_yoy_from_to_with_year_qualifier(self):
        """'从2024年的80亿元'：年份是状语，基数取年份后的数值。"""
        r = self._scan("公司收入从 2024 年的 80 亿元增长至 2025 年的 100 亿元，同比增长 30%。")
        v = self._verdicts(r, "yoy_from_to")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["verdict"], "violation")
        self.assertAlmostEqual(v[0]["computed"], 25.0, places=2)

    def test_yoy_from_to_without_claim_skipped(self):
        """未给出增速 % 就无从对账——不是缺陷，不产出 finding。"""
        r = self._scan("收入从 80 亿元增长至 100 亿元。")
        self.assertEqual(len(self._verdicts(r, "yoy_from_to")), 0)

    def test_yoy_base_in_sentence_violation(self):
        r = self._scan("公司 2025 年营收 100 亿元，上年同期 80 亿元，同比增长 28%。")
        v = self._verdicts(r, "yoy_base_in_sentence")
        self.assertEqual(v[0]["verdict"], "violation")

    def test_yoy_base_in_sentence_decline_direction(self):
        """同比下降：声称值取负后再对账。"""
        r = self._scan("公司 2025 年营收 100 亿元，同比下降 20%，上年同期 125 亿元。")
        v = self._verdicts(r, "yoy_base_in_sentence")
        self.assertEqual(v[0]["verdict"], "consistent")
        self.assertAlmostEqual(v[0]["computed"], -20.0, places=2)

    def test_yoy_without_base_skipped(self):
        """句内无基数：跨句绑定归模型，不猜。"""
        r = self._scan("公司 2025 年营收同比增长 28%。")
        self.assertEqual(len(self._verdicts(r, "yoy_base_in_sentence")), 0)

    # ── 同句占比 ──
    def test_share_in_sentence_violation(self):
        r = self._scan("云计算业务收入 40 亿元，占公司总营收 200 亿元的 30%。")
        v = self._verdicts(r, "share_in_sentence")
        self.assertEqual(v[0]["verdict"], "violation")
        self.assertAlmostEqual(v[0]["computed"], 20.0, places=2)

    def test_share_in_sentence_consistent(self):
        r = self._scan("云计算业务收入 40 亿元，占公司总营收 200 亿元的 20%。")
        self.assertEqual(self._verdicts(r, "share_in_sentence")[0]["verdict"], "consistent")

    def test_share_without_denominator_skipped(self):
        r = self._scan("云计算业务收入 40 亿元，占公司总营收的 20%。")
        self.assertEqual(len(self._verdicts(r, "share_in_sentence")), 0)

    # ── 引用时序 ──
    def test_temporal_impossible(self):
        r = self._scan("根据公司《2025 年年度报告》，2026 年上半年实现营收 55 亿元。")
        v = self._verdicts(r, "temporal_citation")
        self.assertEqual(v[0]["verdict"], "violation")

    def test_temporal_covered(self):
        r = self._scan("根据公司《2025 年年度报告》，2025 年第四季度盈利环比改善。")
        v = self._verdicts(r, "temporal_citation")
        self.assertEqual(v[0]["verdict"], "consistent")

    def test_temporal_comparison_without_citation_verb_skipped(self):
        """'较2024年年报提升'是对比不是引用——无 据/根据/《》 不判。"""
        r = self._scan("2026 年一季度营收较 2024 年年报披露值大幅提升。")
        self.assertEqual(len(self._verdicts(r, "temporal_citation")), 0)

    # ── 预测事实化 ──
    def test_forecast_flagged(self):
        r = self._scan("预计 2026 年营收必将突破 500 亿元大关。")
        v = self._verdicts(r, "forecast_scan")
        self.assertEqual(v[0]["verdict"], "flagged")

    def test_forecast_clean_sentence_not_scanned(self):
        r = self._scan("2025 年公司经营现金流为正。")
        self.assertEqual(len(self._verdicts(r, "forecast_scan")), 0)

    # ── 汇总与下界对账 ──
    def test_summary_fields(self):
        text = ("| 分部 | 收入（亿元） | 占比 |\n|---|---|---|\n| A | 600 | 50% |\n"
                "| B | 400 | 40% |\n| 合计 | 1000 | 90% |\n"
                "公司 2025 年营收 100 亿元，上年同期 80 亿元，同比增长 28%。\n")
        r = self._scan(text)
        self.assertTrue(r["zero_token"])
        self.assertGreater(r["min_claim_floor"], 0)
        self.assertGreater(r["zero_token_verdicts"], 0)
        self.assertEqual(r["must_read_by_model"],
                         max(0, r["min_claim_floor"] - r["zero_token_verdicts"]))
        self.assertIn("table_sum", r["by_check"])

    def test_violations_listed_first(self):
        text = ("| 分部 | 收入（亿元） |\n|---|---|\n| A | 600 |\n| B | 400 |\n| 合计 | 1050 |\n"
                "公司 2025 年营收 100 亿元，上年同期 80 亿元，同比增长 28%。\n")
        r = self._scan(text)
        self.assertEqual(r["findings"][0]["verdict"], "violation")
        self.assertEqual(len(r["violations"]), 2)

    def test_cli_json(self):
        import contextlib
        import io
        import json as _json
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fc.main(["saturation_scan", "--text",
                            "| A | 1 |\n|---|---|\n| B | 2 |\n| C | 3 |\n| 合计 | 4 |"])
        self.assertEqual(code, 0)
        data = _json.loads(buf.getvalue())
        self.assertTrue(data["zero_token"])
        self.assertEqual(data["by_verdict"].get("violation"), 1)

    def test_throughput_large_doc(self):
        """20k 字符合成文档 ≤ 1 秒（零 token 吞吐的机械下界）。"""
        import time
        block = ("| 分部 | 收入（亿元） | 占比 |\n|---|---|---|\n| A | 600 | 60% |\n"
                 "| B | 400 | 40% |\n| 合计 | 1000 | 100% |\n"
                 "公司 2025 年营收 100 亿元，上年同期 80 亿元，同比增长 25%。经营稳定。\n")
        text = block * 120
        t0 = time.perf_counter()
        r = self._scan(text)
        dt = time.perf_counter() - t0
        self.assertLess(dt, 1.0)
        self.assertGreater(r["zero_token_verdicts"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
