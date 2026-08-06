"""Phase 23.24 Task 2 — Financial Fact Verification Path

当 evidence 含 financial_fact 时，执行事实级验证（metric/value/previous_value/growth/period），
生成 fact_verification 结果附加到证据元素。

原则：
- Fact evidence 补充 raw block 验证，不替代（Task 3）
- 不改 verdict policy / Evidence Gate 决策规则（本模块只生成事实匹配诊断，不改变 Gate 判定）
"""
from __future__ import annotations

from app.services.verification.financial_fact_normalizer import normalize_financial_fact

# fact 验证判定阈值（与归一化模块一致）
_VALUE_MATCH_TOLERANCE = 0.01
_GROWTH_MATCH_TOLERANCE = 1.0


def verify_financial_fact(claim: dict, evidence: dict) -> dict:
    """对单条 evidence 的 financial_fact 执行事实级验证。

    输入 evidence 需含 financial_fact（Phase 23.23 已附加）。
    返回：
        {
          "has_financial_fact": bool,
          "fact_verification": {
              "metric_match", "value_match", "previous_value_match",
              "growth_match", "period_match", "all_core_fields_match",
              "verification_success": bool
          } | None
        }
    """
    fact = evidence.get("financial_fact")
    if not fact:
        return {"has_financial_fact": False, "fact_verification": None}

    norm = normalize_financial_fact(fact, claim)

    # 核心字段判定：metric + value + period（最低门槛）
    core_ok = (
        norm.get("metric_match", False)
        and norm.get("value_match", {}).get("matched", False)
        and norm.get("period_match", {}).get("matched", False)
    )
    # 全部字段判定（metric/value/prev/growth/period；prev/growth 缺失时放宽）
    checks = {
        "metric": norm.get("metric_match", False),
        "value": norm.get("value_match", {}).get("matched", False),
        "previous_value": norm.get("previous_value_match", {}).get("matched", False),
        "growth": norm.get("growth_match", {}).get("matched", False),
        "period": norm.get("period_match", {}).get("matched", False),
    }
    all_ok = all(checks.values())

    return {
        "has_financial_fact": True,
        "fact_verification": {
            "metric_match": checks["metric"],
            "value_match": checks["value"],
            "previous_value_match": checks["previous_value"],
            "growth_match": checks["growth"],
            "period_match": checks["period"],
            "all_core_fields_match": core_ok,
            "all_fields_match": all_ok,
            "verification_success": core_ok,
            "details": {
                "value": norm.get("value_match", {}),
                "previous_value": norm.get("previous_value_match", {}),
                "growth": norm.get("growth_match", {}),
                "period": norm.get("period_match", {}),
                "currency": norm.get("currency", ""),
            },
        },
    }


def attach_fact_verifications(claim: dict, evidence_candidates: list[dict]) -> list[dict]:
    """批量：为含 financial_fact 的证据附加 fact_verification（不删除任何候选）。"""
    for e in evidence_candidates:
        r = verify_financial_fact(claim, e)
        e["has_financial_fact"] = r["has_financial_fact"]
        e["fact_verification"] = r["fact_verification"]
    return evidence_candidates
