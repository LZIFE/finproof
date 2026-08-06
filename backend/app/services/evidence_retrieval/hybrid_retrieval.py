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


def _target_page_ids(session, doc_id: int, target_sections: list[str]) -> set[int]:
    """目标章节页 → page_id 集合（作为 bm25/vector 的检索范围）。"""
    from app.services.evidence_retrieval.section_index import target_pages_for_claim

    pages = target_pages_for_claim(doc_id, target_sections)
    pids: set[int] = set()
    for pn in pages:
        pid = _page_id_by_doc_page(session, doc_id, pn)
        if pid:
            pids.add(pid)
    return pids


def bm25_candidates(session, doc_id: int, claim: dict, target_sections: list[str], limit: int = _BM25_LIMIT) -> list[int]:
    """BM25 风格：TF-IDF 词频加权检索（对目标章节页 blocks 打分）。"""
    query = _claim_query_text(claim)
    if not query.strip():
        return []
    pids = _target_page_ids(session, doc_id, target_sections)
    if not pids:
        return []
    rows = (
        session.query(DocumentBlock.id, DocumentBlock.text)
        .filter(DocumentBlock.document_id == doc_id, DocumentBlock.page_id.in_(pids))
        .filter(DocumentBlock.text.isnot(None))
        .all()
    )
    if not rows:
        return []
    texts = [(bid, t or "") for bid, t in rows]
    # 词级 TF-IDF（BM25 近似：词频 + IDF）
    try:
        vec = TfidfVectorizer(analyzer="word", token_pattern=r"[\u4e00-\u9fff]{2,}|[A-Za-z]+|[0-9,]+", lowercase=True)
        mat = vec.fit_transform([t for _, t in texts])
        qvec = vec.transform([query])
        scores = (mat @ qvec.T).toarray().ravel()
    except ValueError:  # 空词表
        return []
    ranked = sorted(zip([b for b, _ in texts], scores), key=lambda x: -x[1])
    return [b for b, s in ranked[:limit] if s > 0]


def vector_candidates(session, doc_id: int, claim: dict, target_sections: list[str], limit: int = _VECTOR_LIMIT) -> list[int]:
    """Vector：字符 n-gram TF-IDF 余弦相似（语义匹配：营业收入≈主营业务收入≈revenue）。"""
    query = _claim_query_text(claim)
    if not query.strip():
        return []
    pids = _target_page_ids(session, doc_id, target_sections)
    if not pids:
        return []
    rows = (
        session.query(DocumentBlock.id, DocumentBlock.text)
        .filter(DocumentBlock.document_id == doc_id, DocumentBlock.page_id.in_(pids))
        .filter(DocumentBlock.text.isnot(None))
        .all()
    )
    if not rows:
        return []
    texts = [(bid, t or "") for bid, t in rows]
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True)
        mat = vec.fit_transform([t for _, t in texts])
        qvec = vec.transform([query])
        scores = (mat @ qvec.T).toarray().ravel()
    except ValueError:
        return []
    ranked = sorted(zip([b for b, _ in texts], scores), key=lambda x: -x[1])
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
    target_sections: list[str],
    aliases: set[str],
) -> list[int]:
    """三路召回 union（去重，保序：rule 优先 → vector → bm25）。"""
    r_cands = rule_candidates(session, doc_id, claim, aliases)
    v_cands = vector_candidates(session, doc_id, claim, target_sections)
    b_cands = bm25_candidates(session, doc_id, claim, target_sections)
    seen: set[int] = set()
    union: list[int] = []
    for bid in r_cands + v_cands + b_cands:
        if bid not in seen:
            seen.add(bid)
            union.append(bid)
    return union
