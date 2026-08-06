"""Phase 23.18 Task 3 — Financial Reranker（fact-level 匹配主导）

替代文本相似度主导的排序（Phase 23.17 semantic 0.40 对财务数据行不利，
正确块被压到第 116 位）。新评分：

- financial_fact_match 0.45 ：claim 结构化字段 vs block 提取财务事实（metric/unit/period/row_label）
- metric_match          0.20 ：指标别名命中
- period_match          0.15 ：期间匹配
- table_match           0.10 ：表格感知（数字/年份/单位/指标行）
- semantic_similarity   0.10 ：字符 n-gram 余弦（仅辅助，不再主导）

Reranker 只排序，不删除候选（排序后数量不变）。
"""
from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer

from app.services.evidence_retrieval.engine import (
    is_noise_block,
    metric_hits,
    period_matches,
    table_awareness_score,
)
from app.services.evidence_retrieval.financial_fact_extractor import (
    extract_financial_fact,
    fact_match_score,
)

RERANK_WEIGHTS = {
    "financial_fact_match": 0.45,
    "metric": 0.20,
    "period": 0.15,
    "table": 0.10,
    "semantic": 0.10,  # 仅辅助（Phase 23.17 曾 0.40 主导 → 财务数据行被压）
}


def _semantic_similarity(claim_text: str, block_text: str) -> float:
    """字符 n-gram TF-IDF 余弦相似（辅助信号）。"""
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
    """对候选做财务事实主导的二级重排；只排序，不删除候选。"""
    claim_text = str(claim.get("original_text") or claim.get("claim_text") or "")
    claim_period = claim.get("period")

    # metric 别名集合（metric_match 用）
    from app.services.evidence_retrieval.engine import metric_aliases

    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))

    for c in candidates:
        text = c.get("block_text") or ""
        if not text or is_noise_block(text):
            c["rerank_score"] = 0.0
            c["rerank_components"] = {
                "financial_fact_match": 0.0, "metric": 0.0, "period": 0.0, "table": 0.0, "semantic": 0.0,
            }
            continue

        # 1) financial_fact_match：claim 结构化字段 vs block 提取事实（fact-level）
        fact = extract_financial_fact(text)
        ffm = fact_match_score(text, claim, fact=fact)

        # 2) metric_match：别名命中
        mm = 1.0 if metric_hits(text, aliases) else 0.0

        # 3) period_match
        pm = period_matches(claim_period, text, doc_period)

        # 4) table_match：表格感知
        tm = table_awareness_score(text)

        # 5) semantic（辅助）
        sm = _semantic_similarity(claim_text, text)

        rerank = (
            RERANK_WEIGHTS["financial_fact_match"] * ffm
            + RERANK_WEIGHTS["metric"] * mm
            + RERANK_WEIGHTS["period"] * pm
            + RERANK_WEIGHTS["table"] * tm
            + RERANK_WEIGHTS["semantic"] * sm
        )
        c["rerank_score"] = round(rerank, 4)
        c["rerank_components"] = {
            "financial_fact_match": ffm,
            "metric": mm,
            "period": pm,
            "table": tm,
            "semantic": sm,
        }

    # 只排序，不删除候选
    candidates.sort(key=lambda c: (-c.get("rerank_score", 0.0), -c.get("final_score", 0.0)))
    return candidates
