"""Phase 23.16 Step 3 — Evidence Reranker

在 score_block 初排之后、Top-K 截断之前，对 hybrid union 候选做二级综合重排。

输入：claim + candidate blocks（含 score_block 分量分）
输出：重排后的 top50 候选

评分维度（0-1，加权和）：
- entity_match    : 公司名/简称/代码命中
- metric_similarity: 指标别名命中 + 字符 n-gram 语义相似（营业收入≈主营业务收入≈revenue）
- period_match    : 期间关键词/文档期间
- table_relevance : 表格感知（数字/年份/单位/指标行）
- semantic_similarity: 字符 n-gram TF-IDF 余弦（claim 原文 vs block 文本）

最终分 = Σ w_i * score_i；保留 score_block 的 final_score 作为基础分叠加。
"""
from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer

from app.services.evidence_retrieval.engine import (
    entity_matches,
    is_noise_block,
    metric_aliases,
    metric_hits,
    period_matches,
    table_awareness_score,
)

RERANK_WEIGHTS = {
    "entity": 0.20,
    "metric": 0.15,
    "period": 0.15,
    "table": 0.10,
    "semantic": 0.40,  # Phase 23.17 Step 5：semantic 主导（替代 metric 主导）
}


def _semantic_similarity(claim_text: str, block_text: str) -> float:
    """字符 n-gram TF-IDF 余弦相似（语义匹配）。"""
    if not claim_text.strip() or not block_text.strip():
        return 0.0
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True)
        mat = vec.fit_transform([block_text, claim_text])
        sim = (mat[0] @ mat[1].T).toarray()[0, 0]
        return round(float(sim), 4)
    except ValueError:
        return 0.0


def rerank_candidates(claim: dict, candidates: list[dict], doc_period: str | None = None) -> list[dict]:
    """对 hybrid union 候选做二级综合重排，返回按 rerank_score 降序的候选（附 rerank 分量）。"""
    claim_text = str(claim.get("original_text") or claim.get("claim_text") or "")
    claim_period = claim.get("period")
    entity_name = claim.get("entity_name") or claim.get("entity")
    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))

    for c in candidates:
        text = c.get("block_text") or ""
        if not text or is_noise_block(text):
            c["rerank_score"] = 0.0
            c["rerank_components"] = {"entity": 0.0, "metric": 0.0, "period": 0.0, "table": 0.0, "semantic": 0.0}
            continue

        # entity
        ent = entity_matches(text, entity_name)

        # metric：别名命中（1.0）或字符相似（0-1）
        hits = metric_hits(text, aliases)
        metric_sim = 1.0 if hits else 0.0
        if not hits and aliases:
            try:
                mvec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), lowercase=True)
                alias_text = " ".join(a for a in aliases if a)
                mmat = mvec.fit_transform([text, alias_text])
                ms = (mmat[0] @ mmat[1].T).toarray()[0, 0]
                metric_sim = round(float(ms), 4)
            except ValueError:
                metric_sim = 0.0

        # period
        per = period_matches(claim_period, text, doc_period)

        # table relevance
        tbl = table_awareness_score(text)

        # semantic
        sem = _semantic_similarity(claim_text, text)

        rerank = (
            RERANK_WEIGHTS["entity"] * ent
            + RERANK_WEIGHTS["metric"] * metric_sim
            + RERANK_WEIGHTS["period"] * per
            + RERANK_WEIGHTS["table"] * tbl
            + RERANK_WEIGHTS["semantic"] * sem
        )
        c["rerank_score"] = round(rerank, 4)
        c["rerank_components"] = {
            "entity": ent,
            "metric": metric_sim,
            "period": per,
            "table": tbl,
            "semantic": sem,
        }

    # 排序：rerank_score 主序，score_block final_score 平局兜底
    candidates.sort(key=lambda c: (-c.get("rerank_score", 0.0), -c.get("final_score", 0.0)))
    return candidates
