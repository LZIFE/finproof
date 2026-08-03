"""Phase 23.10 — 两阶段 Evidence Retrieval。

Stage A：高召回候选生成（目标 Page Candidate Recall@50 ≥0.95 / Block @50 ≥0.90）
- 多 query（QueryPlanner 7 类 query 文本做 LIKE 全量扫描）
- fallback：无规范别名时全量扫描含数字块（避免 No-result）
- 来源标注：query_contributions（每个 query 贡献的 block_ids）
- 输出 Top 50 候选（含 TableContext enriched 上下文）

Stage B：Table-aware Reranker（目标 Top5 命中）
- 对每个候选计算 15+ 特征分数：
  lexical / semantic / entity / metric / numeric / period / unit / scope /
  table_title / row_header / column_header / neighboring_context /
  document_type / source_priority / wrong_period_penalty / wrong_metric_penalty /
  duplicate_penalty / narrative_table_penalty / final_score
- 禁止使用 Gold Page / Gold Block / expected_verdict 作为特征
- 去重 + 每页/每表上限（配合任务十：多样性控制）
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.models import DocumentBlock, DocumentPage
from app.services.evidence_retrieval.engine import (
    DEFAULT_WEIGHTS,
    _block_value_hits,
    _clean_numbers,
    entity_matches,
    metric_aliases,
    metric_hits,
    period_matches,
    text_similarity,
)
from app.services.evidence_retrieval.query_planner import QueryPlanner
from app.services.evidence_retrieval.table_context import build_table_contexts

MIN_CANDIDATE_SCORE = 0.05

# Stage B 默认权重（表感知特征 + 基础分量）
STAGE_B_WEIGHTS: dict[str, float] = {
    "lexical": 0.10, "semantic": 0.10, "entity": 0.10, "metric": 0.15,
    "numeric": 0.15, "period": 0.10, "unit": 0.05, "scope": 0.05,
    "table_title": 0.05, "row_header": 0.10, "column_header": 0.05,
    "neighboring_context": 0.05, "document_type": 0.03, "source_priority": 0.02,
}
_PENALTY_WRONG_PERIOD = 0.3
_PENALTY_WRONG_METRIC = 0.5
_PENALTY_DUPLICATE = 0.6
_PENALTY_NARRATIVE_TABLE = 0.7


@dataclass
class StageCandidate:
    document_id: int | None = None
    page_number: int | None = None
    block_id: int | None = None
    block_text: str = ""
    enriched_text: str = ""
    query_contributions: list = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    final_score: float = 0.0
    table_id: str = ""
    table_region: bool = False

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id, "page_number": self.page_number,
            "block_id": self.block_id, "final_score": round(self.final_score, 4),
            "query_contributions": self.query_contributions,
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "enriched_text": self.enriched_text[:300],
            "table_id": self.table_id,
        }


def _norm(s: str) -> str:
    return "".join(s.split())


def stage_a_candidates(session, claim: dict, top_k: int = 50,
                       max_blocks_per_doc: int = 6000) -> list[StageCandidate]:
    """Stage A：高召回候选生成（多 query + 全量扫描 fallback + TableContext）。

    返回候选列表（含 query_contributions 与 enriched_text）。
    """
    from app.services.evidence_retrieval.service import filter_documents

    plan = QueryPlanner(claim).build()
    aliases = set(plan.metric_aliases)
    cn_aliases = [a for a in aliases if re.search(r"[\u4e00-\u9fff]", a)]
    # query 文本集（LIKE 模式）
    query_texts: list[tuple[str, str]] = []
    for q in plan.queries:
        query_texts.append((q.query_id, q.query_text))
    # 扩展：指标中文别名 + 期间别名 + 单位
    qkw = set(cn_aliases) | set(plan.period_aliases)
    if plan.unit:
        qkw.add(plan.unit)
    query_texts.append(("q_all", " ".join(a for a in qkw if a)[:200]))

    # 扩展：原文关键词 query（语义类/推导类 claim 的召回）
    plan_kw = [k for k in plan.keywords if k][:8]
    if plan_kw:
        query_texts.append(("q_text", " ".join(plan_kw)[:200]))

    # 候选：先按 alias LIKE 过滤（与 phase23.9 相同），无中文别名时全量扫描
    # 推导类（gross_margin/net_margin 及 margin 族变体）与语义类（无 value）也全量扫描
    # 含数字块：利润表块不含"毛利率"字样但含收入/成本数字，可推导毛利率（Phase 23.10）
    std_metric_name = str(claim.get("metric") or "").lower()
    is_derived = ("margin" in std_metric_name or std_metric_name in ("gross_margin", "net_margin"))
    claim_value_flag = claim.get("value") if isinstance(claim.get("value"), (int, float)) else None
    use_fallback = (not cn_aliases) or is_derived or claim_value_flag is None
    scored: list[StageCandidate] = []
    seen_blocks: set = set()
    contrib: dict[int, list[str]] = defaultdict(list)

    from app.services.evidence_retrieval.service import _candidate_blocks

    for doc in filter_documents(session, claim):
        # use_fallback 时传空 aliases → _candidate_blocks 全量扫描（推导类/语义类
        # 的 gold 页如利润表不含指标别名"毛利率"，必须全量扫描才能召回）
        rows = _candidate_blocks(session, doc, set() if use_fallback else set(cn_aliases))
        for block, page_number in rows:
            if len(scored) >= max_blocks_per_doc:
                break
            if block.id in seen_blocks:
                continue
            if not block.text:
                continue
            # 记录 query 贡献（文本匹配哪个 query）
            blk_norm = _norm(block.text)
            hits_q = []
            for qid, qt in query_texts:
                if qt and (all(tok in blk_norm or tok in block.text for tok in re.findall(r"[\u4e00-\u9fff]{2,}", qt)[:3])):
                    hits_q.append(qid)
            # 无 query 命中但含数字 → fallback 保底
            if not hits_q and (not use_fallback and not re.search(r"\d", block.text)):
                continue
            if not hits_q and use_fallback and not re.search(r"\d", block.text):
                continue
            seen_blocks.add(block.id)
            contrib[block.id].extend(hits_q or ["q_fallback"])
            scored.append(StageCandidate(
                document_id=doc.id, page_number=page_number, block_id=block.id,
                block_text=block.text,
            ))

    # TableContext 注入（enriched_text + table_id + table_region）
    table_ctx_by_block: dict[int, dict] = {}
    for cand in scored:
        ctxs = build_table_contexts(session, cand.document_id, cand.page_number)
        for c in ctxs:
            for bid in c.source_block_ids:
                table_ctx_by_block[bid] = c.to_dict()
    for cand in scored:
        tctx = table_ctx_by_block.get(cand.block_id)
        if tctx:
            cand.enriched_text = tctx["enriched_text"]
            cand.table_id = tctx["table_id"]
            cand.table_region = bool(tctx.get("row_header") or tctx.get("value"))
    # query contributions
    for cand in scored:
        cand.query_contributions = contrib.get(cand.block_id, [])

    # Stage A 粗排序（召回优先）：metric + value + table_region 主导，
    # 不得加入文本长度加成（长叙述块会虚高占满 Top50，把 Gold 财务数据行挤出——
    # NARRATIVE_OVER_TABLE 修复，Phase 23.10）
    claim_value = claim.get("value") if isinstance(claim.get("value"), (int, float)) else None
    claim_unit = claim.get("unit") or ""
    derived_terms = ("营业收入", "营业成本", "营业总收入", "净利润", "归属于上市公司股东的净利润")
    for cand in scored:
        text = cand.block_text or ""
        cand.scores["stage_a_metric"] = 1.0 if any(a and a in text for a in cn_aliases) else 0.0
        # 推导类（毛利率/净利率）的 gold 页是利润表（含收入/成本成分词，不含"毛利率"字样）
        if is_derived and cand.scores["stage_a_metric"] == 0.0 and any(k in text for k in derived_terms):
            cand.scores["stage_a_metric"] = 1.0
        cand.scores["stage_a_value"] = 0.0
        if claim_value is not None:
            ok, _r = _block_value_hits(text, claim_value, claim_unit or None)
            cand.scores["stage_a_value"] = 1.0 if ok else 0.0
        cand.scores["stage_a_table"] = 1.0 if cand.table_region else 0.0
        # 含大财务数字（≥6 位）的表格块加成：财务数据行特征
        cand.scores["stage_a_big_number"] = 1.0 if re.search(r"\d{6,}", text) else 0.0
        cand.final_score = (3.0 * cand.scores["stage_a_metric"]
                            + 5.0 * cand.scores["stage_a_value"]
                            + 2.0 * cand.scores["stage_a_table"]
                            + 1.0 * cand.scores["stage_a_big_number"])
    scored.sort(key=lambda c: -c.final_score)
    return scored[:top_k]


def stage_b_rerank(session, claim: dict, candidates: list[StageCandidate],
                   top_k: int = 5, weights: dict | None = None) -> list[StageCandidate]:
    """Stage B：Table-aware Reranker。

    特征计算（全部基于 block/enriched 文本 + claim，不使用 Gold）：
    - lexical：文本关键词命中（Jaccard）
    - semantic：text_similarity（引擎余弦/词面）
    - entity：company 匹配
    - metric：metric_hits（指标别名命中）
    - numeric：_block_value_hits（claim 数值命中）
    - period：period_matches（claim 期间 vs block+doc_period）
    - unit：块内单位与 claim 单位一致性
    - scope：块口径与 claim 口径一致性
    - table_title / row_header / column_header / neighboring_context：
      enriched_text 中对应段的关键词命中
    - document_type / source_priority：文档期间优先级
    惩罚：wrong_period / wrong_metric / duplicate / narrative_table
    """
    w = {**STAGE_B_WEIGHTS, **(weights or {})}
    claim_value = claim.get("value") if isinstance(claim.get("value"), (int, float)) else None
    claim_unit = claim.get("unit") or ""
    claim_period = claim.get("period") or ""
    claim_entity = claim.get("entity") or claim.get("entity_name") or ""
    claim_scope = claim.get("scope") or "consolidated"
    claim_text = claim.get("original_text") or claim.get("source_text") or ""
    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))

    # 去重（相同 block_id / 高文本相似度 / 同页同表）
    seen_block: set = set()
    seen_page: dict[tuple, int] = defaultdict(int)
    seen_table: dict[str, int] = defaultdict(int)
    seen_texts: list[str] = []
    deduped: list[StageCandidate] = []
    for c in candidates:
        if c.block_id in seen_block:
            continue
        # 高文本相似度去重（与已保留候选归一化文本相同/包含，防止同表重复行挤占）
        cnorm = _norm(c.block_text or "")
        if cnorm and any(cnorm == _norm(t) or cnorm in _norm(t) or _norm(t) in cnorm
                         for t in seen_texts[-8:]):
            continue
        # 每页上限 12、每表上限 8（任务十：多样性控制）
        if seen_page[(c.document_id, c.page_number)] >= 12:
            continue
        if c.table_id and seen_table[c.table_id] >= 8:
            continue
        seen_block.add(c.block_id)
        seen_page[(c.document_id, c.page_number)] += 1
        if c.table_id:
            seen_table[c.table_id] += 1
        if cnorm:
            seen_texts.append(cnorm)
        deduped.append(c)

    results: list[StageCandidate] = []
    for c in deduped:
        text = c.block_text or ""
        enriched = c.enriched_text or text
        # lexical（关键词共现比例）
        q_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}", claim_text))
        b_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}", text))
        lexical = len(q_tokens & b_tokens) / len(q_tokens) if q_tokens else 0.0
        # semantic
        semantic = text_similarity(claim_text, text)
        # entity
        entity = entity_matches(text, claim_entity) if claim_entity else 0.0
        # metric
        hits = metric_hits(text, aliases)
        metric = 1.0 if hits else 0.0
        # numeric
        numeric = 0.0
        if claim_value is not None:
            ok, _reason = _block_value_hits(text, claim_value, claim_unit or None)
            numeric = 1.0 if ok else 0.0
        # period（用 enriched 中的期间段）
        period = period_matches(claim_period, enriched, None)
        # unit：claim 单位是否在文本/enriched 中
        unit = 1.0 if (claim_unit and claim_unit in text) else 0.0
        # scope
        scope_txt = text + enriched
        scope = 1.0
        if "归母" in scope_txt and claim_scope in ("consolidated", "reported"):
            scope = 0.0
        if "扣非" in scope_txt and claim_scope == "consolidated":
            scope = 0.0
        # table 特征
        table_title = 1.0 if ("表格：" in enriched or "章节：" in enriched) else 0.0
        row_header = 1.0 if ("指标：" in enriched or "指标标签：" in enriched) else 0.0
        column_header = 1.0 if ("列：" in enriched or "期间：" in enriched) else 0.0
        neighboring = 1.0 if ("相邻行：" in enriched or "相邻列：" in enriched) else 0.0
        # document_type / source_priority（期初期中：年报优先）
        doc_type = 1.0 if "FY" in str(claim_period) else 0.5
        source_priority = 1.0

        final = (w["lexical"] * lexical + w["semantic"] * semantic + w["entity"] * entity
                 + w["metric"] * metric + w["numeric"] * numeric + w["period"] * period
                 + w["unit"] * unit + w["scope"] * scope + w["table_title"] * table_title
                 + w["row_header"] * row_header + w["column_header"] * column_header
                 + w["neighboring_context"] * neighboring + w["document_type"] * doc_type
                 + w["source_priority"] * source_priority)
        # 惩罚
        if claim_period and period == 0.0:
            final *= _PENALTY_WRONG_PERIOD
        if claim_value is not None and metric == 0.0 and numeric == 1.0:
            final *= _PENALTY_WRONG_METRIC
        if not c.table_region and numeric == 1.0 and metric == 0.0:
            final *= _PENALTY_NARRATIVE_TABLE
        c.scores = {
            "lexical_score": lexical, "semantic_score": semantic, "entity_score": entity,
            "metric_score": metric, "numeric_score": numeric, "period_score": period,
            "unit_score": unit, "scope_score": scope, "table_title_score": table_title,
            "row_header_score": row_header, "column_header_score": column_header,
            "neighboring_context_score": neighboring, "document_type_score": doc_type,
            "source_priority_score": source_priority,
        }
        c.final_score = round(final, 4)
        results.append(c)

    results.sort(key=lambda c: -c.final_score)
    return results[:top_k]


def retrieve_for_claim_v2(session, claim: dict, top_k: int = 5,
                          stage_a_top: int = 50, weights: dict | None = None) -> list[dict]:
    """两阶段检索入口：Stage A（Top50）→ Stage B（Top K）。"""
    a = stage_a_candidates(session, claim, top_k=stage_a_top)
    b = stage_b_rerank(session, claim, a, top_k=top_k, weights=weights)
    out = []
    for i, c in enumerate(b, start=1):
        out.append({
            "rank": i, "document_id": c.document_id, "page_number": c.page_number,
            "block_id": c.block_id, "final_score": round(c.final_score, 4),
            "scores": {k: round(v, 4) for k, v in c.scores.items()},
            "query_contributions": c.query_contributions,
            "block_text": c.block_text[:300],
            "enriched_text": c.enriched_text[:300],
            "table_id": c.table_id,
        })
    return out


__all__ = ["StageCandidate", "stage_a_candidates", "stage_b_rerank", "retrieve_for_claim_v2", "STAGE_B_WEIGHTS"]
