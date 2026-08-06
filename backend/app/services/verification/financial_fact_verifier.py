"""Phase 23.30 Task 2 — Financial Fact Verifier

输入 Claim + Evidence.financial_fact，输出 FinancialFactVerificationResult。

输入：
    Claim: {metric, value, growth, period}
    financial_fact: {metric, current_value, previous_value, growth, period}

输出：
    FinancialFactVerificationResult = {
        metric_match, value_match, growth_match, period_match,
        confidence, decision
    }

规则：
- 全部核心字段匹配（metric + value + period）→ SUPPORTED
- metric 匹配但 value 冲突 → REFUTED
- 信息不足（缺 metric 或 value）→ UNKNOWN

Phase 23.31（period-aware）：
- 新增 period_compatibility_score：claim 2025FY vs fact [2025年度] → 1.0；
  claim 2025Q1/H1 vs fact FY → 严重降权（0.2/0.3）；fact periods 空 → 0。
- period 不匹配的 fact 不得直接 REFUTED：period mismatch → UNKNOWN（即使 value 冲突），
  避免期间错配造成错误 REFUTED。

复用 financial_fact_normalizer 的归一化（currency/unit/percentage/period）。
"""
from __future__ import annotations

import re

from app.services.verification.financial_fact_normalizer import (
    normalize_financial_fact,
)


def period_compatibility_score(claim_period, fact_periods) -> float:
    """期间兼容分（0-1）。

    - claim 年度（FY/年份）且 fact 含同年度 → 1.0
    - claim 半年度（H1）且 fact 含同年度 → 0.3（年度数据可佐证但非精确）
    - claim 季度（Q1-Q4）且 fact 含同年度 → 0.2（季度 vs 年度严重降权）
    - fact periods 缺失 → 0.0
    - claim 年份不在 fact periods → 0.0
    """
    if not claim_period or not fact_periods:
        return 0.0
    m = re.search(r"(19|20)\d{2}", str(claim_period))
    if not m:
        return 0.0
    year = m.group(0)
    # fact periods 含 claim 年份（如 "2025年" 或 "2025年度"）
    has_year = any(year in p for p in fact_periods)
    if not has_year:
        return 0.0
    cp = str(claim_period).upper()
    if "Q" in cp:
        return 0.2
    if "H" in cp:
        return 0.3
    return 1.0


# Phase 23.32 Task 2：financial_fact 质量评分（低质量 fact 不得参与 SUPPORTED/REFUTED）
# 比例/每股类指标（值应为无单位比值或 0-100 的百分比）
_RATIO_METRICS = {"basic_eps", "eps", "gross_margin", "roe", "net_margin"}
# 金额类单位
_AMOUNT_UNITS = ("千元", "万元", "百万元", "亿元", "元")
# 主表类型（高置信度来源）
_PRIMARY_TABLES = ("income_statement", "balance_sheet", "cash_flow", "equity_changes")
# 泛化指标名（低 metric confidence）
_GENERIC_METRICS = {"", "收入", "净利润", "收益", "资产", "负债"}
# 低质量阈值：quality_score < 该值 → 强制 UNKNOWN
QUALITY_THRESHOLD = 0.6


def financial_fact_quality_score(fact: dict) -> float:
    """财务事实质量分（0-1），四维置信度加权。

    - metric confidence（0.30）：metric_code 非空且非泛化
    - unit confidence（0.25）：比例类不带金额单位；金额类带单位
    - period confidence（0.25）：periods 非空且年份合理（无 >2030 异常）
    - source table confidence（0.20）：主表 > notes/MD 章节
    """
    if not fact:
        return 0.0

    # 1) metric confidence
    mc = str(fact.get("metric_code") or "").strip()
    metric_conf = 1.0 if mc and mc not in _GENERIC_METRICS else 0.0

    # 2) unit confidence
    unit = str(fact.get("unit") or "").strip()
    if mc in _RATIO_METRICS:
        # 比例/每股类：带金额单位 → 低置信（EPS=686429元 是错误）
        unit_conf = 0.2 if unit in _AMOUNT_UNITS else 1.0
    else:
        # 金额类：带金额单位 → 高置信
        unit_conf = 1.0 if unit in _AMOUNT_UNITS else 0.4

    # 3) period confidence
    periods = fact.get("periods") or []
    if not periods:
        period_conf = 0.2
    else:
        bad_year = any(
            any(("2062" in p or "2099" in p or "2090" in p) for p in [pp]) or
            (pp.isdigit() and int(pp) > 2030)
            for pp in periods
        )
        period_conf = 0.2 if bad_year else 1.0

    # 4) source table confidence
    table = str(fact.get("table_type") or "other").strip()
    table_conf = 1.0 if table in _PRIMARY_TABLES else 0.4

    score = (
        0.30 * metric_conf
        + 0.25 * unit_conf
        + 0.25 * period_conf
        + 0.20 * table_conf
    )
    return round(score, 4)


