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

    Phase 23.13：Entity 反查放宽——entity 精确匹配失败时，用实体别名表
    （全称/简称/股票代码/历史名）反查 company_name，避免"公司简称对不上"整组漏召回。
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
    # Phase 23.13 Stage 1：精确匹配无结果 → Entity 别名反查（全称/简称/代码/英文名）
    if not docs and entity:
        from app.services.evidence_retrieval.engine import _ENTITY_ALIASES

        aliases = _ENTITY_ALIASES.get(entity, set())
        # 双向反查：entity 是别名值（如 "Midea"/"五粮液"/"000333"）时，
        # 反向遍历别名表找含该值的键对应的全组别名
        if not aliases:
            for _full, _aliases in _ENTITY_ALIASES.items():
                if entity in _aliases:
                    aliases = _aliases
                    break
        if aliases:
            docs = (
                session.query(Document)
                .filter(Document.document_role == "SOURCE_DOCUMENT")
                .filter(Document.company_name.in_(aliases))
                .order_by(Document.id)
                .all()
            )
        # 别名表未命中：尝试 company_name 含 entity 前 2 字（简称放宽，如"五粮液"→"宜宾五粮液"）
        if not docs and len(entity) >= 2:
            short = entity[:2]
            docs = (
                session.query(Document)
                .filter(Document.document_role == "SOURCE_DOCUMENT",
                        Document.company_name.like(f"%{short}%"))
                .order_by(Document.id)
                .all()
            )
    return sorted(docs, key=lambda d: (document_priority(claim.get("period"), d.report_period), d.id))


_FALLBACK = object()  # 候选 fallback 标记：aliases 为空时退化为「含数字的块全部进候选」

# Phase 23.14 Step 3：Evidence Window 扩展半径（同页 ±3 块）与同表 y-range 阈值
_WINDOW_RADIUS = 3
_WINDOW_Y_TOLERANCE = 60.0  # 同表行 y0 允许偏差（pt）


def _evidence_window(
    session: Session,
    doc_id: int,
    page_id: int,
    block_index: int,
    y0: float,
    radius: int = _WINDOW_RADIUS,
) -> list[int]:
    """命中 block 后扩展 Evidence Window：同页 ±radius 块 + 同表 y-range 块。

    返回窗口内 block_ids（含命中块本身），按 block_index 升序。
    用途：指标行/数值行/表头/单位被拆成多个 block 时，窗口内聚合可完整表达事实。
    """
    rows = (
        session.query(DocumentBlock)
        .filter(DocumentBlock.document_id == doc_id, DocumentBlock.page_id == page_id)
        .order_by(DocumentBlock.block_index)
        .all()
    )
    if not rows:
        return []
    idx_list = [r.block_index or 0 for r in rows]
    try:
        pos = idx_list.index(block_index)
    except ValueError:
        pos = None
    window: set[int] = set()
    if pos is not None:
        lo, hi = max(0, pos - radius), min(len(rows), pos + radius + 1)
        for r in rows[lo:hi]:
            window.add(r.id)
    # 同表 y-range：y0 与命中块接近的块（表格行）
    if y0 is not None:
        for r in rows:
            if r.y0 is not None and abs((r.y0 or 0) - y0) <= _WINDOW_Y_TOLERANCE:
                window.add(r.id)
    return sorted(window)


