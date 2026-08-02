"""证据检索服务（Phase 4A Oracle 模式）——编排：文档过滤 → 块候选 → 评分 → Top-K。"""

import json
import re
import time

from sqlalchemy.orm import Session

from app.models import Document, DocumentBlock
from app.models.evidence import EvidenceCandidate, EvidenceRetrievalRun
from app.services.evidence_retrieval.engine import (
    DEFAULT_WEIGHTS,
    EVIDENCE_TYPE_PRIMARY,
    classify_evidence_type,
    document_priority,
    metric_aliases,
    normalize_claim,
    score_block,
)

MIN_CANDIDATE_SCORE = 0.05  # 低于该分的块不进入候选

# 数据集 → 金标准主张文件（Oracle 输入；仅 gold_claims，不读 gold_evidence/gold_verifications）
DATASET_GOLD_PATHS = {
    "demo": "data/demo/annotations/gold_claims.json",
    "holdout": "data/holdout/annotations/gold_claims.json",
}


def load_gold_claims(dataset: str) -> list[dict]:
    """读取数据集金标准主张（ORACLE_GOLD 输入）。"""
    from pathlib import Path

    from app.core.config import BASE_DIR

    path = Path(BASE_DIR) / DATASET_GOLD_PATHS[dataset]
    if not path.exists():
        raise FileNotFoundError(f"数据集 {dataset} 金标准不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))["claims"]


def filter_documents(session: Session, claim: dict) -> list[Document]:
    """第一层文档过滤：同公司/代码 + 真实披露（SOURCE_DOCUMENT），按财报类型/时间优先排序。

    排序：主张期间类型匹配的财报优先（2025H1 → 半年报、2025FY → 年报、2025Q1 → 一季报），
    其余同公司文档按期间类型距离兜底。
    """
    # Phase 23.7：兼容 gold_claims 的 `entity` 字段（原仅读 `entity_name` 导致公司过滤失效）
    entity = (claim.get("entity_name") or claim.get("entity") or claim.get("company") or "").strip()
    stock = (claim.get("stock_code") or "").strip()
    q = session.query(Document).filter(Document.document_role == "SOURCE_DOCUMENT")
    if entity:
        q = q.filter(Document.company_name == entity)
    if stock:
        q = q.filter(Document.stock_code == stock)
    docs = q.order_by(Document.id).all()
    if not docs and stock:
        docs = (
            session.query(Document)
            .filter(Document.document_role == "SOURCE_DOCUMENT", Document.stock_code == stock)
            .all()
        )
    return sorted(docs, key=lambda d: (document_priority(claim.get("period"), d.report_period), d.id))


def _candidate_blocks(session: Session, doc: Document, aliases: set[str]):
    """全文检索候选：指标别名预筛（含数字的指标行优先），MVP 规模直接扫描。

    返回 [(block, page_number)]；page_number 来自 document_pages（1 基物理页码）。
    """
    from app.models import DocumentPage

    like_patterns = [f"%{a}%" for a in sorted(aliases, key=lambda a: -len(a))][:8]
    if not like_patterns:
        return []
    cond = DocumentBlock.text.like(like_patterns[0])
    for p in like_patterns[1:]:
        cond = cond | DocumentBlock.text.like(p)
    rows = (
        session.query(DocumentBlock, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .filter(DocumentBlock.document_id == doc.id, cond)
        .order_by(DocumentPage.page_index, DocumentBlock.reading_order)
        .all()
    )
    return rows


def _page_section_flag(session: Session, page_id: int, cache: dict) -> bool:
    """页面是否处于管理层讨论/经营分析章节（标题块命中 section 关键词）。"""
    if page_id in cache:
        return cache[page_id]
    from app.services.evidence_retrieval.engine import section_matches

    headings = (
        session.query(DocumentBlock)
        .filter(DocumentBlock.page_id == page_id, DocumentBlock.heading_level > 0)
        .all()
    )
    flag = any(section_matches(h.text or "") for h in headings)
    cache[page_id] = flag
    return flag


def retrieve_for_claim(
    session: Session,
    claim: dict,
    top_k: int = 5,
    weights: dict | None = None,
    max_blocks_per_doc: int = 400,
) -> list[dict]:
    """单条主张检索：返回按 final_score 降序的 Top-K 证据候选。

    输出元素：{rank, document_id, page_number, block_id, final_score,
              metric_score, value_score, period_score, entity_score, text_score,
              matched_terms, block_text, retrieval_method}
    """
    claim = normalize_claim(claim)
    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))
    # 仅保留可用于中文文本匹配的别名；无中文别名（语义主张/代码指标）回退原文关键词
    chinese_aliases = {a for a in aliases if re.search(r"[\u4e00-\u9fff]", a)}
    if not chinese_aliases:
        from app.services.evidence_retrieval.engine import _text_keywords

        chinese_aliases = set(_text_keywords(claim.get("original_text") or ""))
    aliases = chinese_aliases or aliases
    if not aliases:
        return []

    scored: list[dict] = []
    section_cache: dict[int, bool] = {}
    for doc in filter_documents(session, claim):
        for block, page_number in _candidate_blocks(session, doc, aliases):
            if len(scored) >= max_blocks_per_doc:
                break
            if not block.text:
                continue
            s = score_block(
                block.text, claim,
                doc_period=doc.report_period,
                weights=weights,
                section_bonus=1.0 if _page_section_flag(session, block.page_id, section_cache) else 0.0,
            )
            if s["final_score"] < MIN_CANDIDATE_SCORE:
                continue
            scored.append(
                {
                    "document_id": doc.id,
                    "page_number": page_number,
                    "block_id": block.id,
                    "page_id": block.page_id,
                    "y0": block.y0 or 0.0,
                    "reading_order": block.reading_order or 0,
                    **s,
                    "block_text": block.text[:300],
                }
            )
    if not scored:
        return []

    # ---- Phase 4A.5：表格感知 + 页面/表格加分（块级加成，保持 block 级排序）----
    # 实测结论：页面级重排（按页面分排序 + 每页上限）在两个变体（max / top-2 之和）
    # 下均使 Hit@K 回退（Demo Hit@5 0.25→0.167），故回退为 block 级排序；
    # page_bonus（同页指标+数值+期间）与 table_bonus（表格区域）作为块级加分保留。
    from collections import defaultdict

    w = weights or DEFAULT_WEIGHTS
    page_blocks: dict[tuple, list[dict]] = defaultdict(list)
    for b in scored:
        page_blocks[(b["document_id"], b["page_number"])].append(b)

    for (doc_id, pn), blocks in page_blocks.items():
        has_metric = any(b["metric_score"] > 0 for b in blocks)
        has_value = any(b["value_score"] > 0 for b in blocks)
        has_period = any(b["period_score"] > 0 for b in blocks)
        page_bonus = 1.0 if (has_metric and has_value and has_period) else 0.0
        # 表格区域：y 坐标分桶（5pt）+ 桶内同时含指标块与数字块；单块表格行（指标+数字同块）同样标记
        buckets: dict[int, list[dict]] = defaultdict(list)
        for b in blocks:
            buckets[round(b["y0"] / 5.0)].append(b)
        table_blocks: set[int] = set()
        for bucket in buckets.values():
            has_metric_b = any(b["metric_score"] > 0 for b in bucket)
            has_number_b = any(re.search(r"\d", b["block_text"] or "") for b in bucket)
            if has_metric_b and has_number_b:
                table_blocks.update(b["block_id"] for b in bucket)
        for b in blocks:
            b["page_bonus"] = page_bonus
            b["table_region"] = b["block_id"] in table_blocks
            # Phase 4A.6：证据类型分级 + 质量分 + 排名原因（多证据分层）
            section_flag = _page_section_flag(session, b["page_id"], section_cache)
            etype, qscore, reason = classify_evidence_type(
                b["block_text"], is_table_region=b["table_region"], is_management_section=section_flag
            )
            b["evidence_type"] = etype
            b["evidence_quality_score"] = qscore
            b["evidence_rank_reason"] = reason
            b["evidence_tier"] = "primary" if etype == EVIDENCE_TYPE_PRIMARY else "secondary"
            b["final_score"] = round(
                b["final_score"]
                + w.get("page", 0.10) * page_bonus
                + w.get("table", 0.05) * (1.0 if b["block_id"] in table_blocks else 0.0)
                + w.get("evidence_quality", 0.10) * qscore,
                4,
            )

    scored.sort(key=lambda b: -b["final_score"])
    final = scored[:top_k]
    for i, c in enumerate(final, start=1):
        c["rank"] = i
    return final