def verify_financial_fact_native(claim: dict, financial_fact: dict) -> dict:
    """原生事实验证：Claim vs financial_fact → FinancialFactVerificationResult。

    decision:
        SUPPORTED —— metric+value+period 全匹配（growth 作为加分，缺失不降级）
        REFUTED   —— metric+period 匹配但 value 明确冲突
        UNKNOWN   —— 信息不足 / period 不匹配（Phase 23.31：period mismatch 不 REFUTED）
    """
    if not financial_fact:
        return {
            "metric_match": None, "value_match": None, "growth_match": None,
            "period_match": None, "period_score": 0.0, "quality_score": 0.0,
            "confidence": 0.0, "decision": "UNKNOWN",
            "reason": "无 financial_fact",
        }

    # Phase 23.32 Task 2：低质量 fact 不得参与 SUPPORTED/REFUTED（强制 UNKNOWN）
    quality_score = financial_fact_quality_score(financial_fact)
    if quality_score < QUALITY_THRESHOLD:
        return {
            "metric_match": None, "value_match": None, "growth_match": None,
            "period_match": None, "period_score": 0.0,
            "quality_score": quality_score,
            "confidence": 0.0, "decision": "UNKNOWN",
            "reason": f"低质量 financial_fact（quality_score={quality_score} < {QUALITY_THRESHOLD}），不参与判定",
        }

    norm = normalize_financial_fact(financial_fact, claim)

    metric_match = norm.get("metric_match", False)
    # Phase 23.36 Task 3：value 判定改用 value comparator（单位归一 + 5% 容差 + metric strictness）
    from app.services.verification.financial_fact_value_comparator import compare_values

    vc = compare_values(claim, financial_fact)
    value_match = bool(vc.get("compatible"))
    prev_match = bool(norm.get("previous_value_match", {}).get("matched", False))
    growth_match = bool(norm.get("growth_match", {}).get("matched", False))
    # Phase 23.31：period 用兼容分判定（而非简单真/假）
    period_score = period_compatibility_score(claim.get("period"),
                                              financial_fact.get("periods") or [])
    period_match = period_score >= 0.8

    # 信息不足判定
    claim_value = claim.get("reported_value") or claim.get("value")
    fact_value = financial_fact.get("current_value")
    if not metric_match and claim_value is None and fact_value is None:
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "period_score": period_score,
            "confidence": 0.0, "decision": "UNKNOWN",
            "reason": "信息不足：claim 与 fact 均缺 metric/value",
        }

    # Phase 23.31：period 不匹配 → UNKNOWN（不得因 period 错配而 REFUTED/SUPPORTED）
    if period_score < 0.8:
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "period_score": period_score,
            "confidence": 0.3,
            "decision": "UNKNOWN",
            "reason": f"期间不兼容（claim={claim.get('period')} vs fact={financial_fact.get('periods')}，score={period_score}），不判定 REFUTED",
        }

    # 核心字段：metric + value + period
    core_ok = metric_match and value_match and period_match

    if core_ok:
        # growth 加分：有 growth 且匹配 → 置信度更高；缺失 growth 不降级
        conf = 0.80 + (0.10 if growth_match else 0.0) + (0.05 if prev_match else 0.0)
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "period_score": period_score,
            "confidence": round(min(conf, 0.95), 4),
            "decision": "SUPPORTED",
            "reason": f"核心字段匹配（metric+value+period）{'+growth' if growth_match else ''}",
        }

    if metric_match and not value_match:
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "period_score": period_score,
            "confidence": 0.75,
            "decision": "REFUTED",
            "reason": f"metric+period 匹配但 value 冲突（{norm.get('value_match', {}).get('reason', '')}）",
        }

    if not metric_match:
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "period_score": period_score,
            "confidence": 0.3,
            "decision": "UNKNOWN",
            "reason": "metric 不匹配，信息不足以判定",
        }

    return {
        "metric_match": metric_match, "value_match": value_match,
        "growth_match": growth_match, "period_match": period_match,
        "period_score": period_score,
        "confidence": 0.4,
        "decision": "UNKNOWN",
        "reason": "部分匹配但信息不足",
    }


def best_fact_verification(claim: dict, evidence_candidates: list[dict]) -> dict:
    """在候选 evidence 中找最优 fact 验证结果（decision 优先级 SUPPORTED > REFUTED > UNKNOWN）。

    用于 Task 3 双路径：fact 明确时优先，否则 fallback block 验证。
    """
    best = None
    priority = {"SUPPORTED": 2, "REFUTED": 1, "UNKNOWN": 0}
    for e in evidence_candidates:
        ff = e.get("financial_fact")
        if not ff:
            continue
        r = verify_financial_fact_native(claim, ff)
        if best is None or priority.get(r["decision"], 0) > priority.get(best["decision"], 0):
            best = {**r, "evidence_id": e.get("evidence_id") or e.get("block_id")}
    return best or {
        "metric_match": None, "value_match": None, "growth_match": None,
        "period_match": None, "confidence": 0.0, "decision": "UNKNOWN",
        "reason": "无 fact 证据", "evidence_id": None,
    }