def _candidate_blocks(session: Session, doc: Document, aliases: set[str]):
    """全文检索候选：指标别名预筛（含数字的指标行优先），MVP 规模直接扫描。

    返回 [(block, page_number)]；page_number 来自 document_pages（1 基物理页码）。
    aliases 命中的块全部保留；aliases 为空 OR 块含数字时也保留（fallback 到含数字块）。
    """
    from app.models import DocumentPage

    like_patterns = [f"%{a}%" for a in sorted(aliases, key=lambda a: -len(a))][:8]
    base_q = (
        session.query(DocumentBlock, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .filter(DocumentBlock.document_id == doc.id)
    )
    if like_patterns:
        cond = DocumentBlock.text.like(like_patterns[0])
        for p in like_patterns[1:]:
            cond = cond | DocumentBlock.text.like(p)
        rows = base_q.filter(cond).order_by(DocumentPage.page_index, DocumentBlock.reading_order).all()
    else:
        rows = base_q.order_by(DocumentPage.page_index, DocumentBlock.reading_order).all()
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
    max_blocks_per_doc: int = 4000,
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
    # fallback 判定必须在原文关键词覆盖之前：规范 metric 中文别名为空
    # （quarterly_revenue / scope 类）→ 含数字块全部进候选，避免 NO_RESULT
    fallback_mode = not chinese_aliases
    if not chinese_aliases:
        from app.services.evidence_retrieval.engine import _text_keywords

        chinese_aliases = set(_text_keywords(claim.get("original_text") or ""))
    # 并集而非覆盖：metric_aliases 的规范中文别名始终参与（Phase 23.9 修复：
    # CLM-002 等英文代码 claim 的 chinese_aliases 碎片词不得覆盖规范别名）
    aliases = chinese_aliases | aliases

    scored: list[dict] = []
    section_cache: dict[int, bool] = {}
    # fallback_mode 已在第 128 行基于「规范 metric 中文别名」判定（第 139 行旧赋值会
    # 用含原文碎片词的 aliases 覆盖成 False，导致 quarterly/scope 类 NO_RESULT，已删除）
    # fallback 模式下传空 aliases 给 _candidate_blocks → 全量扫描含数字块（碎片词 LIKE 过滤会漏掉 gold 块）
    candidate_aliases = set() if fallback_mode else aliases
    # 页级单位声明缓存：财务表页首"（除特别注明外，金额单位为人民币千元）"在表头块，
    # 数据块（裸数字）评分时注入该单位以命中 value_score（Phase 23.9 修复）
    page_unit_cache: dict[tuple, str | None] = {}

    # Phase 23.15 Step 4：Claim→Section→Table→Block 三级检索
    # 1) claim 路由到目标章节类型
    from app.services.evidence_retrieval.claim_routing import route_sections_for_claim
    from app.services.evidence_retrieval.section_index import (
        section_bonus_for_page,
        target_pages_for_claim,
        table_pages_for_types,
    )

    _routing = route_sections_for_claim(claim)
    target_sections = _routing["sections"]
    # 文档级目标页缓存：{doc_id: set(target_pages)}
    target_pages_cache: dict[int, set[int]] = {}
    # 表格页缓存：{doc_id: set(table_pages)}（目标章节类型的表格页，block 级检索优先）
    table_pages_cache: dict[int, set[int]] = {}

    def _page_unit(session, doc_id: int, page_id: int) -> str | None:
        key = (doc_id, page_id)
        if key not in page_unit_cache:
            from app.models import DocumentBlock

            texts = [b.text or "" for b in session.query(DocumentBlock).filter(DocumentBlock.page_id == page_id).all()]
            joined = "".join(texts)
            m = re.search(r"单位[：:为]?\s*[（(]?(人民币)?\s*(万亿元|亿元|百万元|万元|千元|元)\s*[）)]?", joined)
            page_unit_cache[key] = m.group(2) if m else None
        return page_unit_cache[key]

    for doc in filter_documents(session, claim):
        # Phase 23.15 Step 4：目标章节页集合（claim→section→table 定位，避免全文扫）
        if doc.id not in target_pages_cache:
            target_pages_cache[doc.id] = target_pages_for_claim(doc.id, target_sections)
            table_pages_cache[doc.id] = table_pages_for_types(doc.id, target_sections)
        target_pages = target_pages_cache[doc.id]
        table_pages = table_pages_cache[doc.id]
        # Phase 23.16 Step 2：Hybrid Retrieval 三路召回 union（BM25 + Vector + Rule）
        from app.services.evidence_retrieval.hybrid_retrieval import hybrid_candidates

        hybrid_ids = hybrid_candidates(session, doc.id, claim, target_sections, candidate_aliases)
        # 按 block_id 查 block + page_number（union 候选遍历）
        from app.models import DocumentPage

        if hybrid_ids:
            hybrid_rows = (
                session.query(DocumentBlock, DocumentPage.page_number)
                .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
                .filter(DocumentBlock.document_id == doc.id, DocumentBlock.id.in_(hybrid_ids))
                .order_by(DocumentPage.page_index, DocumentBlock.reading_order)
                .all()
            )
        else:
            hybrid_rows = []
        for block, page_number in hybrid_rows:
            if len(scored) >= max_blocks_per_doc:
                break
            if not block.text:
                continue
            # Phase 23.15 Step 4：目标章节页加分（section→table→block 三级；非目标章节页不加分也不过滤）
            sec_bonus = section_bonus_for_page(doc.id, page_number, target_sections)
            # 表格页优先：目标章节类型的表格页块额外加成
            tbl_bonus = 0.10 if page_number in table_pages else 0.0
            # 数据块无单位但页首有单位声明 → 注入页级单位用于评分（不改变候选文本）
            # 只对「非年份数字」的数据块注入：表头块（"2025年度"等）不含财务数字，注入会虚高
            block_text_for_score = block.text
            has_financial_number = re.search(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", block.text) or re.search(r"(?<!\d)\d{4,}(?!\d)", block.text)
            if has_financial_number and not re.search(r"[万亿千]元", block.text):
                pu = _page_unit(session, doc.id, block.page_id)
                if pu:
                    block_text_for_score = f"（单位：人民币{pu}）\n{block.text}"
            s = score_block(
                block_text_for_score, claim,
                doc_period=doc.report_period,
                weights=weights,
                section_bonus=1.0 if _page_section_flag(session, block.page_id, section_cache) else 0.0,
            )
            # Phase 23.15 Step 4：目标章节页/表格页块加分（权重 0.10，与 evidence_quality 同量级）
            if sec_bonus > 0 or tbl_bonus > 0:
                s["final_score"] = round(s["final_score"] + 0.10 * sec_bonus + tbl_bonus, 4)
            if s["final_score"] < MIN_CANDIDATE_SCORE:
                # fallback 模式：含数字的块保底进入候选（避免 quarterly/scope 类 No-result）
                if not (fallback_mode and re.search(r"\d", block.text)):
                    continue
                s["final_score"] = MIN_CANDIDATE_SCORE
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
            # Phase 23.14 Step 3：Evidence Window 扩展——命中块后把同页 ±3 块 /
            # 同表 y-range 块补充进候选池（指标/数值/表头/单位分块时窗口聚合才能表达事实）
            win_ids = _evidence_window(session, doc.id, block.page_id, block.block_index or 0, block.y0 or 0.0)
            if len(win_ids) > 1:
                win_rows = (
                    session.query(DocumentBlock)
                    .filter(DocumentBlock.id.in_(win_ids))
                    .order_by(DocumentBlock.block_index)
                    .all()
                )
                seen_win = {(b["document_id"], b["block_id"]) for b in scored}
                for wb in win_rows:
                    if (doc.id, wb.id) in seen_win:
                        continue
                    if len(scored) >= max_blocks_per_doc:
                        break
                    if not wb.text:
                        continue
                    wtext = wb.text
                    has_financial_number = re.search(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", wb.text) or re.search(r"(?<!\d)\d{4,}(?!\d)", wb.text)
                    if has_financial_number and not re.search(r"[万亿千]元", wb.text):
                        pu = _page_unit(session, doc.id, wb.page_id)
                        if pu:
                            wtext = f"（单位：人民币{pu}）\n{wb.text}"
                    ws = score_block(
                        wtext, claim,
                        doc_period=doc.report_period,
                        weights=weights,
                        section_bonus=1.0 if _page_section_flag(session, wb.page_id, section_cache) else 0.0,
                    )
                    if ws["final_score"] < MIN_CANDIDATE_SCORE:
                        # 窗口块保底：含数字/指标的窗口块进入候选（不提前丢弃）
                        if not (re.search(r"\d", wb.text) or ws["metric_score"] > 0):
                            continue
                        ws["final_score"] = MIN_CANDIDATE_SCORE
                    scored.append(
                        {
                            "document_id": doc.id,
                            "page_number": page_number,
                            "block_id": wb.id,
                            "page_id": wb.page_id,
                            "y0": wb.y0 or 0.0,
                            "reading_order": wb.reading_order or 0,
                            **ws,
                            "block_text": wb.text[:300],
                            "retrieval_method": "evidence_window",
                            "window_anchor_block_id": block.id,
                        }
                    )
                    seen_win.add((doc.id, wb.id))
    # ---- Phase 23.13 Stage 3：Broad Page Retrieval（不提前丢弃）----
    # 精准候选不足（别名预筛/文档过滤命中少）时，放宽到 company 匹配 + 全文关键词：
    # 用空 aliases 全量扫描含数字块补充候选，避免"正确 evidence 未召回"。
    # 补充上限：至少覆盖 top_k，且不超过 max_blocks_per_doc。
    broad_cap = min(max_blocks_per_doc, max(50, top_k * 4))
    if len(scored) < min(top_k, 10) and len(scored) < broad_cap:
        seen_ids = {(b["document_id"], b["block_id"]) for b in scored}
        for doc in filter_documents(session, claim):
            for block, page_number in _candidate_blocks(session, doc, set()):
                if (doc.id, block.id) in seen_ids:
                    continue
                if len(scored) >= broad_cap:
                    break
                if not block.text:
                    continue
                s = score_block(
                    block.text, claim,
                    doc_period=doc.report_period,
                    section_bonus=1.0 if _page_section_flag(session, block.page_id, section_cache) else 0.0,
                )
                if s["final_score"] < MIN_CANDIDATE_SCORE:
                    # broad 模式：含数字的块保底进入候选（不因低分提前丢弃）
                    if not re.search(r"\d", block.text):
                        continue
                    s["final_score"] = MIN_CANDIDATE_SCORE
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
                        "retrieval_method": "broad_page",
                    }
                )
                seen_ids.add((doc.id, block.id))
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

    # Phase 23.16 Step 3：Evidence Reranker 二级重排（score_block 初排后、top_k 截断前）
    from app.services.evidence_retrieval.reranker import rerank_candidates

    doc_period_any = None
    for d in filter_documents(session, claim):
        doc_period_any = d.report_period
        break
    scored = rerank_candidates(claim, scored, doc_period=doc_period_any)
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
            description="Phase 23.10 权重：metric 0.35 / value 0.30 / period 0.15 / entity 0.10 / text 0.10",
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


# ===========================================================================
# Phase 23.11: Channel dispatch (retrieve_via_channels)
# ===========================================================================

# Route types that prefer structured fact index (Channel A)
_STRUCTURED_ROUTES = frozenset({
    "STRUCTURED_NUMERIC", "TABLE_METRIC",
    "PERIOD_COMPARISON", "SCOPE_VALIDATION",
})
# Route types that prefer narrative evidence (Channel B)
_NARRATIVE_ROUTES = frozenset({
    "NARRATIVE_FACT", "CAUSALITY", "FORECAST",
})


def retrieve_via_channels(
    session: Session,
    claim: dict,
    routing,
    top_k: int = 5,
    weights: dict | None = None,
) -> list[dict]:
    """Channel dispatch hook (Phase 23.11).

    Routes claims to Channel A (structured fact index) or Channel B
    (narrative BM25+semantic) based on ClaimRoutingResult.route.

    Structured routes: Channel A primary, Channel B supplementary.
    Narrative routes: Channel B primary, Channel A supplementary.
    INSUFFICIENTLY_PARSED: Channel B fallback.

    Returns merged + deduplicated candidate list (dict format compatible
    with verify_evidence_set).
    """
    route = routing.route
    candidates: list[dict] = []

    # Channel A: Structured Fact Retrieval (FinancialFactIndex)
    from app.services.financial_fact_index import query_facts

    # Channel B: Narrative Evidence Retrieval (existing retrieve_for_claim)
    def _narrative_candidates() -> list[dict]:
        raw = retrieve_for_claim(session, claim, top_k=top_k, weights=weights)
        # Normalize to verify_evidence_set candidate format
        out = []
        for c in raw:
            out.append({
                "evidence_id": str(c.get("block_id") or "?"),
                "block_id": c.get("block_id"),
                "text": c.get("block_text", "") or "",
                "page": c.get("page_number"),
                "page_number": c.get("page_number"),
                "document_id": c.get("document_id"),
                "final_score": c.get("final_score", 0.0),
                "metric_score": c.get("metric_score", 0.0),
                "value_score": c.get("value_score", 0.0),
                "period_score": c.get("period_score", 0.0),
                "evidence_type": c.get("evidence_type", "UNKNOWN"),
            })
        return out

    # Channel A query
    def _structured_candidates() -> list[dict]:
        facts = query_facts(session, claim, routing, top_k=top_k)
        # Normalize to verify_evidence_set candidate format
        out = []
        for f in facts:
            out.append({
                "evidence_id": f.get("evidence_id") or "?",
                "text": f.get("text", "") or "",
                "page": f.get("page"),
                "page_number": f.get("page"),
                "document_id": f.get("document_id"),
                "table_id": f.get("table_id"),
                "row_header": f.get("row_header"),
                "period_header": f.get("period_header"),
                "unit": f.get("unit"),
                "scope": f.get("scope"),
                "normalized_value": f.get("normalized_value"),
                "final_score": f.get("final_score", 0.0),
                "channel": "A_structured",
            })
        return out

    # Dispatch based on route
    if route in _STRUCTURED_ROUTES:
        # Channel A primary
        candidates.extend(_structured_candidates())
        # Channel B supplementary (narrative context)
        candidates.extend(_narrative_candidates())
    elif route in _NARRATIVE_ROUTES:
        # Channel B primary
        candidates.extend(_narrative_candidates())
        # Channel A supplementary (numeric context)
        candidates.extend(_structured_candidates())
    else:
        # INSUFFICIENTLY_PARSED: Channel B fallback only
        candidates.extend(_narrative_candidates())

    # Deduplicate by evidence_id (Channel A + B may overlap)
    seen: set[str] = set()
    deduped: list[dict] = []
    for c in candidates:
        eid = str(c.get("evidence_id") or "?")
        if eid in seen or eid == "?":
            continue
        seen.add(eid)
        deduped.append(c)

    # Sort by final_score descending, take top_k
    deduped.sort(key=lambda c: c.get("final_score", 0.0), reverse=True)
    return deduped[:top_k]


__all__ = [
    "retrieve_via_channels",
]
