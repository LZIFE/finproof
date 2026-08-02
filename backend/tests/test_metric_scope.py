"""Phase 23.8 重构指标和口径解析单元测试。"""

from __future__ import annotations

import pytest

from app.services.verification.metric_scope import (
    METRIC_ALIASES,
    METRIC_ALIASES_VERSION,
    ScopeContext,
    metrics_compatible,
    normalize_metric,
    parse_scope,
    query_expansion,
    scopes_compatible,
)


class TestMetricAliases:
    def test_version(self):
        assert METRIC_ALIASES_VERSION == "23.8.0"

    @pytest.mark.parametrize("std,alias", [
        ("revenue", "营业收入"),
        ("revenue", "营业总收入"),
        ("revenue", "revenue"),
        ("net_profit", "净利润"),
        ("net_profit_parent", "归母净利润"),
        ("net_profit_parent", "归属于母公司净利润"),
        ("net_profit_ex_recurring", "扣非归母净利润"),
        ("consolidated_net_profit", "合并净利润"),
        ("operating_cash_flow", "经营活动现金流净额"),
        ("gross_margin", "毛利率"),
        ("net_margin", "净利率"),
        ("eps", "每股收益"),
        ("eps_basic", "基本每股收益"),
        ("eps_diluted", "稀释每股收益"),
        ("overseas_revenue", "海外收入"),
        ("domestic_revenue", "国内收入"),
        ("segment_revenue", "分部收入"),
        ("accounts_receivable", "应收账款"),
        ("inventory", "存货"),
    ])
    def test_alias_present(self, std, alias):
        assert alias in METRIC_ALIASES[std]

    def test_at_least_20_metrics(self):
        assert len(METRIC_ALIASES) >= 20


class TestNormalizeMetric:
    def test_exact_cn(self):
        std, conf = normalize_metric("营业收入")
        assert std == "revenue"
        assert conf == 1.0

    def test_exact_en(self):
        std, conf = normalize_metric("revenue")
        assert std == "revenue"
        assert conf == 1.0

    def test_case_insensitive(self):
        std, _ = normalize_metric("REVENUE")
        assert std == "revenue"

    def test_contains_match(self):
        std, conf = normalize_metric("营业总收入 FY25")
        assert std == "revenue"
        assert conf >= 0.85

    def test_unknown_metric(self):
        std, conf = normalize_metric("未知指标")
        assert conf <= 0.3

    def test_empty(self):
        std, conf = normalize_metric("")
        assert std == ""
        assert conf == 0.0


class TestMetricsCompatible:
    def test_same_metric(self):
        ok, _ = metrics_compatible("营业收入", "revenue")
        assert ok

    def test_revenue_vs_net_profit(self):
        ok, reason = metrics_compatible("营业收入", "净利润")
        assert not ok
        assert "不兼容" in reason

    def test_net_profit_vs_parent_incompatible(self):
        # 净利润 vs 归母净利润 同前缀但不同口径，保守判不兼容
        ok, reason = metrics_compatible("净利润", "归母净利润")
        assert not ok
        assert "口径不同" in reason


class TestParseScope:
    def test_consolidated(self):
        sc = parse_scope("合并")
        assert sc.scope_type == "consolidated"
        assert sc.confidence >= 0.9

    def test_parent_attributable(self):
        sc = parse_scope("归母")
        assert sc.scope_type == "parent_attributable"

    def test_adjusted(self):
        sc = parse_scope("扣非")
        assert sc.scope_type == "adjusted"

    def test_empty_defaults_consolidated(self):
        sc = parse_scope("")
        assert sc.scope_type == "consolidated"

    def test_unknown(self):
        sc = parse_scope("xyz")
        assert sc.scope_type == "unknown"


class TestScopesCompatible:
    def test_same_scope(self):
        c = parse_scope("合并")
        e = parse_scope("合并")
        ok, _ = scopes_compatible(c, e)
        assert ok

    def test_consolidated_vs_parent_incompatible(self):
        c = parse_scope("合并")
        e = parse_scope("归母")
        ok, reason = scopes_compatible(c, e)
        assert not ok
        assert "不兼容" in reason

    def test_adjusted_vs_reported_incompatible(self):
        c = parse_scope("扣非")
        e = parse_scope("报告")
        ok, _ = scopes_compatible(c, e)
        assert not ok

    def test_unknown_compatible(self):
        c = parse_scope("未知")
        e = parse_scope("合并")
        ok, _ = scopes_compatible(c, e)
        assert ok


class TestQueryExpansion:
    def test_revenue_expansion(self):
        aliases = query_expansion("营业收入")
        assert "营业收入" in aliases
        assert "revenue" in aliases
        assert "营业总收入" in aliases

    def test_unknown_returns_self(self):
        aliases = query_expansion("未知指标")
        assert aliases == ["未知指标"]

    def test_empty(self):
        assert query_expansion("") == []


class TestScopeContextProperties:
    def test_is_consolidated(self):
        sc = parse_scope("合并")
        assert sc.is_consolidated

    def test_is_parent_attributable(self):
        sc = parse_scope("归母")
        assert sc.is_parent_attributable
        assert not sc.is_consolidated
