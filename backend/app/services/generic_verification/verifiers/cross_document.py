"""跨文档核验引擎：在用户提供的证据文档块中检索支持/反驳材料。

纯函数：输入 claim + 证据块列表，输出 VerificationOutcome。
打分 = 文本相似度 + 数值命中加分（语境命中且数值兼容 +0.4）。
"""

from __future__ import annotations

from app.services.evidence_retrieval.engine import text_similarity
from app.services.generic_verification.claim_extraction import extract_numbers
from app.services.generic_verification.schemas import GenericClaim, VerificationOutcome
from app.services.generic_verification.verifiers.internal_consistency import (
    _context_ctx_match,
    _quantity_comparable,
    _same_context_slot,
    values_compatible,
)
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)


def verify_claim_cross_document(claim: GenericClaim, evidence_blocks: list[dict],
                                top_k: int = 5) -> VerificationOutcome:
    scored: list[tuple[float, dict]] = []
    for b in evidence_blocks:
        text = b.get("text") or ""
        if not text.strip():
            continue
        score = text_similarity(claim.source_text, text)
        matched_value = False
        conflict = False
        for num in claim.numbers:
            ctx = (num.get("context") or "")
            if not _context_ctx_match(ctx, text):
                continue
            for other in extract_numbers(text):
                # 仅同一语义语境槽的数字参与支持/冲突判定（如"营收"vs"同比增长"百分比不算冲突）
                if not _same_context_slot(ctx, other.get("context") or ""):
                    continue
                # 数量类型不同（百分比 vs 绝对值）不可比，跳过
                if not _quantity_comparable(num.get("unit"), other.get("unit")):
                    continue
                if values_compatible(num.get("value"), num.get("unit"),
                                     other.get("value"), other.get("unit")):
                    matched_value = True
                else:
                    conflict = True
        if matched_value:
            score += 0.4
        scored.append((score, {**b, "_matched_value": matched_value, "_conflict": conflict}))

    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[:top_k]
    evidence = [
        {"text": b.get("text"), "page_number": b.get("page_number"),
         "document_id": b.get("document_id"), "score": round(s, 4)}
        for s, b in top if s > 0
    ]

    if any(b["_conflict"] for _, b in top):
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.85,
            mode_used=["cross_doc"], evidence=evidence,
            reason="证据文档中存在与主张数值冲突的记录", error_type="CROSS_DOC_CONFLICT",
        )
    if any(b["_matched_value"] for _, b in top):
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_SUPPORTED, confidence=0.75,
            mode_used=["cross_doc"], evidence=evidence,
            reason="证据文档中数值一致", error_type=None,
        )
    if evidence:
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_PARTIALLY_SUPPORTED, confidence=0.5,
            mode_used=["cross_doc"], evidence=evidence,
            reason="证据与主张文本相关但未找到数值对应", error_type=None,
        )
    return VerificationOutcome(
        claim_id=claim.claim_id, verdict=STATUS_INSUFFICIENT, confidence=0.5,
        mode_used=["cross_doc"], evidence=[],
        reason="证据文档中未检索到相关块", error_type=None,
    )
