"""增长率验证器（Phase 4B.1）：同比/环比增长率核验（GROWTH_RATE_CHECK）。

[DEPRECATED] Phase 23.9 起主链改走 core_pipeline._core_verify_growth（PRIMARY 路径，
使用 FinancialValue/PeriodContext 模块）。本模块保留为 LEGACY：仅单元测试与历史诊断脚本
调用，禁止生产入口（copilot/agent/demo/risk）调用。

原始职责（Phase 4B.1）：GROWTH_RATE_CHECK——同比/环比增长率核验：
从证据中提取当前期与上年同期数值，计算 (cur − prev) / prev × 100%，
与主张增长率比较（允许 ±0.5 个百分点误差）。
"""

import re

from app.services.evidence_retrieval.engine import _clean_numbers, _COLUMN_UNIT_RE, iter_numbers, unit_to_yi
from app.services.verification.base import (
    GROWTH_TOLERANCE_PP,
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
    TYPE_GROWTH_RATE,
    VerificationResult,
    claim_value_of,
)

_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def _claim_metric_tokens(claim: dict) -> set[str]:
    """按主张指标代码的别名族提取指标词（用于证据块优先排序）。

    支持金标准格式（metric 字段存代码）与系统格式（metric_code）；
    yoy_growth_* 前缀剥除后取基础指标族（net_profit 与 net_profit_attributable 合并防漏）。
    """
    from app.services.evidence_retrieval.engine import _METRIC_ALIASES

    metric = str(claim.get("metric") or "")
    code = claim.get("metric_code")
    if not code and not re.search(r"[\u4e00-\u9fff]", metric):
        code = metric  # 金标准：metric 字段存代码
    base = str(code or "")
    for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
        if base.startswith(pfx):
            base = base[len(pfx):]
            break
    tokens: set[str] = set()
    if re.search(r"[\u4e00-\u9fff]", metric):
        tokens.add(metric)
    families = [base]
    if base == "net_profit":
        families.append("net_profit_attributable")
    if base == "revenue":
        families.append("total_operating_revenue")
    for f in families:
        tokens |= _METRIC_ALIASES.get(f, set())
    return {t for t in tokens if t}


def _growth_evidence_order(evidence: list[dict], claim: dict) -> list[dict]:
    """增长率证据优先排序：指标族匹配 + 证据文档期间与主张期间一致。

    防止用子期间（如 Q1）的数据对验证全年（FY）增长率。
    """
    from app.services.evidence_retrieval.engine import period_type_of

    tokens = _claim_metric_tokens(claim)
    claim_ptype = period_type_of(claim.get("period"))

    def key(e):
        text = e.get("text") or ""
        metric_ok = 0 if (tokens and any(t and t in text for t in tokens)) else 1
        ev_ptype = period_type_of(e.get("doc_period"))
        period_ok = 0 if (claim_ptype and ev_ptype == claim_ptype) else 1
        return (period_ok, metric_ok)

    return sorted(evidence, key=key)


def _extract_current_prev(text: str):
    """从证据文本提取当前期与上年同期两个数值（同单位，跳过 4 位年份）。

    返回 (cur, prev, unit, cur_yi, prev_yi) 或 None。
    """
    cleaned = _clean_numbers(text or "")
    m = _COLUMN_UNIT_RE.search(cleaned)
    unit = m.group(0) if m else None
    nums = []
    for n in re.finditer(r"(?<![0-9])(\d+(?:\.\d+)?)(?![0-9])", cleaned):
        token = n.group(1)
        if _YEAR_RE.match(token):
            continue
        nums.append(float(token))
        if len(nums) >= 2:
            break
    if len(nums) < 2:
        return None
    cur, prev = nums[0], nums[1]
    yi = unit_to_yi(unit)
    cur_yi = cur * yi if yi is not None else None
    prev_yi = prev * yi if yi is not None else None
    return cur, prev, unit, cur_yi, prev_yi


def _is_growth_claim(claim: dict) -> bool:
    """主张是否为增长率类型（claim_type 或 metric_code 或 claim_nature 判定）。"""
    ct = (claim.get("claim_type") or "").upper()
    code = (claim.get("metric_code") or "").lower()
    nature = (claim.get("claim_nature") or "").upper()
    return (
        "GROWTH" in ct
        or "growth" in code
        or "yoy" in code
        or "qoq" in code
        or nature == "CALCULATED_FACT"
    )


def verify_growth_rate(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
    evidence_ordered: list[dict] | None = None,
) -> VerificationResult:
    """增长率核验：主张增长率 vs 证据计算的 (cur−prev)/prev。

    - 计算值在主张值 ±0.5pp 内 → SUPPORTED（含 calculation_detail）；
    - 计算值明显偏离 → REFUTED；
    - 证据缺少当前期/上年同期数值 → INSUFFICIENT_EVIDENCE。
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    claimed_growth, _unit = claim_value_of(claim)
    matched_evidence_ids = matched_evidence_ids or []

    if claimed_growth is None:
        return VerificationResult(
            claim_id, STATUS_UNABLE, confidence=0.3, verification_type=TYPE_GROWTH_RATE,
            matched_evidence_ids=matched_evidence_ids, reason="主张无增长率数值",
        )

    # 优先使用指标行证据（evidence_ordered 已按指标词排序）
    ordered_texts = [e["text"] for e in evidence_ordered] if evidence_ordered else evidence_texts
    for idx, text in enumerate(ordered_texts):
        pair = _extract_current_prev(text)
        if not pair:
            continue
        cur, prev, unit, cur_yi, prev_yi = pair
        if prev == 0:
            continue
        # 换算到亿元（若单位可换算）后计算；否则按原值计算
        a, b = (cur_yi, prev_yi) if (cur_yi is not None and prev_yi is not None) else (cur, prev)
        calculated = (a - b) / b * 100.0
        calc = {
            "current_value": a,
            "previous_value": b,
            "source_unit": unit,
            "calculated_growth_pp": round(calculated, 2),
            "claimed_growth_pp": claimed_growth,
            "tolerance_pp": GROWTH_TOLERANCE_PP,
        }
        if abs(calculated - claimed_growth) <= GROWTH_TOLERANCE_PP:
            return VerificationResult(
                claim_id, STATUS_SUPPORTED, confidence=0.95, verification_type=TYPE_GROWTH_RATE,
                matched_evidence_ids=matched_evidence_ids[:1],
                calculation_detail=calc,
                reason=f"计算增长率 {calculated:.2f}% 与主张 {claimed_growth:g}% 一致（±{GROWTH_TOLERANCE_PP}pp）",
            )
        return VerificationResult(
            claim_id, STATUS_REFUTED, confidence=0.9, verification_type=TYPE_GROWTH_RATE,
            matched_evidence_ids=matched_evidence_ids[:1],
            calculation_detail=calc,
            reason=f"计算增长率 {calculated:.2f}% 与主张 {claimed_growth:g}% 不符（差 {abs(calculated - claimed_growth):.2f}pp）",
        )
    return VerificationResult(
        claim_id, STATUS_INSUFFICIENT, confidence=0.4, verification_type=TYPE_GROWTH_RATE,
        matched_evidence_ids=matched_evidence_ids, reason="证据缺少当前期与上年同期数值，无法计算增长率",
    )
