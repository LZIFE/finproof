"""Phase 23.25 Step 2/3 — Financial Fact Decision Bridge

当 evidence 含已验证 financial_fact 时，生成结构化 verdict 信号供 core_verify 融合。

融合逻辑（Step 3，不简单覆盖旧逻辑）：
- fact 完整且匹配（metric+value+period 全 True）→ verdict_hint=SUPPORTED
- fact metric 匹配但 value 冲突（value_match=False）→ verdict_hint=REFUTED
- fact 不完整 / 无 fact → verdict_hint=None（fallback 到 raw text 验证旧流程）

只读 fact_verification（Phase 23.24 已附加），不改 Gate 决策规则；
CORE Oracle（gold block 无 financial_fact）→ has_fact=False → 完全走旧路径。
"""
from __future__ import annotations


def fact_decision_signal(claim: dict, evidence_list: list[dict]) -> dict:
    """聚合 evidence 的 financial_fact 验证结果，返回 verdict 信号。

    返回：
        {
          "has_fact": bool,              # 是否有已验证的 financial_fact
          "verdict_hint": str | None,    # SUPPORTED / REFUTED / None(fallback)
          "reason": str,
          "fact_count": int,             # 已验证 fact 数量
          "matched_count": int,          # 全匹配 fact 数量
          "conflict_count": int,         # value 冲突 fact 数量
        }
    """
    has_fact = False
    matched_count = 0
    conflict_count = 0
    fact_count = 0
    sample_reason = ""

    for e in evidence_list:
        fv = e.get("fact_verification")
        if not fv:
            continue
        has_fact = True
        fact_count += 1
        if fv.get("verification_success"):
            matched_count += 1
            if not sample_reason:
                sample_reason = f"fact 核心字段匹配（evidence={e.get('evidence_id')}）"
        elif fv.get("metric_match") and fv.get("value_match") is False:
            conflict_count += 1
            if not sample_reason:
                sample_reason = (
                    f"fact metric 匹配但 value 冲突（evidence={e.get('evidence_id')}）"
                )

    # 决策
    if not has_fact:
        return {
            "has_fact": False, "verdict_hint": None, "reason": "无 financial_fact，走 raw text 验证",
            "fact_count": 0, "matched_count": 0, "conflict_count": 0,
        }
    if matched_count > 0:
        return {
            "has_fact": True, "verdict_hint": "SUPPORTED",
            "reason": f"{sample_reason or 'fact 匹配'}（{matched_count}/{fact_count}）",
            "fact_count": fact_count, "matched_count": matched_count, "conflict_count": conflict_count,
        }
    if conflict_count > 0:
        return {
            "has_fact": True, "verdict_hint": "REFUTED",
            "reason": f"{sample_reason or 'fact 数值冲突'}（{conflict_count}/{fact_count}）",
            "fact_count": fact_count, "matched_count": matched_count, "conflict_count": conflict_count,
        }
    return {
        "has_fact": True, "verdict_hint": None, "reason": "fact 存在但验证不完整，fallback 到 raw text",
        "fact_count": fact_count, "matched_count": 0, "conflict_count": 0,
    }
