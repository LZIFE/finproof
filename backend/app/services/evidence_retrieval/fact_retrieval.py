"""Phase 23.19 Task 3 — Fact Retrieval Layer

在 reranking 之前，直接按指标别名检索财务事实候选：

1. 对 hybrid union 候选块做 Evidence Window Reconstruction（跨块合并 → FinancialEvidenceObject）
2. 用 fact_match_score 对重建对象直接排序
3. 把财务证据对象字段附加到候选（metric/current/previous/growth/unit/period/table_type/source_blocks）

接入 retrieve_for_claim：rerank 之前调用，确保财务表格行（跨块）优先进入 top_k。
"""
from __future__ import annotations

from app.models import DocumentBlock
from app.services.evidence_retrieval.evidence_window_reconstruction import reconstruct_evidence_window
from app.services.evidence_retrieval.financial_fact_extractor import fact_match_score

_FACT_LIMIT = 100


def _block_by_id(session, block_id: int) -> DocumentBlock | None:
    return session.query(DocumentBlock).filter(DocumentBlock.id == block_id).first()


def fact_retrieve_candidates(session, claim: dict, scored: list[dict], top_k: int = _FACT_LIMIT) -> list[dict]:
    """对候选块做窗口重建 + 财务事实匹配排序，返回附加 FinancialEvidenceObject 的候选。

    返回排序后的候选（fact_match_score 降序；只增强候选字段，不删除任何候选）。
    """
    for c in scored:
        bid = c.get("block_id")
        if bid is None:
            continue
        block = _block_by_id(session, bid)
        if block is None or not block.text:
            c["financial_object"] = None
            c["fact_retrieval_score"] = 0.0
            continue
        # Evidence Window Reconstruction：跨块合并（同页同表近 y）
        obj = reconstruct_evidence_window(session, block)
        c["financial_object"] = obj
        # Financial Fact Match：claim 结构化字段 vs 重建对象
        merged = obj.get("merged_text") or block.text
        ffm = fact_match_score(merged, claim)
        # fact 匹配得分 = 0.7 * ffm + 0.3 * has_number（数值证据优先）
        c["fact_retrieval_score"] = round(0.7 * ffm + 0.3 * (1.0 if obj.get("has_number") else 0.0), 4)

    scored.sort(key=lambda c: (-c.get("fact_retrieval_score", 0.0), -c.get("final_score", 0.0)))
    return scored
