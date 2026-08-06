"""Phase 23.24 Task 1 — Financial Fact Normalization

为 FinancialEvidenceObject.financial_fact 提供财务事实归一化：
- currency conversion（货币换算：CNY/USD，按单位推断）
- unit conversion（单位换算：亿元/万元/千元/元，统一到元）
- percentage comparison（百分比/增长率比较）
- period matching（期间匹配：claim period 年份 ∈ fact periods）

复用 verification.financial_value 的 UNIT_SCALE / values_match 基础设施，
新增对 financial_fact schema 的归一化封装。
"""
from __future__ import annotations

import re

from app.services.verification.financial_value import UNIT_SCALE, values_match

# 货币：英文单位默认 USD，中文默认 CNY（与 financial_value 一致）
_USD_UNITS = {"million", "billion", "mb", "b"}


def currency_of(unit: str | None) -> str:
    """由单位推断货币（million/billion → USD，中文单位 → CNY）。"""
    u = (unit or "").strip().lower()
    if u in _USD_UNITS:
        return "USD"
    return "CNY"


def normalize_value(value: float | None, unit: str | None) -> float | None:
    """归一化数值到元（currency/unit conversion）。"""
    if value is None:
        return None
    scale = UNIT_SCALE.get((unit or "").strip(), 1.0)
    return value * scale


def percentage_match(claim_growth: float | None, fact_growth: float | None, tolerance: float = 1.0) -> tuple[bool, str]:
    """增长率比较（百分比，绝对容差默认 1 个百分点）。"""
    if claim_growth is None or fact_growth is None:
        return False, "缺少增长率"
    if abs(claim_growth - fact_growth) <= tolerance:
        return True, f"增长率匹配（claim={claim_growth}%, fact={fact_growth}%）"
    return False, f"增长率不匹配（claim={claim_growth}%, fact={fact_growth}%）"


def period_match(claim_period: str | None, fact_periods: list[str]) -> tuple[bool, str]:
    """期间匹配：claim period 年份是否在 fact periods 中。"""
    if not claim_period or not fact_periods:
        return False, "缺少期间"
    m = re.search(r"(19|20)\d{2}", str(claim_period))
    if not m:
        return False, f"claim period 无年份（{claim_period}）"
    year = f"{m.group(0)}年"
    if any(year == p or year in p for p in fact_periods):
        return True, f"期间匹配（{year} ∈ {fact_periods}）"
    return False, f"期间不匹配（{year} ∉ {fact_periods}）"


def normalize_financial_fact(fact: dict, claim: dict) -> dict:
    """对单个 financial_fact 做归一化 + 与 claim 的匹配评估。

    返回：
        {
          "fact": 原 financial_fact（含 source_blocks）
          "metric_match": bool,
          "value_match": {"matched": bool, "claim_yuan": float, "fact_yuan": float, "reason": str},
          "previous_value_match": {...},
          "growth_match": {"matched": bool, "reason": str},
          "period_match": {"matched": bool, "reason": str},
          "currency": str,
        }
    """
    claim_metric_code = str(claim.get("metric_code") or "").strip() or str(claim.get("metric") or "").strip()
    fact_metric_code = str(fact.get("metric_code") or "").strip()
    # metric 家族匹配（revenue≈total_operating_revenue）
    metric_match = _metric_family_match(claim_metric_code, fact_metric_code)

    claim_value = claim.get("reported_value") or claim.get("value")
    if isinstance(claim_value, str):
        try:
            claim_value = float(claim_value.replace(",", ""))
        except ValueError:
            claim_value = None
    claim_unit = str(claim.get("unit") or "").strip()
    fact_value = fact.get("current_value")
    fact_unit = str(fact.get("unit") or "").strip()

    value_match = {"matched": False, "claim_yuan": None, "fact_yuan": None, "reason": ""}
    if claim_value is not None and fact_value is not None:
        claim_yuan = claim_value * UNIT_SCALE.get(claim_unit, 1.0)
        fact_yuan = fact_value * UNIT_SCALE.get(fact_unit or "千元", 1.0)
        ok, reason = values_match(claim_value, claim_unit,
                                  _make_fv(fact_value, fact_unit), tolerance=0.01)
        value_match = {"matched": ok, "claim_yuan": round(claim_yuan, 2),
                       "fact_yuan": round(fact_yuan, 2), "reason": reason}

    claim_prev = _claim_previous_value(claim)
    fact_prev = fact.get("previous_value")
    prev_match = {"matched": False, "reason": "缺少上一期数值"}
    if claim_prev is not None and fact_prev is not None:
        ok, reason = values_match(claim_prev, claim_unit,
                                  _make_fv(fact_prev, fact_unit or "千元"), tolerance=0.01)
        prev_match = {"matched": ok, "reason": reason}

    growth_match = {"matched": False, "reason": ""}
    claim_growth = _claim_growth(claim)
    if claim_growth is not None or fact.get("growth") is not None:
        ok, reason = percentage_match(claim_growth, fact.get("growth"))
        growth_match = {"matched": ok, "reason": reason}

    p_match = period_match(claim.get("period"), fact.get("periods") or [])
    period_result = {"matched": p_match[0], "reason": p_match[1]}

    return {
        "fact": fact,
        "currency": currency_of(fact_unit),
        "metric_match": metric_match,
        "value_match": value_match,
        "previous_value_match": prev_match,
        "growth_match": growth_match,
        "period_match": period_result,
    }


def _metric_family_match(claim_code: str, fact_code: str) -> bool:
    """指标家族匹配（revenue≈total_operating_revenue；净利润家族严格隔离）。"""
    if not claim_code or not fact_code:
        return False
    c = claim_code
    for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
        if c.startswith(pfx):
            c = c[len(pfx):]
            break
    if c == fact_code:
        return True
    family = {
        "revenue": {"revenue", "total_operating_revenue"},
        "total_operating_revenue": {"revenue", "total_operating_revenue"},
    }
    return fact_code in family.get(c, set())


def _make_fv(value: float, unit: str):
    """构造轻量 FinancialValue（values_match 需要 absolute_value_in_yuan）。"""
    from app.services.verification.financial_value import FinancialValue

    return FinancialValue(
        raw_text=str(value), normalized_value=value,
        scale=UNIT_SCALE.get((unit or "").strip(), 1.0),
        currency=currency_of(unit), unit=unit or "", percentage_type="",
        sign="positive", metric="", period="", source_span=(0, 0), extraction_confidence=1.0,
    )


def _claim_previous_value(claim: dict) -> float | None:
    """从 claim 提取上一期数值（若 claim 有 comparison/上期字段）。"""
    for k in ("previous_value", "comparison_value", "prior_value"):
        v = claim.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", ""))
            except ValueError:
                continue
    return None


def _claim_growth(claim: dict) -> float | None:
    """从 claim 提取增长率（若 claim 已含 growth 字段或文本带百分比）。"""
    v = claim.get("growth") or claim.get("growth_rate")
    if isinstance(v, (int, float)):
        return float(v)
    text = str(claim.get("original_text") or claim.get("claim_text") or "")
    m = re.search(r"同比(?:增长|下降|增减)?\s*([\d.]+)%", text)
    if m:
        return float(m.group(1))
    return None
