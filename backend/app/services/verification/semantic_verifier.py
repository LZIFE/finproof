"""金融语义核验与证据充分性分析（Phase 4B.2）。

Semantic Claim → Evidence Requirement 规则 → Evidence Coverage 评分 → 结论。

保持 Evidence First 原则：不判断真假，只判断证据是否足够支撑主张。
- 证据覆盖全部要求维度 → SUPPORTED
- 覆盖部分 → PARTIALLY_SUPPORTED
- 无覆盖/证据不足 → INSUFFICIENT_EVIDENCE
"""

import re

from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_SUPPORTED,
    TYPE_CAUSAL,
    TYPE_COMPARISON,
    TYPE_SEMANTIC_SUPPORT,
    VerificationResult,
    claim_text_of,
)

# 证据维度信号
_NUMERIC_RE = re.compile(r"\d")
_GROWTH_SIGNAL = ("同比", "环比", "增长", "上升", "提高", "增加", "%", "％")
_SHARE_SIGNAL = ("占比", "过半", "份额", "超过", "贡献", "一半", "主要")
_DISCLOSURE_SIGNAL = ("主要系", "由于", "得益于", "因为", "原因", "调整", "推动", "带动", "所致", "投入")
_RANK_SIGNAL = ("排名", "第一", "领先", "首位", "前列", "最强", "龙头", "位居")
_PEER_SIGNAL = ("行业", "同行", "同业", "竞争对手", "高于行业", "领先行业", "平均")
_TREND_SIGNAL = ("持续", "稳步", "逐年", "保持", "趋势", "历史", "连续")
_GUIDANCE_SIGNAL = ("预计", "目标", "展望", "指引", "将", "计划", "有望")

# 语义类型关键词（原句分类，优先于 claim_type）
SEMANTIC_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "STRATEGIC_CLAIM": ("核心", "引擎", "增长动力", "主要收入来源", "重要增量", "支柱", "基本盘"),
    "CAUSAL_CLAIM": ("由于", "主要系", "得益于", "因为", "推动", "导致", "所致", "带动"),
    "COMPARATIVE_CLAIM": ("领先", "高于行业", "优于", "第一", "龙头", "最强", "优势", "居前"),
    "FORECAST_CLAIM": ("预计", "展望", "将", "未来", "有望", "目标", "计划"),
}

# 各语义类型的 Evidence Requirement 规则（维度, 说明）
EVIDENCE_REQUIREMENTS: dict[str, list[tuple[str, str]]] = {
    "BUSINESS_FACT": [("numeric", "相关业务数据（数值）"), ("growth", "增长/同比数据")],
    "STRATEGIC_CLAIM": [
        ("numeric", "相关业务数据（数值）"),
        ("growth", "增长率数据"),
        ("share", "整体占比/增长比较"),
    ],
    "CAUSAL_CLAIM": [("numeric", "财务结果（数值）"), ("disclosure", "公司披露原因/时间顺序")],
    "COMPARATIVE_CLAIM": [("rank", "行业排名/市占率"), ("peer", "同行业/比较对象数据")],
    "FORECAST_CLAIM": [("trend", "历史趋势数据"), ("guidance", "管理层指引/预测")],
}


def classify_semantic_type(claim: dict) -> str:
    """语义主张类型分类：原句关键词优先，claim_type 兜底。"""
    text = claim_text_of(claim)
    for t, kws in SEMANTIC_TYPE_KEYWORDS.items():
        if any(k in text for k in kws):
            return t
    ct = (claim.get("claim_type") or "").upper()
    mapping = {
        "CAUSAL_CLAIM": "CAUSAL_CLAIM",
        "CAUSALITY": "CAUSAL_CLAIM",
        "COMPARISON": "COMPARATIVE_CLAIM",
        "FORECAST": "FORECAST_CLAIM",
        "OPINION": "STRATEGIC_CLAIM",
        "TREND": "BUSINESS_FACT",
        "BUSINESS_FACT": "BUSINESS_FACT",
        "BUSINESS_SHARE": "BUSINESS_FACT",
        "SCOPE": "BUSINESS_FACT",
        "OTHER_VERIFIABLE": "BUSINESS_FACT",
    }
    return mapping.get(ct, "BUSINESS_FACT")


def _dimension_hit(text: str, dim: str) -> bool:
    if not text:
        return False
    if dim == "numeric":
        return bool(_NUMERIC_RE.search(text))
    if dim == "growth":
        return any(s in text for s in _GROWTH_SIGNAL)
    if dim == "share":
        return any(s in text for s in _SHARE_SIGNAL) or bool(re.search(r"占[^，。]{0,8}%|占比", text))
    if dim == "disclosure":
        return any(s in text for s in _DISCLOSURE_SIGNAL)
    if dim == "rank":
        return any(s in text for s in _RANK_SIGNAL)
    if dim == "peer":
        return any(s in text for s in _PEER_SIGNAL)
    if dim == "trend":
        return any(s in text for s in _TREND_SIGNAL)
    if dim == "guidance":
        return any(s in text for s in _GUIDANCE_SIGNAL)
    return False


def analyze_coverage(
    claim: dict, evidence_texts: list[str]
) -> tuple[str, list[tuple[str, str]], dict[str, bool]]:
    """语义类型 + Evidence Requirement 覆盖率分析。

    返回 (semantic_type, requirements, coverage{维度: 是否覆盖})。
    """
    stype = classify_semantic_type(claim)
    requirements = EVIDENCE_REQUIREMENTS.get(stype, EVIDENCE_REQUIREMENTS["BUSINESS_FACT"])
    joined = "".join(evidence_texts)
    coverage = {dim: _dimension_hit(joined, dim) for dim, _desc in requirements}
    return stype, requirements, coverage


