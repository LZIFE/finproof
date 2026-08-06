"""Phase 23.26 Step 2 — Financial Evidence Ranking Recovery Reranker

排序优先级（Financial Evidence 优先，A→G 依次递减）：

A. financial_fact 存在        —— 带结构化事实的块优先
B. metric_match               —— fact metric 家族 vs claim metric
C. value_match                —— fact current_value vs claim value（单位换算）
D. period_match               —— fact periods vs claim period
E. growth_match               —— fact growth vs claim growth
F. table_type                 —— income_statement/balance_sheet/cash_flow
G. semantic similarity        —— 辅助，不再主导

原则：只排序，不删除候选（排序后数量不变）。
利用候选已附加的 financial_fact（attach_financial_facts，Phase 23.23）做 A-F；
G 用文本语义；无 fact 的候选（raw block）按 metric/text 信号排序（fallback）。
"""
from __future__ import annotations

import re

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
    "financial_fact_exists": 0.25,  # A
    "metric": 0.20,                 # B
    "value": 0.15,                  # C
    "period": 0.12,                 # D
    "growth": 0.08,                 # E
    "table": 0.10,                  # F
    "semantic": 0.10,               # G
}

# 表格类型优先级（财务主表 > 附注 > 其他）
_TABLE_TYPE_PRIORITY = {
    "income_statement": 1.0,
    "balance_sheet": 1.0,
    "cash_flow": 1.0,
    "equity_changes": 0.8,
    "other": 0.3,
}


def _semantic_similarity(claim_text: str, block_text: str) -> float:
    """字符 n-gram TF-IDF 余弦相似（G：辅助信号）。"""
    if not claim_text.strip() or not block_text.strip():
        return 0.0
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True)
        mat = vec.fit_transform([block_text, claim_text])
        sim = (mat[0] @ mat[1].T).toarray()[0, 0]
        return round(float(sim), 4)
    except ValueError:
        return 0.0


def _metric_family_compatible(claim_code: str, fact_code: str) -> bool:
    """指标家族匹配（revenue≈total_operating_revenue；净利润家族严格隔离）。"""
    if not claim_code or not fact_code:
        return False
    c = claim_code
    for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
        if c.startswith(pfx):
            c = c[len(pfx):]
            break
    if c == fact_code:
        return True
    fam = {
        "revenue": {"revenue", "total_operating_revenue"},
        "total_operating_revenue": {"revenue", "total_operating_revenue"},
    }
    return fact_code in fam.get(c, set())


def _value_compatible(claim_value, claim_unit: str, fact_value, fact_unit: str) -> bool:
    """fact 数值与 claim 数值兼容（统一换算到元，容差 1%）。"""
    if claim_value is None or fact_value is None:
        return False
    try:
        claim_v = float(claim_value)
        fact_v = float(fact_value)
    except (TypeError, ValueError):
        return False
    scale = {"元": 1.0, "千元": 1000.0, "万元": 1e4, "百万元": 1e6, "亿元": 1e8}
    cu = (claim_unit or "").replace("人民币", "")
    fu = (fact_unit or "千元").replace("人民币", "")
    claim_abs = claim_v * scale.get(cu, scale.get("千元", 1000.0))
    fact_abs = fact_v * scale.get(fu, scale.get("千元", 1000.0))
    if fact_abs == 0:
        return False
    ratio = claim_abs / fact_abs
    return 0.99 <= ratio <= 1.01


def _growth_compatible(claim_text: str, fact_growth) -> bool:
    """fact growth 与 claim 增长率主张兼容（有 claim 增长词且 fact growth 存在即信号）。"""
    if fact_growth is None:
        return False
    return any(w in claim_text for w in ("同比", "增长", "下降", "YoY", "增减", "增幅"))


def _period_compatible(claim_period, fact_periods) -> bool:
    """fact periods 含 claim period 年份。"""
    if not claim_period or not fact_periods:
        return False
    m = re.search(r"(19|20)\d{2}", str(claim_period))
    if not m:
        return False
    year = f"{m.group(0)}年"
    return any(year in p for p in fact_periods)