def run_retrieval(
    session: Session,
    dataset: str = "demo",
    input_mode: str = "ORACLE_GOLD",
    top_k: int = 5,
    version: str = "v2",
) -> EvidenceRetrievalRun:
    """执行一次证据检索任务：逐条金标准主张 → Top-K 候选 → 持久化。

    - 输入仅使用 gold_claims（ORACLE_GOLD）；不读取 gold_evidence/gold_verifications；
    - 排序逻辑不使用任何 gold 答案（仅文档文本 + 结构化匹配）。
    """
    weights = ensure_retrieval_config(session, version)
    claims = load_gold_claims(dataset)

    run = EvidenceRetrievalRun(
        dataset=dataset,
        input_mode=input_mode,
        status="RUNNING",
        top_k=top_k,
        retrieval_version=version,
        claim_count=len(claims),
    )
    session.add(run)
    session.commit()

    start = time.monotonic()
    try:
        for claim in claims:
            cid = claim.get("claim_id") or claim.get("original_text", "")[:32]
            candidates = retrieve_for_claim(session, claim, top_k=top_k, weights=weights)
            for c in candidates:
                session.add(
                    EvidenceCandidate(
                        retrieval_run_id=run.id,
                        claim_id=cid,
                        document_id=c["document_id"],
                        page_number=c["page_number"],
                        block_id=c["block_id"],
                        rank=c["rank"],
                        final_score=c["final_score"],
                        metric_score=c["metric_score"],
                        value_score=c["value_score"],
                        period_score=c["period_score"],
                        entity_score=c["entity_score"],
                        text_score=c["text_score"],
                        matched_terms=json.dumps(c.get("matched_terms", []), ensure_ascii=False),
                        retrieval_method="structured",
                        evidence_type=c.get("evidence_type", "UNKNOWN"),
                        evidence_quality_score=c.get("evidence_quality_score", 0.3),
                        evidence_rank_reason=c.get("evidence_rank_reason"),
                    )
                )
        run.status = "COMPLETED"
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        run = session.get(EvidenceRetrievalRun, run.id)
        run.status = "FAILED"
        run.duration_ms = int((time.monotonic() - start) * 1000)
        session.commit()
        raise
    run.duration_ms = int((time.monotonic() - start) * 1000)
    session.commit()
    return run


