"""数字事实验证器（Phase 4B.1）：绝对值核验（EXACT_VALUE_CHECK）。

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
    """绝对值核验：主张数值 vs 证据数值（单位统一换算，容差 0.5%）。

    - 证据含匹配数值 → SUPPORTED（calculation_detail 记录换算过程）；
    - 证据含数值但不匹配 → REFUTED（数值不一致）；
    - 证据无数值 → INSUFFICIENT_EVIDENCE。
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    claim_value, claim_unit = claim_value_of(claim)
    matched_evidence_ids = matched_evidence_ids or []

    if claim_value is None:
        return VerificationResult(
            claim_id, STATUS_UNABLE, confidence=0.3, verification_type=TYPE_EXACT_VALUE,
            matched_evidence_ids=matched_evidence_ids, reason="主张无数值，无法核验",
        )

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
            return VerificationResult(
                claim_id, STATUS_SUPPORTED, confidence=0.98, verification_type=TYPE_EXACT_VALUE,
                matched_evidence_ids=matched_evidence_ids[:1],
                calculation_detail=calc,
                reason=f"证据数值 {source_value:g}{source_unit} 换算后与主张 {claim_value:g}{claim_unit or ''} 一致",
            )

    # 证据有数字但无一匹配 → 数值错误
    if any(_evidence_has_numbers(t) for t in evidence_texts):
        return VerificationResult(
            claim_id, STATUS_REFUTED, confidence=0.8, verification_type=TYPE_EXACT_VALUE,
            matched_evidence_ids=matched_evidence_ids[:1],
            reason=f"证据中的数值与主张 {claim_value:g}{claim_unit or ''} 不一致",
        )
    return VerificationResult(
        claim_id, STATUS_INSUFFICIENT, confidence=0.4, verification_type=TYPE_EXACT_VALUE,
        matched_evidence_ids=matched_evidence_ids, reason="证据不含可核验数值",
    )
