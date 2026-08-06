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

复用 financial_fact_normalizer 的归一化（currency/unit/percentage/period）。
"""
from __future__ import annotations

import re

from app.services.verification.financial_fact_normalizer import (
    normalize_financial_fact,
)


def verify_financial_fact_native(claim: dict, financial_fact: dict) -> dict:
    """原生事实验证：Claim vs financial_fact → FinancialFactVerificationResult。

    decision:
        SUPPORTED —— metric+value+period 全匹配（growth 作为加分，缺失不降级）
        REFUTED   —— metric 匹配但 value 冲突（或 value 明确冲突）
        UNKNOWN   —— 信息不足（claim/fact 缺 metric 或 value）
    """
    if not financial_fact:
        return {
            "metric_match": None, "value_match": None, "growth_match": None,
            "period_match": None, "confidence": 0.0, "decision": "UNKNOWN",
            "reason": "无 financial_fact",
        }

    norm = normalize_financial_fact(financial_fact, claim)

    metric_match = norm.get("metric_match", False)
    value_match = bool(norm.get("value_match", {}).get("matched", False))
    prev_match = bool(norm.get("previous_value_match", {}).get("matched", False))
    growth_match = bool(norm.get("growth_match", {}).get("matched", False))
    period_match = bool(norm.get("period_match", {}).get("matched", False))

    # 信息不足判定
    claim_value = claim.get("reported_value") or claim.get("value")
    fact_value = financial_fact.get("current_value")
    if not metric_match and claim_value is None and fact_value is None:
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "confidence": 0.0, "decision": "UNKNOWN",
            "reason": "信息不足：claim 与 fact 均缺 metric/value",
        }

    # 核心字段：metric + value + period
    core_ok = metric_match and value_match and period_match

    if core_ok:
        # growth 加分：有 growth 且匹配 → 置信度更高；缺失 growth 不降级
        conf = 0.80 + (0.10 if growth_match else 0.0) + (0.05 if prev_match else 0.0)
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "confidence": round(min(conf, 0.95), 4),
            "decision": "SUPPORTED",
            "reason": f"核心字段匹配（metric+value+period）{'+growth' if growth_match else ''}",
        }

    if metric_match and not value_match:
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "confidence": 0.75,
            "decision": "REFUTED",
            "reason": f"metric 匹配但 value 冲突（{norm.get('value_match', {}).get('reason', '')}）",
        }

    if not metric_match:
        return {
            "metric_match": metric_match, "value_match": value_match,
            "growth_match": growth_match, "period_match": period_match,
            "confidence": 0.3,
            "decision": "UNKNOWN",
            "reason": "metric 不匹配，信息不足以判定",
        }

    return {
        "metric_match": metric_match, "value_match": value_match,
        "growth_match": growth_match, "period_match": period_match,
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
