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


def merge_evidence_index_candidates(session, claim: dict, scored: list[dict], target_sections: list[str]) -> list[dict]:
    """Phase 23.20 Task 3：把 FinancialEvidence Index 候选并入 block 候选池。

    - 对每个检索到的证据对象，取其 source_blocks 中尚未入池的块加入 scored
      （附加 financial_object + evidence_retrieval_score，标记 source="evidence_index"）
    - 不删除任何既有 block 候选（仅 union 扩池）
    - 返回扩池后的 scored；reranker 将按 financial_fact_match 对 evidence 对象优先排序
    """
    from app.services.evidence_retrieval.evidence_retriever import retrieve_financial_evidence

    evs = retrieve_financial_evidence(claim, target_sections=target_sections, top_k=30)
    if not evs:
        return scored

    existing_ids = {c.get("block_id") for c in scored}
    added = 0
    for ev in evs:
        for bid in ev.get("source_blocks", []):
            if bid in existing_ids:
                continue
            block = _block_by_id(session, bid)
            if block is None or not block.text:
                continue
            scored.append({
                "document_id": ev.get("document_id"),
                "page_number": ev.get("page_number"),
                "block_id": bid,
                "page_id": ev.get("page_id"),
                "y0": block.y0 or 0.0,
                "reading_order": block.reading_order or 0,
                "final_score": ev.get("retrieval_score", 0.0),
                "block_text": block.text[:300],
                "financial_object": ev,          # 直接附加索引证据对象（跨块重建）
                "fact_retrieval_score": ev.get("retrieval_score", 0.0),
                "retrieval_method": "evidence_index",
            })
            existing_ids.add(bid)
            added += 1
    return scored


# Phase 23.23 Task 1：EvidenceBundle 扩展——financial_fact schema（与任务要求一致）
def attach_financial_facts(scored: list[dict]) -> list[dict]:
    """为候选附加标准化 financial_fact 字段（EvidenceBundle 的 financial_facts 部分）。

    - 从候选的 financial_object（Phase 23.20/23.21 已附加）提取 schema 8 字段
    - 不删除 raw block 字段（block_id / block_text / page 等原样保留）
    - 无 financial_object 的候选保持 raw-block-only（向后兼容）
    """
    for c in scored:
        fo = c.get("financial_object") or {}
        if not fo:
            c["financial_fact"] = None
            continue
        c["financial_fact"] = {
            "metric": fo.get("metric", ""),
            "metric_code": fo.get("metric_code", ""),
            "current_value": fo.get("current_value"),
            "previous_value": fo.get("previous_value"),
            "growth": fo.get("growth"),
            "unit": fo.get("unit", ""),
            "period": fo.get("period", ""),
            "periods": fo.get("periods", []),
            "table_type": fo.get("table_type", "other"),
            "source_blocks": fo.get("source_blocks", []),
            "source_evidence_id": c.get("block_id"),   # 关联 raw block
        }
    return scored
