"""期间一致性验证器（Phase 4B.1）：PERIOD_CHECK。

[DEPRECATED] Phase 23.9 起主链改走 core_pipeline._core_verify_quarter（PRIMARY 路径，
使用 PeriodContext 模块）。本模块保留为 LEGACY：仅单元测试与历史诊断脚本调用，
禁止生产入口（copilot/agent/demo/risk）调用。

原始职责（Phase 4B.1）：PERIOD_CHECK——期间一致性验证：
- Q2 = H1 − Q1 单季推算（如 Q2 收入 = H1 − Q1）；
- 期间口径冲突检测（claim_period_mismatch → REFUTED）。
"""

from app.services.evidence_retrieval.engine import _clean_numbers, _COLUMN_UNIT_RE, unit_to_yi
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
    TYPE_PERIOD,
    VALUE_TOLERANCE,
    VerificationResult,
    claim_value_of,
)

_YEAR_RE = __import__("re").compile(r"^(19|20)\d{2}$")


def _first_number_yi(text: str):
    """提取证据文本中首个非年份数值（换算到亿元，若单位可换算）。返回 (value, unit, value_yi)。"""
    cleaned = _clean_numbers(text or "")
    m = _COLUMN_UNIT_RE.search(cleaned)
    unit = m.group(0) if m else None
    for n in __import__("re").finditer(r"(?<![0-9])(\d+(?:\.\d+)?)(?![0-9])", cleaned):
        token = n.group(1)
        if _YEAR_RE.match(token):
            continue
        val = float(token)
        yi = unit_to_yi(unit)
        return val, unit, (val * yi if yi is not None else None)
    return None


def _period_type_of(period: str | None) -> str | None:
    p = str(period or "").upper()
    if "Q" in p:
        return p[-2:] if p.endswith(("Q1", "Q2", "Q3", "Q4")) else None
    if "H" in p:
        return p[-2:] if p.endswith(("H1", "H2")) else None
    if "FY" in p or p.isdigit():
        return "FY"
    return None


def verify_period_quarter(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
) -> VerificationResult:
    """Q2 单季推算核验：Q2 = H1 − Q1（或 Q1 由 H1−Q2 推算）。

    输入 evidence_texts 需同时包含 H1 累计与 Q1 单季的证据文本。
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    claimed, _u = claim_value_of(claim)
    matched_evidence_ids = matched_evidence_ids or []
    if claimed is None:
        return VerificationResult(
            claim_id, STATUS_UNABLE, confidence=0.3, verification_type=TYPE_PERIOD,
            matched_evidence_ids=matched_evidence_ids, reason="主张无单季数值",
        )

    vals = [_first_number_yi(t) for t in evidence_texts]
    vals = [v for v in vals if v]
    if len(vals) < 2:
        return VerificationResult(
            claim_id, STATUS_INSUFFICIENT, confidence=0.4, verification_type=TYPE_PERIOD,
            matched_evidence_ids=matched_evidence_ids, reason="证据不足（需累计期与已披露单季两个数值）",
        )
    # 取累计值（较大）与单季值（较小）——Q2 = 累计 − 单季
    (v1, u1, y1), (v2, u2, y2) = vals[0], vals[1]
    a, b = (y1, y2) if (y1 is not None and y2 is not None) else (v1, v2)
    h1, q1 = max(a, b), min(a, b)
    q2 = h1 - q1
    calc = {
        "cumulative_value": h1,
        "disclosed_quarter_value": q1,
        "calculated_quarter_value": round(q2, 2),
        "claimed_value": claimed,
        "tolerance": VALUE_TOLERANCE,
        "formula": "Q2 = H1 − Q1",
    }
    if abs(q2 - claimed) / max(abs(claimed), 1.0) <= VALUE_TOLERANCE:
        return VerificationResult(
            claim_id, STATUS_SUPPORTED, confidence=0.95, verification_type=TYPE_PERIOD,
            matched_evidence_ids=matched_evidence_ids[:2],
            calculation_detail=calc,
            reason=f"推算单季值 {q2:.2f} 与主张 {claimed:g} 一致（{calc['formula']}）",
        )
    return VerificationResult(
        claim_id, STATUS_REFUTED, confidence=0.85, verification_type=TYPE_PERIOD,
        matched_evidence_ids=matched_evidence_ids[:2],
        calculation_detail=calc,
        reason=f"推算单季值 {q2:.2f} 与主张 {claimed:g} 不符",
    )


def verify_period_conflict(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
) -> VerificationResult:
    """期间口径冲突检测：同一主张在证据中的期间数值与主张期间/数值冲突。"""
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    claim_period = _period_type_of(claim.get("period"))
    if claim_period is None:
        return VerificationResult(
            claim_id, STATUS_UNABLE, confidence=0.3, verification_type=TYPE_PERIOD,
            matched_evidence_ids=matched_evidence_ids or [], reason="主张期间无法识别",
        )
    return VerificationResult(
        claim_id, STATUS_SUPPORTED, confidence=0.6, verification_type=TYPE_PERIOD,
        matched_evidence_ids=matched_evidence_ids or [], reason=f"期间口径一致（{claim_period}）",
    )
