"""规则工具单元测试（Phase 3）：数字/百分比/单位/币种/期间/同比环比/类型/风险。"""

import pytest

from app.services.claims.normalizers import (
    detect_claim_nature,
    detect_claim_type,
    detect_comparison,
    find_metric,
    grade_risk,
    parse_number,
    parse_percent,
    parse_period,
    requires_calculation,
)


# ---------- 指标词典 ----------

def test_find_metric_longest_match():
    assert find_metric("营业收入") == ("营业收入", "revenue")
    assert find_metric("归属于上市公司股东的净利润") == (
        "归属于上市公司股东的净利润", "net_profit_attributable",
    )
    assert find_metric("毛利率") == ("毛利率", "gross_margin")
    assert find_metric("同比增长") == ("同比增长", "growth_rate")


def test_find_metric_none():
    assert find_metric("公司是一家优秀的企业") is None


# ---------- 数字/单位/币种 ----------

def test_parse_number_with_unit():
    n = parse_number("实现营业收入4564.52亿元")
    assert n.value == 4564.52
    assert n.unit == "亿元"
    assert n.operator == "EQUAL"


def test_parse_number_percent():
    n = parse_number("同比增长12.11%")
    assert n.value == 12.11
    assert n.unit == "PERCENT"


def test_parse_number_skips_year():
    # "2025年" 不应被当作数值（数字+单位成对匹配）
    assert parse_number("公司2025年实现营业收入4564.52亿元").value == 4564.52


def test_parse_number_operator():
    assert parse_number("超过1200亿元").operator == "GREATER_THAN"
    assert parse_number("不低于15%").operator == "GREATER_THAN_OR_EQUAL"
    assert parse_number("低于10亿元").operator == "LESS_THAN"


def test_parse_number_currency():
    assert parse_number("上半年收入60亿港元").currency == "HKD"
    assert parse_number("收入60亿美元").currency == "USD"
    assert parse_number("收入60亿元").currency == "CNY"


def test_parse_percent():
    assert parse_percent("同比增长15.7%") == 15.7
    assert parse_percent("毛利率26.4%") == 26.4
    assert parse_percent("无百分比") is None


# ---------- 期间标准化 ----------

def test_parse_period_quarter():
    assert parse_period("2025年第一季度", 2025).period == "2025Q1"
    assert parse_period("第二季度", 2025).period == "2025Q2"
    assert parse_period("2025Q3", 2025).period == "2025Q3"


def test_parse_period_half_year():
    assert parse_period("2025年上半年", 2025).period == "2025H1"
    assert parse_period("2025年H1", 2025).period == "2025H1"


def test_parse_period_fiscal_year():
    assert parse_period("2025年度", 2025).period == "2025FY"
    assert parse_period("2025年", 2025).period == "2025"


def test_parse_period_h1_before_quarter_mention():
    # "较一季度有所回落" 不应把 H1 句误判为 Q1
    p = parse_period("2025年上半年，公司营业总收入2523.31亿元，增速较一季度有所回落", 2025)
    assert p.period == "2025H1"


def test_parse_period_future():
    p = parse_period("展望2026年，公司营业收入将突破5000亿元", 2025)
    assert p.period == "2026FY"
    assert p.period_type == "FUTURE_PERIOD"


# ---------- 同比/环比 ----------

def test_detect_comparison_yoy():
    ct, cp = detect_comparison("收入同比增长15%", "2025H1", 2025)
    assert ct == "YEAR_OVER_YEAR"
    assert cp == "2024H1"


def test_detect_comparison_qoq():
    ct, _ = detect_comparison("环比增长10%", "2025Q2", 2025)
    assert ct == "QUARTER_OVER_QUARTER"


def test_detect_comparison_none():
    ct, _ = detect_comparison("公司收入为100亿元", "2025", 2025)
    assert ct == "NONE"


# ---------- 类型/性质 ----------

def test_claim_type_growth_rate():
    t = detect_claim_type("公司2025年收入同比增长12.11%", parse_number("同比增长12.11%"), "revenue", "YEAR_OVER_YEAR")
    assert t == "GROWTH_RATE"


def test_claim_type_causal():
    assert detect_claim_type("利润增长主要由海外市场扩张推动", None, "profit", "NONE") == "CAUSAL_CLAIM"


def test_claim_type_forecast():
    assert detect_claim_type("公司营业收入将突破5000亿元", parse_number("将突破5000亿元"), "revenue", "NONE") == "FORECAST"


def test_claim_type_business_fact_strategy():
    # "持续深化……战略" 不应被误判为 TREND
    assert detect_claim_type("公司持续深化海外OBM优先战略", None, None, "NONE") == "BUSINESS_FACT"


def test_claim_type_trend():
    assert detect_claim_type("公司经营现金流持续改善", None, "cash_flow", "NONE") == "TREND"


def test_claim_nature_mapping():
    assert detect_claim_nature("同比增长15%", "GROWTH_RATE") == "CALCULATED_FACT"
    assert detect_claim_nature("利润主要由海外推动", "CAUSAL_CLAIM") == "CAUSAL_INTERPRETATION"
    assert detect_claim_nature("公司将突破5000亿", "FORECAST") == "FORECAST"


def test_requires_calculation():
    assert requires_calculation("GROWTH_RATE", "同比增长15%") is True
    assert requires_calculation("ABSOLUTE_FINANCIAL_VALUE", "收入100亿元") is False


# ---------- 风险分级 ----------

def test_risk_high_for_core_metrics():
    level, _ = grade_risk("公司2025年实现营业收入4564.52亿元", "ABSOLUTE_FINANCIAL_VALUE", "revenue")
    assert level == "HIGH"


def test_risk_critical_keywords():
    level, _ = grade_risk("公司已完成对某企业的收购", "BUSINESS_FACT", None)
    assert level == "CRITICAL"


def test_risk_medium_comparison():
    level, _ = grade_risk("机器人业务毛利率高于行业平均20个百分点", "COMPARISON", "robot_business")
    assert level == "MEDIUM"


def test_risk_low_background():
    level, _ = grade_risk("公司是一家优秀的公司", "BUSINESS_FACT", None)
    assert level == "LOW"