def get_run_claims(session: Session, run_id: int) -> dict[str, list[dict]]:
    """按 claim_id 聚合候选（供 API 与前端展示）。"""
    rows = (
        session.query(EvidenceCandidate)
        .filter(EvidenceCandidate.retrieval_run_id == run_id)
        .order_by(EvidenceCandidate.claim_id, EvidenceCandidate.rank)
        .all()
    )
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r.claim_id, []).append(
            {
                "rank": r.rank,
                "document_id": r.document_id,
                "page_number": r.page_number,
                "block_id": r.block_id,
                "final_score": r.final_score,
                "metric_score": r.metric_score,
                "value_score": r.value_score,
                "period_score": r.period_score,
                "entity_score": r.entity_score,
                "text_score": r.text_score,
                "matched_terms": json.loads(r.matched_terms or "[]"),
                "retrieval_method": r.retrieval_method,
                "evidence_type": r.evidence_type,
                "evidence_quality_score": r.evidence_quality_score,
                "evidence_rank_reason": r.evidence_rank_reason,
                "evidence_tier": "primary" if r.evidence_type == EVIDENCE_TYPE_PRIMARY else "secondary",
            }
        )
    return out


def ensure_retrieval_config(session: Session, version: str = "v1") -> dict:
    """确保权重配置持久化（可配置/可解释/存库）：缺省写入 v1 默认权重，返回当前权重。"""
    from app.models.evidence import EvidenceRetrievalConfig

    row = session.query(EvidenceRetrievalConfig).filter(EvidenceRetrievalConfig.version == version).first()
    if row is None:
        import json

        row = EvidenceRetrievalConfig(
            version=version,
            weights_json=json.dumps(DEFAULT_WEIGHTS, ensure_ascii=False),
            description="Phase 4A 默认权重：metric 0.30 / value 0.25 / period 0.20 / entity 0.10 / text 0.15",
        )
        session.add(row)
        session.commit()
    return load_weights(session, version)


def load_weights(session: Session, version: str = "v1") -> dict:
    """从 evidence_retrieval_configs 读取权重（可配置/可解释/存库），缺省回退默认值。"""
    from app.models.evidence import EvidenceRetrievalConfig

    row = session.query(EvidenceRetrievalConfig).filter(EvidenceRetrievalConfig.version == version).first()
    if row and row.weights_json:
        import json

        return {**DEFAULT_WEIGHTS, **json.loads(row.weights_json)}
    return dict(DEFAULT_WEIGHTS)