def verify_semantic_support(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
) -> VerificationResult:
    """语义主张证据充分性核验（SEMANTIC_SUPPORT_CHECK）。

    coverage 全部 → SUPPORTED；部分 → PARTIALLY_SUPPORTED；无 → INSUFFICIENT_EVIDENCE。
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    matched_evidence_ids = matched_evidence_ids or []
    stype, requirements, coverage = analyze_coverage(claim, evidence_texts)
    covered = sum(1 for v in coverage.values() if v)
    total = len(requirements)
    calc = {
        "semantic_type": stype,
        "coverage": {dim: covered_flag for dim, covered_flag in coverage.items()},
        "covered": covered,
        "required": total,
        "required_desc": [desc for _d, desc in requirements],
    }
    if total == 0 or covered == 0:
        status, conf, reason = STATUS_INSUFFICIENT, 0.4, f"证据不足：{stype} 主张的 {total} 个要求维度均未覆盖"
    elif covered >= total:
        status, conf, reason = STATUS_SUPPORTED, 0.85, f"证据覆盖 {covered}/{total} 个要求维度，足以支撑 {stype} 主张"
    else:
        status, conf, reason = (
            STATUS_PARTIALLY_SUPPORTED, 0.6,
            f"证据覆盖 {covered}/{total} 个要求维度（缺 {', '.join(desc for d, desc in requirements if not coverage[d])}），不足以完全支撑 {stype} 主张",
        )
    return VerificationResult(
        claim_id, status, confidence=conf, verification_type=TYPE_SEMANTIC_SUPPORT,
        matched_evidence_ids=matched_evidence_ids, calculation_detail=calc, reason=reason,
    )


def verify_causal(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
) -> VerificationResult:
    """因果关系核验（CAUSAL_CHECK）。

    主张含因果结构（由于/主要系）→ 拆 Cause/Result；
    证据需同时有：财务结果（数值）+ 公司披露原因/时间顺序。
    只有相关（仅有财务结果、无原因披露）不能认定因果成立 → INSUFFICIENT_EVIDENCE。
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    matched_evidence_ids = matched_evidence_ids or []
    text = claim_text_of(claim)
    joined = "".join(evidence_texts)
    has_result = _dimension_hit(joined, "numeric")
    has_disclosure = _dimension_hit(joined, "disclosure")
    has_time_order = bool(re.search(r"20\d{2}年|报告期|期间|之后|随后", joined))
    calc = {
        "cause": _split_cause(text)[0],
        "result": _split_cause(text)[1],
        "has_financial_result": has_result,
        "has_disclosed_reason": has_disclosure,
        "has_time_order": has_time_order,
    }
    if has_result and (has_disclosure or has_time_order):
        return VerificationResult(
            claim_id, STATUS_PARTIALLY_SUPPORTED, confidence=0.7, verification_type=TYPE_CAUSAL,
            matched_evidence_ids=matched_evidence_ids, calculation_detail=calc,
            reason="证据含财务结果与原因披露/时间顺序，因果链基本成立（仍需人工复核）",
        )
    return VerificationResult(
        claim_id, STATUS_INSUFFICIENT, confidence=0.4, verification_type=TYPE_CAUSAL,
        matched_evidence_ids=matched_evidence_ids, calculation_detail=calc,
        reason="证据仅有相关性（财务结果）而缺少公司披露原因或时间顺序，不足以认定因果关系",
    )


def _split_cause(text: str) -> tuple[str, str]:
    for marker in ("由于", "主要系", "得益于", "因为"):
        if marker in text:
            parts = text.split(marker, 1)
            if marker == "由于" or marker == "因为":
                return parts[1].split("，", 1)[0], parts[0] or parts[1].split("，", 1)[-1]
            return parts[0], parts[1]
    return "", text


def verify_comparison(
    claim: dict,
    evidence_texts: list[str],
    matched_evidence_ids: list | None = None,
) -> VerificationResult:
    """比较类主张核验（COMPARISON_CHECK）。

    主张含领先/高于/优于等比较词 → 证据需含比较对象（行业排名/市占率/同行业数据）。
    无比较数据 → INSUFFICIENT_EVIDENCE。
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    matched_evidence_ids = matched_evidence_ids or []
    joined = "".join(evidence_texts)
    has_rank = _dimension_hit(joined, "rank")
    has_peer = _dimension_hit(joined, "peer")
    calc = {"has_industry_rank": has_rank, "has_peer_data": has_peer}
    if has_rank or has_peer:
        return VerificationResult(
            claim_id, STATUS_PARTIALLY_SUPPORTED, confidence=0.7, verification_type=TYPE_COMPARISON,
            matched_evidence_ids=matched_evidence_ids, calculation_detail=calc,
            reason="证据含行业排名/市占率或同行业比较数据，比较类主张有部分支撑",
        )
    return VerificationResult(
        claim_id, STATUS_INSUFFICIENT, confidence=0.4, verification_type=TYPE_COMPARISON,
        matched_evidence_ids=matched_evidence_ids, calculation_detail=calc,
        reason="证据缺少比较对象（行业排名/市占率/同行业数据），无法支撑'领先行业'类主张",
    )
