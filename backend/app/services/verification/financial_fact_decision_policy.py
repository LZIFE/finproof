"""Phase 23.33 Task 2 — Financial Fact Decision Authority Policy

规则（决策权威层）：
- 仅当 financial_fact_quality_score >= 0.8 AND metric match AND value match AND period match
  → fact verdict 优先（Decision Authority 触发）
- SUPPORTED：直接支持（quality + 全字段匹配）
- REFUTED：仅当 same metric + same period + value conflict（严格条件，避免误 REFUTED）
- 否则 UNKNOWN（fallback 到 block verification）

设计：与 Phase 23.30/23.31/23.32 的 verifier 相比，本策略更严格：
1. quality 门槛提高到 0.8（仅高质量 fact 有权威）
2. REFUTED 必须同 metric + 同 period + value 冲突（phase 23.31 已防 period 错配 REFUTED，
   本层再要求同 metric）
"""
from __future__ import annotations

from app.services.verification.financial_fact_verifier import (
    QUALITY_THRESHOLD,
    financial_fact_quality_score,
    period_compatibility_score,
)
from app.services.verification.financial_fact_normalizer import normalize_financial_fact

# 权威层 quality 门槛（比 verifier 的 0.6 更严，仅高质量 fact 有决策权威）
AUTHORITY_QUALITY_THRESHOLD = 0.8


def fact_decision_authority(claim: dict, financial_fact: dict) -> dict:
    """Financial Fact 决策权威层：返回权威判定结果。

    返回：
        {
          "authority_triggered": bool,   # 是否触发 fact 权威（quality>=0.8 + metric/value/period 全匹配）
          "decision": "SUPPORTED" | "REFUTED" | "UNKNOWN",
          "quality_score": float,
          "metric_match": bool,
          "value_match": bool,
          "period_match": bool,
          "confidence": float,
          "reason": str,
        }
    """
    if not financial_fact:
        return {
            "authority_triggered": False, "decision": "UNKNOWN", "quality_score": 0.0,
            "metric_match": None, "value_match": None, "period_match": None,
            "confidence": 0.0, "reason": "无 financial_fact",
        }

    quality_score = financial_fact_quality_score(financial_fact)
    norm = normalize_financial_fact(financial_fact, claim)
    metric_match = norm.get("metric_match", False)
    value_match = bool(norm.get("value_match", {}).get("matched", False))
    period_score = period_compatibility_score(claim.get("period"),
                                              financial_fact.get("periods") or [])
    period_match = period_score >= 0.8

    # 权威触发条件：quality >= 0.8 + metric + value + period 全匹配
    if quality_score < AUTHORITY_QUALITY_THRESHOLD:
        return {
            "authority_triggered": False, "decision": "UNKNOWN",
            "quality_score": quality_score, "metric_match": metric_match,
            "value_match": value_match, "period_match": period_match,
            "confidence": 0.0,
            "reason": f"quality_score={quality_score} < {AUTHORITY_QUALITY_THRESHOLD}，无决策权威",
        }

    if metric_match and value_match and period_match:
        return {
            "authority_triggered": True, "decision": "SUPPORTED",
            "quality_score": quality_score, "metric_match": metric_match,
            "value_match": value_match, "period_match": period_match,
            "confidence": round(min(0.85 + 0.05 * (quality_score - 0.8) / 0.2, 0.95), 4),
            "reason": f"fact 权威：quality={quality_score} + metric/value/period 全匹配",
        }

    # REFUTED 严格条件：同 metric + 同 period + value 冲突
    if metric_match and period_match and not value_match:
        return {
            "authority_triggered": True, "decision": "REFUTED",
            "quality_score": quality_score, "metric_match": metric_match,
            "value_match": value_match, "period_match": period_match,
            "confidence": 0.8,
            "reason": "fact 权威：同 metric + 同 period 但 value 冲突",
        }

    return {
        "authority_triggered": False, "decision": "UNKNOWN",
        "quality_score": quality_score, "metric_match": metric_match,
        "value_match": value_match, "period_match": period_match,
        "confidence": 0.3,
        "reason": "部分匹配不足，无法触发 fact 权威",
    }


def best_fact_authority(claim: dict, evidence_candidates: list[dict]) -> dict:
    """在候选 evidence 中找最优 fact 权威判定（SUPPORTED > REFUTED > UNKNOWN）。

    用于 Task 3 Decision Fusion：authority_triggered 时 fact 优先，否则 fallback。
    """
    best = None
    priority = {"SUPPORTED": 2, "REFUTED": 1, "UNKNOWN": 0}
    for e in evidence_candidates:
        ff = e.get("financial_fact")
        if not ff:
            continue
        r = fact_decision_authority(claim, ff)
        if r["authority_triggered"] and (
            best is None or priority.get(r["decision"], 0) > priority.get(best["decision"], 0)
        ):
            best = {**r, "evidence_id": e.get("evidence_id") or e.get("block_id")}
    return best or {
        "authority_triggered": False, "decision": "UNKNOWN", "quality_score": 0.0,
        "metric_match": None, "value_match": None, "period_match": None,
        "confidence": 0.0, "reason": "无权威 fact", "evidence_id": None,
    }
