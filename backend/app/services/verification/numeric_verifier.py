"""数字事实验证器（Phase 4B.1）：绝对值核验（EXACT_VALUE_CHECK）。

[DEPRECATED] Phase 23.9 起主链改走 core_pipeline.core_verify（PRIMARY 路径）。
本模块保留为 LEGACY：仅单元测试 (tests/test_verification.py) 与历史诊断脚本
(scripts/phase23_5/6/7/8) 调用，不再被生产入口 verification_service._select_verifier 调用。
- 新代码请使用 app.services.verification.financial_value 抽数与 core_pipeline 核验。
- 禁止在生产入口（copilot/agent/demo/risk）调用本模块函数。

支持单位转换（千元/万元/元/亿元/列单位/页单位），保存 calculation_detail。
"""

import re

from app.services.evidence_retrieval.engine import (
    _block_value_hits,
    _clean_numbers,
    _COLUMN_UNIT_RE,
    iter_numbers,
    unit_to_yi,
    values_compatible,
)
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
    TYPE_EXACT_VALUE,
    VALUE_TOLERANCE,
    VerificationResult,
    claim_value_of,
)

_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def _find_matching_number(text: str, claim_value: float, claim_unit: str | None):
    """在证据文本中定位与主张数值匹配的数字，返回 (source_value, source_unit, converted_yi, 匹配说明)。"""
    # 1) 成对单位布局
    for value, unit, _cur, yi in iter_numbers(text):
        if values_compatible(claim_value, claim_unit, value, unit):
            return value, unit, yi, "成对单位匹配"
    # 2) 列头单位布局
    cleaned = _clean_numbers(text)
    m = _COLUMN_UNIT_RE.search(cleaned)
    if m:
        col_unit = m.group(0)
        for n in re.finditer(r"(?<![0-9])(\d+(?:\.\d+)?)(?![0-9])", cleaned):
            num = float(n.group(1))
            if _YEAR_RE.match(n.group(1)):
                continue
            if values_compatible(claim_value, claim_unit, num, col_unit):
                yi = num * unit_to_yi(col_unit) if unit_to_yi(col_unit) is not None else None
                return num, col_unit, yi, "列单位匹配"
    return None


def _evidence_has_numbers(text: str) -> bool:
    return any(_ for _ in iter_numbers(text)) or bool(re.search(r"\d", text or ""))


def verify_exact_value(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
) -> VerificationResult:
    """绝对值核验：主张数值 vs 证据数值（单位统一换算，容差 0.1%）。

    - 证据含匹配数值 → SUPPORTED（calculation_detail 记录换算过程，rule_id/calculated_value 结构化）；
    - 证据含数值但不匹配 → REFUTED（数值不一致）；
    - 证据无数值 → INSUFFICIENT_EVIDENCE；
    - 非数值类 claim（business_fact / forecast / scope / causality）→ 路由到 semantic_verifier，
      避免 UNABLE 过度弃权（Phase 23.7 修复）。

    Phase 23.7 修复：
    1. 容差从 0.5% 收紧到 0.1%（经 base.VALUE_TOLERANCE=0.001，v2.7.1 落地；此前文档声称收紧但代码仍为 0.005）；
    2. 非数值类 claim_type 路由到 semantic_verifier，消除过度弃权；
    3. VerificationResult 添加 rule_id / calculated_value 结构化字段（诊断脚本依赖）。
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    claim_value, claim_unit = claim_value_of(claim)
    claim_type = claim.get("claim_type", "?")
    matched_evidence_ids = matched_evidence_ids or []

    # Phase 23.7：非数值类路由到 semantic_verifier，避免过度弃权
    # 仅当 claim_type 明确为非数值类且 claim 有原文文本可做语义匹配时才路由；
    # 否则（claim_type 是数值类但 claim_value 为 None，或无原文）保持 UNABLE_TO_DETERMINE。
    _NON_NUMERIC_TYPES = {"business_fact", "forecast", "scope", "causality", "comparison"}
    claim_text = (claim.get("original_text") or claim.get("claim_text") or "").strip()
    if claim_type in _NON_NUMERIC_TYPES and claim_text:
        from app.services.verification.semantic_verifier import (
            verify_causal,
            verify_comparison,
            verify_semantic_support,
        )
        # 按 claim_type 选择语义核验器
        if claim_type == "causality":
            vr = verify_causal(claim, evidence_texts, matched_evidence_ids)
        elif claim_type == "comparison":
            vr = verify_comparison(claim, evidence_texts, matched_evidence_ids)
        else:
            # business_fact / forecast / scope / 缺数值类走 semantic_support
            vr = verify_semantic_support(claim, evidence_texts, matched_evidence_ids)
        # 补充结构化字段（诊断脚本依赖）
        vr.rule_id = f"semantic:{claim_type}"
        vr.calculated_value = None
        return vr

    if claim_value is None:
        # 数值类主张但无数值（或非数值类但无原文）：保持 UNABLE_TO_DETERMINE，不误判为 INSUFFICIENT
        vr = VerificationResult(
            claim_id, STATUS_UNABLE, confidence=0.3, verification_type=TYPE_EXACT_VALUE,
            matched_evidence_ids=matched_evidence_ids, reason="主张无数值，无法核验",
        )
        vr.rule_id = "numeric:no_claim_value"
        vr.calculated_value = None
        return vr

    for idx, text in enumerate(evidence_texts):
        found = _find_matching_number(text, claim_value, claim_unit)
        if found:
            source_value, source_unit, converted, how = found
            calc = {
                "source_value": source_value,
                "source_unit": source_unit,
                "converted_value": converted if converted is not None else source_value,
                "target_unit": claim_unit or "亿元",
                "tolerance": VALUE_TOLERANCE,
                "method": how,
            }
            vr = VerificationResult(
                claim_id, STATUS_SUPPORTED, confidence=0.98, verification_type=TYPE_EXACT_VALUE,
                matched_evidence_ids=matched_evidence_ids[:1],
                calculation_detail=calc,
                reason=f"证据数值 {source_value:g}{source_unit} 换算后与主张 {claim_value:g}{claim_unit or ''} 一致",
            )
            vr.rule_id = "numeric:exact_value"
            vr.calculated_value = converted if converted is not None else source_value
            return vr

    # 证据有数字但无一匹配 → 数值错误
    if any(_evidence_has_numbers(t) for t in evidence_texts):
        vr = VerificationResult(
            claim_id, STATUS_REFUTED, confidence=0.8, verification_type=TYPE_EXACT_VALUE,
            matched_evidence_ids=matched_evidence_ids[:1],
            reason=f"证据中的数值与主张 {claim_value:g}{claim_unit or ''} 不一致",
        )
        vr.rule_id = "numeric:mismatch"
        vr.calculated_value = None
        return vr
    vr = VerificationResult(
        claim_id, STATUS_INSUFFICIENT, confidence=0.4, verification_type=TYPE_EXACT_VALUE,
        matched_evidence_ids=matched_evidence_ids, reason="证据不含可核验数值",
    )
    vr.rule_id = "numeric:no_numbers"
    vr.calculated_value = None
    return vr
