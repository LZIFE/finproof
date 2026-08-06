"""Phase 23.16 Step 2 — Hybrid Retrieval：三路召回合并（BM25 + Vector + Rule）

对 claim 的候选生成从"单一 keyword LIKE"升级为三路召回 + candidate union：

1. BM25 Retrieval：document_blocks.text 词频加权检索（词形匹配，覆盖等价词）
2. Vector Retrieval：字符 n-gram TF-IDF 余弦相似（语义匹配：营业收入≈主营业务收入≈revenue）
3. Rule Retrieval：保留现有 entity / metric / period / section 规则召回（_candidate_blocks + 章节路由）

三路候选 union 后统一走 score_block 评分（Step 3 reranker 在其上做二级排序）。

性能控制：vector/bm25 只在目标章节页的 blocks 内打分（复用 section_index 缩小范围），避免全库 TF-IDF。
"""
from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer

from app.models import DocumentBlock
from app.services.evidence_retrieval.engine import metric_aliases

# 每路召回上限（block 数）
_BM25_LIMIT = 200
_VECTOR_LIMIT = 200


def _claim_query_text(claim: dict) -> str:
    """构建 claim 检索文本（metric 别名 + 原文关键词 + 期间）。"""
    parts: list[str] = []
    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))
    parts.extend(a for a in aliases if a)
    orig = claim.get("original_text") or claim.get("claim_text") or ""
    parts.append(str(orig))
    period = claim.get("period")
    if period:
        parts.append(str(period))
    return " ".join(parts)


def _page_id_by_doc_page(session, doc_id: int, page_number: int) -> int | None:
    from app.models import DocumentPage

    row = (
        session.query(DocumentPage.id)
        .filter(DocumentPage.document_id == doc_id, DocumentPage.page_number == page_number)
        .first()
    )
    return row[0] if row else None


# Phase 23.17 Step 2：移除提前过滤——BM25/vector 改为全局检索（不再按章节页过滤）。
# per-doc TF-IDF 矩阵缓存：{doc_id: (vectorizer, matrix, block_ids)}，避免重复 fit。
_bm25_cache: dict[int, tuple] = {}
_vector_cache: dict[int, tuple] = {}


def _doc_blocks(session, doc_id: int):
    """该文档全部非空 block：(block_id, text) 列表。"""
    rows = (
        session.query(DocumentBlock.id, DocumentBlock.text)
        .filter(DocumentBlock.document_id == doc_id, DocumentBlock.text.isnot(None))
        .all()
    )
    return [(bid, t or "") for bid, t in rows]


def bm25_candidates(session, doc_id: int, claim: dict, target_sections: list[str] | None = None, limit: int = _BM25_LIMIT) -> list[int]:
    """BM25 风格：词级 TF-IDF 全局检索（不按页过滤；章节仅用于可选加分由上层处理）。"""
    query = _claim_query_text(claim)
    if not query.strip():
        return []
    if doc_id not in _bm25_cache:
        texts = _doc_blocks(session, doc_id)
        if not texts:
            return []
        try:
            vec = TfidfVectorizer(analyzer="word", token_pattern=r"[\u4e00-\u9fff]{2,}|[A-Za-z]+|[0-9,]+", lowercase=True)
            mat = vec.fit_transform([t for _, t in texts])
            _bm25_cache[doc_id] = (vec, mat, [b for b, _ in texts])
        except ValueError:  # 空词表
            return []
    vec, mat, block_ids = _bm25_cache[doc_id]
    try:
        qvec = vec.transform([query])
        scores = (mat @ qvec.T).toarray().ravel()
    except ValueError:
        return []
    ranked = sorted(zip(block_ids, scores), key=lambda x: -x[1])
    return [b for b, s in ranked[:limit] if s > 0]


def vector_candidates(session, doc_id: int, claim: dict, target_sections: list[str] | None = None, limit: int = _VECTOR_LIMIT) -> list[int]:
    """Vector：字符 n-gram TF-IDF 全局余弦（语义匹配：营业收入≈主营业务收入≈revenue，不按页过滤）。"""
    query = _claim_query_text(claim)
    if not query.strip():
        return []
    if doc_id not in _vector_cache:
        texts = _doc_blocks(session, doc_id)
        if not texts:
            return []
        try:
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True)
            mat = vec.fit_transform([t for _, t in texts])
            _vector_cache[doc_id] = (vec, mat, [b for b, _ in texts])
        except ValueError:
            return []
    vec, mat, block_ids = _vector_cache[doc_id]
    try:
        qvec = vec.transform([query])
        scores = (mat @ qvec.T).toarray().ravel()
    except ValueError:
        return []
    ranked = sorted(zip(block_ids, scores), key=lambda x: -x[1])
    return [b for b, s in ranked[:limit] if s > 0]


def rule_candidates(session, doc_id: int, claim: dict, aliases: set[str], limit: int = 400) -> list[int]:
    """Rule：现有 keyword LIKE 召回（复用 _candidate_blocks 逻辑，取前 limit 块）。"""
    from app.services.evidence_retrieval.service import _candidate_blocks
    from app.models import Document

    doc = session.query(Document).filter(Document.id == doc_id).first()
    if doc is None:
        return []
    rows = _candidate_blocks(session, doc, aliases)
    return [b.id for b, _ in rows[:limit]]


def hybrid_candidates(
    session,
    doc_id: int,
    claim: dict,
    target_sections: list[str] | None = None,
    aliases: set[str] | None = None,
    union_floor: int = 100,
) -> list[int]:
    """三路召回 union（去重，保序：rule 优先 → embedding → bm25）。

    Phase 23.17 Step 4：BM25 top50 + Embedding top50 + Rule top50，union 至少 union_floor 个，
    无提前截断（不因排序丢弃候选）。
    """
    from app.services.evidence_retrieval.embedding import embed_candidates

    r_cands = rule_candidates(session, doc_id, claim, aliases or set())
    v_cands = embed_candidates(session, doc_id, claim)
    b_cands = bm25_candidates(session, doc_id, claim, target_sections)
    seen: set[int] = set()
    union: list[int] = []
    # 先并入各路上限（每路 top50）
    for cands, cap in ((r_cands, 50), (v_cands, 50), (b_cands, 50)):
        for bid in cands[:cap]:
            if bid not in seen:
                seen.add(bid)
                union.append(bid)
    # union 不足 floor 时，补充余量（不提前截断候选）
    if len(union) < union_floor:
        extra = (r_cands[50:] + v_cands[50:] + b_cands[50:])
        for bid in extra:
            if len(union) >= union_floor:
                break
            if bid not in seen:
                seen.add(bid)
                union.append(bid)
    return union
