#!/usr/bin/env python3
"""Phase 23.10 — 13 个 Retrieval Failure 逐条诊断。

对 Development Claims（43 条）执行真实检索 top_k=20，逐 claim 诊断：
- gold_document_id / gold_page / gold_block_id / gold_block_indexed
- gold_candidate_rank_before_rerank / after_rerank（top20）
- top_20_candidates
- failure_stage（QUERY_CONSTRUCTION / CANDIDATE_GENERATION / PAGE_RETRIEVAL /
  BLOCK_RETRIEVAL / TABLE_CONTEXT_LOSS / RERANKING / DUPLICATE_CROWDING /
  WRONG_PERIOD_BOOST / WRONG_METRIC_BOOST / NARRATIVE_OVER_TABLE /
  HEADER_ROW_SPLIT / MULTI_PAGE_TABLE / VERIFICATION_NOISE）
- root_cause / proposed_fix / status

产物：backend/artifacts/retrieval/phase23_10_failure_diagnosis.json

用法:
    cd backend
    python scripts/phase23_10_failure_diagnosis.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS = BACKEND_DIR / "artifacts" / "retrieval"

DOC_PERIOD_BY_NAME = {
    "annual_report.pdf": "2025FY",
    "half_year_report.pdf": "2025H1",
    "q1_report.pdf": "2025Q1",
    "quarter_report.pdf": "2025Q3",
    "annual_report_2025.pdf": "2025FY",
    "annual_report_2024.pdf": "2024FY",
}


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def load_gold(dataset: str):
    claims = json.load(open(DATA_DIR / dataset / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])
    evs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_evidence.json", encoding="utf-8")).get("evidence", [])
    vrs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_verifications.json", encoding="utf-8")).get("verifications", [])
    ev_by: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        ev_by[e.get("claim_id", "")].append(e)
    vr_by = {v.get("claim_id", ""): v for v in vrs}
    return claims, dict(ev_by), vr_by


def classify_stage(claim: dict, gold_blocks: list, retrieved: list, gold_pages: set) -> str:
    """按证据判定失败阶段（启发式）。"""
    if not gold_blocks:
        return "CANDIDATE_GENERATION"
    if not retrieved:
        return "CANDIDATE_GENERATION"
    # gold page 是否在任何候选（top20）
    gold_page_in_top20 = any((c.get("document_id"), c.get("page_number")) in gold_pages for c in retrieved)
    gold_block_in_top20 = any(c.get("block_id") in gold_blocks for c in retrieved)
    if gold_page_in_top20:
        # 页进了 top20 但块/排名问题
        if gold_block_in_top20:
            # 块也在 → 排名被挤出 top5 → RERANKING 或 NARRATIVE_OVER_TABLE
            top5_has_gold = any(c.get("block_id") in gold_blocks or (c.get("document_id"), c.get("page_number")) in gold_pages
                                for c in retrieved[:5])
            if not top5_has_gold:
                return "RERANKING"
            return "VERIFICATION_NOISE"
        # 页进但块没进 → 表头/数据行分离 → TABLE_CONTEXT_LOSS / HEADER_ROW_SPLIT
        # 检查 gold page 是否有候选块（同页）
        same_page = [c for c in retrieved if (c.get("document_id"), c.get("page_number")) in gold_pages]
        if same_page:
            return "HEADER_ROW_SPLIT"
        return "BLOCK_RETRIEVAL"
    # gold page 未进 top20
    metric = str(claim.get("metric") or "")
    period = str(claim.get("period") or "")
    if "quarterly" in metric or re.search(r"Q[1-4]", period):
        return "QUERY_CONSTRUCTION"
    return "CANDIDATE_GENERATION"


def run_diagnosis() -> dict:
    _ensure_app_on_path()
    from app.db import SessionLocal, init_db
    from app.services import document_service
    from app.services.evidence_retrieval.service import retrieve_for_claim
    from app.models import Document, DocumentBlock, DocumentPage

    # 干净库 + 导入 Development 源文档
    db_path = DATA_DIR.parent / "finproof.db"
    if db_path.exists():
        db_path.unlink()
    storage = DATA_DIR.parent / "storage"
    if storage.exists():
        shutil.rmtree(storage)
    init_db()
    session = SessionLocal()
    imports = [
        (DATA_DIR / "demo" / "source" / "annual_report.pdf", "美的集团", "000333", "2025FY"),
        (DATA_DIR / "demo" / "source" / "half_year_report.pdf", "美的集团", "000333", "2025H1"),
        (DATA_DIR / "demo" / "source" / "q1_report.pdf", "美的集团", "000333", "2025Q1"),
        (DATA_DIR / "holdout" / "source" / "annual_report.pdf", "五粮液", "000858", "2025FY"),
    ]
    for path, company, stock, period in imports:
        with open(path, "rb") as f:
            data = f.read()
        document_service.register_document(session, filename=path.name, data=data,
                                           document_role="SOURCE_DOCUMENT", company_name=company,
                                           stock_code=stock, report_period=period)

    doc_by_name: dict[str, Document] = {}
    for d in session.query(Document).all():
        # 同名文档消歧：demo 与 holdout 均有 annual_report.pdf，
        # 用 company_name 前缀区分（美的集团 → demo，五粮液 → holdout）
        key = f"{d.company_name}|{d.original_filename}"
        doc_by_name[key] = d
        # 无公司名时的 fallback（避免覆盖）
        doc_by_name.setdefault(d.original_filename, d)

    all_claims, all_ev, all_vr = [], {}, {}
    for ds in ["demo", "holdout"]:
        claims, ev, vr = load_gold(ds)
        for c in claims:
            c["_dataset"] = ds
        all_claims.extend(claims)
        all_ev.update(ev)
        all_vr.update(vr)

    # block 文本缓存（top20 诊断展示用）
    block_text_cache: dict[int, str] = {}

    def _bt(block_id) -> str:
        if block_id is None:
            return ""
        if block_id not in block_text_cache:
            b = session.query(DocumentBlock).get(block_id)
            block_text_cache[block_id] = (b.text or "") if b else ""
        return block_text_cache[block_id]

    diag_rows = []
    for claim in all_claims:
        cid = claim["claim_id"]
        gold_evs = all_ev.get(cid, [])
        gold = all_vr.get(cid, {}).get("expected_verdict", "UNKNOWN")
        gold_blocks: set = set()
        gold_pages: set = set()
        gold_block_indexed = True
        for e in gold_evs:
            fname = str(e.get("document_name") or "").split("/")[-1]
            # 实体消歧：gold evidence 文档名相同（annual_report.pdf 同时属于 demo/holdout），
            # 用 claim.entity 匹配 company_name
            entity = str(claim.get("entity") or claim.get("entity_name") or "")
            doc = None
            if entity:
                doc = doc_by_name.get(f"{entity}|{fname}")
            if doc is None:
                doc = doc_by_name.get(fname)
            if doc is None:
                gold_block_indexed = False
                continue
            gold_pages.add((doc.id, e.get("page")))
            # 尝试解析 gold block：同页文本归一化包含匹配
            rows = (session.query(DocumentBlock, DocumentPage.page_number)
                    .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
                    .filter(DocumentBlock.document_id == doc.id, DocumentPage.page_number == e.get("page")).all())
            ev_norm = re.sub(r"\s+", "", e.get("evidence_text", "") or "")
            best_bid = None
            if ev_norm:
                best_len = 0
                for b, pn in rows:
                    bn = re.sub(r"\s+", "", (b.text or ""))
                    if bn and (ev_norm in bn or bn in ev_norm) and len(bn) > best_len:
                        best_bid, best_len = b.id, len(bn)
            if best_bid is not None:
                gold_blocks.add(best_bid)

        try:
            cands = retrieve_for_claim(session, claim, top_k=20) or []
        except Exception as exc:  # noqa: BLE001
            cands = []
            retr_err = str(exc)[:120]
        else:
            retr_err = ""

        gold_rank_top20 = None
        for i, c in enumerate(cands, start=1):
            if c.get("block_id") in gold_blocks or (c.get("document_id"), c.get("page_number")) in gold_pages:
                gold_rank_top20 = i
                break

        stage = classify_stage(claim, list(gold_blocks), cands, gold_pages)
        gold_page_in_top5 = gold_rank_top20 is not None and gold_rank_top20 <= 5
        is_failure = not gold_page_in_top5

        root_cause = ""
        proposed_fix = ""
        if stage == "CANDIDATE_GENERATION" and not gold_block_indexed:
            root_cause = "Gold Block 未索引（gold evidence 指向未导入文档）"
            proposed_fix = "检查索引覆盖，将缺失文档纳入 Stage A 候选池"
        elif stage == "CANDIDATE_GENERATION":
            root_cause = "Gold Page 未进入 Top20 候选（候选生成阶段漏召）"
            proposed_fix = "扩 Stage A 候选（BM25 + numeric index + table row index + 多 query）"
        elif stage == "QUERY_CONSTRUCTION":
            root_cause = "quarterly/scope 类无规范 metric 别名，query 构造不足"
            proposed_fix = "Claim Query Planner 生成 metric+period+alias 多 query"
        elif stage == "HEADER_ROW_SPLIT":
            root_cause = "表头与数据行被拆成不同 block，Gold Page 进候选但 Gold Block 未命中"
            proposed_fix = "TableContext 重建：row_header + column_header + 数据行合并为 Enriched Evidence"
        elif stage == "TABLE_CONTEXT_LOSS":
            root_cause = "表格上下文丢失（跨页表/单位在表头），数值块无单位绑定"
            proposed_fix = "TableContext 注入 unit_header + 相邻行列上下文"
        elif stage == "BLOCK_RETRIEVAL":
            root_cause = "Gold Page 未进入 Top20 且 Gold Block 也未命中"
            proposed_fix = "Stage A 提高 Block Candidate Recall@50（table row index）"
        elif stage == "RERANKING":
            root_cause = "Gold 候选进入 Top20 但被挤到 Top5 之外（reranker 排序不足）"
            proposed_fix = "Stage B Table-aware Reranker：table_title/row_header/numeric_score 加权"
        else:
            root_cause = "Gold 候选在 Top5 内但 Verification 未识别（噪声鲁棒性）"
            proposed_fix = "多 Evidence Verification：聚合正确证据、拒绝干扰证据"

        diag_rows.append({
            "claim_id": cid,
            "claim_text": claim.get("original_text", ""),
            "company": claim.get("entity", ""),
            "metric": claim.get("metric", ""),
            "period": claim.get("period", ""),
            "value": claim.get("value"),
            "unit": claim.get("unit", ""),
            "scope": claim.get("scope", ""),
            "gold_verdict": gold,
            "gold_document_id": next(iter(gold_pages), (None, None))[0],
            "gold_page": next(iter(gold_pages), (None, None))[1],
            "gold_block_id": next(iter(gold_blocks), None),
            "gold_block_indexed": gold_block_indexed,
            "gold_candidate_rank_after_rerank": gold_rank_top20,
            "retrieved_count": len(cands),
            "failure": is_failure,
            "failure_stage": stage,
            "root_cause": root_cause,
            "proposed_fix": proposed_fix,
            "status": "FAIL" if is_failure else "PASS",
            "retrieval_error": retr_err or None,
            "top_20_candidates": [
                {"rank": i, "document_id": c.get("document_id"), "page": c.get("page_number"),
                 "block_id": c.get("block_id"), "final_score": round(float(c.get("final_score") or 0), 3),
                 "metric_score": round(float(c.get("metric_score") or 0), 2),
                 "value_score": round(float(c.get("value_score") or 0), 2),
                 "period_score": round(float(c.get("period_score") or 0), 2),
                 "gold_block_hit": c.get("block_id") in gold_blocks,
                 "gold_page_hit": (c.get("document_id"), c.get("page_number")) in gold_pages,
                 "text": _bt(c.get("block_id"))[:60]}
                for i, c in enumerate(cands, start=1)
            ],
        })

    failures = [r for r in diag_rows if r["failure"]]
    from collections import Counter
    stage_counts = Counter(r["failure_stage"] for r in failures)

    result = {
        "phase": "23.10",
        "script": "phase23_10_failure_diagnosis",
        "pipeline": "真实检索 retrieve_for_claim(top_k=20)",
        "total_claims": len(diag_rows),
        "failure_count": len(failures),
        "failure_stage_counts": dict(stage_counts),
        "diagnosis": diag_rows,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "phase23_10_failure_diagnosis.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(f"total={len(diag_rows)} failures={len(failures)}")
    print(f"stage counts: {dict(stage_counts)}")
    for r in failures:
        print(f"  {r['claim_id']:8s} {r['failure_stage']:22s} gold_rank={r['gold_candidate_rank_after_rerank']} retr={r['retrieved_count']}")
    session.close()
    return result


if __name__ == "__main__":
    run_diagnosis()