def rerank_candidates(claim: dict, candidates: list[dict], doc_period: str | None = None) -> list[dict]:
    """Financial Evidence 优先的七级重排；只排序，不删除候选。"""
    claim_text = str(claim.get("original_text") or claim.get("claim_text") or "")
    claim_period = claim.get("period")
    claim_value = claim.get("reported_value") or claim.get("value")
    if isinstance(claim_value, str):
        try:
            claim_value = float(claim_value.replace(",", ""))
        except ValueError:
            claim_value = None
    claim_unit = str(claim.get("unit") or "").strip()
    claim_code = str(claim.get("metric_code") or "").strip() or str(claim.get("metric") or "").strip()

    from app.services.evidence_retrieval.engine import metric_aliases

    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))

    for c in candidates:
        text = c.get("block_text") or ""
        if not text or is_noise_block(text):
            c["rerank_score"] = 0.0
            c["rerank_components"] = {
                "financial_fact_exists": 0.0, "metric": 0.0, "value": 0.0,
                "period": 0.0, "growth": 0.0, "table": 0.0, "semantic": 0.0,
            }
            continue

        ff = c.get("financial_fact") or {}

        # A. financial_fact 存在
        fact_exists = 1.0 if ff else 0.0

        # B. metric_match：fact metric 家族（无 fact 时用文本别名）
        if ff:
            mm = 1.0 if _metric_family_compatible(claim_code, ff.get("metric_code", "")) else 0.0
        else:
            mm = 1.0 if metric_hits(text, aliases) else 0.0

        # C. value_match：fact current_value vs claim value
        if ff:
            vm = 1.0 if _value_compatible(claim_value, claim_unit,
                                          ff.get("current_value"), ff.get("unit", "")) else 0.0
        else:
            vm = 0.0

        # D. period_match：fact periods vs claim period
        if ff:
            pm = 1.0 if _period_compatible(claim_period, ff.get("periods", [])) else 0.0
        else:
            pm = period_matches(claim_period, text, doc_period)

        # E. growth_match
        if ff:
            gm = 1.0 if _growth_compatible(claim_text, ff.get("growth")) else 0.0
        else:
            gm = 0.0

        # F. table_type
        tm = _TABLE_TYPE_PRIORITY.get(ff.get("table_type", "other"), 0.3) if ff else (
            table_awareness_score(text)
        )

        # G. semantic（辅助）
        sm = _semantic_similarity(claim_text, text)

        rerank = (
            RERANK_WEIGHTS["financial_fact_exists"] * fact_exists
            + RERANK_WEIGHTS["metric"] * mm
            + RERANK_WEIGHTS["value"] * vm
            + RERANK_WEIGHTS["period"] * pm
            + RERANK_WEIGHTS["growth"] * gm
            + RERANK_WEIGHTS["table"] * tm
            + RERANK_WEIGHTS["semantic"] * sm
        )
        c["rerank_score"] = round(rerank, 4)
        c["rerank_components"] = {
            "financial_fact_exists": fact_exists, "metric": mm, "value": vm,
            "period": pm, "growth": gm, "table": tm, "semantic": sm,
        }

    # 只排序，不删除候选（rerank_score 主序，final_score 兜底）
    # Phase 23.26 Step 3：fact 去重降权——同一 financial_object（source_blocks 相同）
    # 被窗口重建附加到多个块时，仅第一个保留完整分，其余共享块降权（避免同事实霸占 top-K）
    seen_fact_keys: dict[str, int] = {}
    for c in candidates:
        ff = c.get("financial_fact") or {}
        if ff:
            src_key = tuple(sorted(str(b) for b in ff.get("source_blocks", []))) or (str(c.get("block_id")),)
            if src_key in seen_fact_keys:
                # 重复事实：降权 0.5（仍保留在候选，不删除）
                c["rerank_score"] = round(c.get("rerank_score", 0.0) * 0.5, 4)
            else:
                seen_fact_keys[src_key] = c.get("block_id")
    candidates.sort(key=lambda c: (-c.get("rerank_score", 0.0), -c.get("final_score", 0.0)))
    return candidates
