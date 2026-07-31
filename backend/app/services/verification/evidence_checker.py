"""证据充分性与多证据组合检查器（Phase 4B.1）。

- verify_semantic：无数字语义主张——证据含相关业务描述才可判断，
  仅收入数字/无业务说明 → INSUFFICIENT_EVIDENCE（不强制判断）；
- verify_multi_evidence：多证据组合——主张需多个证据维度（数据+同比+业务说明）。
"""

from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_SUPPORTED,
    TYPE_MULTI_EVIDENCE,
    TYPE_SEMANTIC,
    VerificationResult,
    claim_text_of,
)

# 语义主张的业务描述关键词（证据覆盖度判断）
_BUSINESS_KEYWORDS = (
    "战略", "业务", "增长动力", "核心引擎", "贡献", "占比", "布局", "市场份额",
    "驱动", "推动", "得益于", "主要", "原因", "海外", "全球化", "OBM", "品牌",
)


def _evidence_coverage(claim_text: str, evidence_texts: list[str]) -> float:
    """证据文本对主张语义关键词的覆盖比例（0~1）。"""
    if not claim_text:
        return 0.0
    kws = [k for k in _BUSINESS_KEYWORDS if k in claim_text]
    if not kws:
        return 1.0 if evidence_texts else 0.0
    joined = "".join(evidence_texts)
    return sum(1 for k in kws if k in joined) / len(kws)


def verify_semantic(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
) -> VerificationResult:
    """语义主张核验：证据覆盖主张关键词 → PARTIALLY/SUPPORTED；否则 INSUFFICIENT。"""
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    matched_evidence_ids = matched_evidence_ids or []
    coverage = _evidence_coverage(claim_text_of(claim), evidence_texts)
    if not evidence_texts:
        return VerificationResult(
            claim_id, STATUS_INSUFFICIENT, confidence=0.4, verification_type=TYPE_SEMANTIC,
            matched_evidence_ids=matched_evidence_ids,
            reason="无证据（语义主张需业务描述/数据说明支撑）",
        )
    if coverage >= 0.6:
        return VerificationResult(
            claim_id, STATUS_PARTIALLY_SUPPORTED, confidence=0.7, verification_type=TYPE_SEMANTIC,
            matched_evidence_ids=matched_evidence_ids,
            reason=f"证据覆盖主张语义关键词（覆盖率 {coverage:.0%}）",
        )
    return VerificationResult(
        claim_id, STATUS_INSUFFICIENT, confidence=0.4, verification_type=TYPE_SEMANTIC,
        matched_evidence_ids=matched_evidence_ids,
        reason=f"证据不足：仅覆盖主张语义关键词的 {coverage:.0%}，缺少业务描述或数据说明",
    )


def verify_multi_evidence(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
    evidence_meta: list[dict] | None = None,
) -> VerificationResult:
    """多证据组合核验：主张需多维度证据（数值 + 同比 + 业务说明）。

    维度判定（基于证据文本/元数据）：
    - numeric：含可核验数字；
    - comparison：含同比/环比/同期；
    - business：含业务描述关键词。
    全部覆盖 → SUPPORTED；覆盖 ≥1 维但不全 → PARTIALLY_SUPPORTED；全无 → INSUFFICIENT。
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    matched_evidence_ids = matched_evidence_ids or []
    evidence_meta = evidence_meta or []
    joined = "".join(evidence_texts)

    has_numeric = any(meta.get("value_score", 0) > 0 for meta in evidence_meta) or any(
        c.isdigit() for c in joined
    )
    has_comparison = any(kw in joined for kw in ("同比", "环比", "同期", "较上年", "较上期"))
    has_business = any(kw in joined for kw in _BUSINESS_KEYWORDS)

    dims = {"numeric": has_numeric, "comparison": has_comparison, "business": has_business}
    covered = sum(1 for v in dims.values() if v)
    calc = {"dimensions": dims, "covered": covered, "required": 3}

    if covered >= 3:
        status, conf, reason = STATUS_SUPPORTED, 0.9, "证据覆盖数值+同比+业务说明三个维度"
    elif covered >= 1:
        status, conf, reason = STATUS_PARTIALLY_SUPPORTED, 0.6, f"证据覆盖 {covered}/3 个维度（{calc['dimensions']}）"
    else:
        status, conf, reason = STATUS_INSUFFICIENT, 0.4, "证据不足：数值/同比/业务说明均缺失"
    return VerificationResult(
        claim_id, status, confidence=conf, verification_type=TYPE_MULTI_EVIDENCE,
        matched_evidence_ids=matched_evidence_ids, calculation_detail=calc, reason=reason,
    )
