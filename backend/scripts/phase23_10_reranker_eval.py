#!/usr/bin/env python3
"""Phase 23.10 — Reranker 评测：Stage A 高召回 + Stage B Table-aware Reranker。

输出：
- Candidate Page Recall@50 / Block Recall@50
- Page Hit@1/3/5 / Block Hit@1/3/5 / Recall@1/3/5 / MRR / No-result Rate
- Top5 duplicate rate（任务十指标）
- Hit@K 单调性不变量检查（任务十三）

用法:
    cd backend
    python scripts/phase23_10_reranker_eval.py
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


def _norm(s: str) -> str:
    return "".join(s.split())


def run_eval() -> dict:
    _ensure_app_on_path()
    from app.db import SessionLocal, init_db
    from app.services import document_service
    from app.services.evidence_retrieval.stage_retrieval import stage_a_candidates, stage_b_rerank
    from app.models import Document, DocumentBlock, DocumentPage

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

    # 文档消歧
    doc_by_key: dict[str, Document] = {}
    for d in session.query(Document).all():
        doc_by_key[f"{d.company_name}|{d.original_filename}"] = d
        doc_by_key.setdefault(d.original_filename, d)

    all_claims, all_ev, all_vr = [], {}, {}
    for ds in ["demo", "holdout"]:
        claims, ev, vr = load_gold(ds)
        for c in claims:
            c["_dataset"] = ds
        all_claims.extend(claims)
        all_ev.update(ev)
        all_vr.update(vr)

    block_text_cache: dict[int, str] = {}

    def _bt(bid) -> str:
        if bid is None:
            return ""
        if bid not in block_text_cache:
            b = session.query(DocumentBlock).get(bid)
            block_text_cache[bid] = (b.text or "") if b else ""
        return block_text_cache[bid]

    per_claim: list[dict] = []
    for claim in all_claims:
        cid = claim["claim_id"]
        gold_evs = all_ev.get(cid, [])
        gold_pages: set = set()
        gold_blocks: set = set()
        for e in gold_evs:
            fname = str(e.get("document_name") or "").split("/")[-1]
            entity = str(claim.get("entity") or claim.get("entity_name") or "")
            doc = doc_by_key.get(f"{entity}|{fname}") or doc_by_key.get(fname)
            if doc is None or e.get("page") is None:
                continue
            gold_pages.add((doc.id, e["page"]))
            rows = (session.query(DocumentBlock, DocumentPage.page_number)
                    .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
                    .filter(DocumentBlock.document_id == doc.id, DocumentPage.page_number == e["page"]).all())
            ev_norm = _norm(e.get("evidence_text", "") or "")
            if ev_norm:
                best_bid, best_len = None, 0
                for b, pn in rows:
                    bn = _norm(b.text or "")
                    if bn and (ev_norm in bn or bn in ev_norm) and len(bn) > best_len:
                        best_bid, best_len = b.id, len(bn)
                if best_bid is not None:
                    gold_blocks.add(best_bid)
        # 无 Gold Evidence 的 claim 不计入 total_claims（统一定义：total_claims =
        # 全部有 Gold Evidence 的 Development Claims）
        if not gold_pages:
            continue

        # Stage A（Top50）+ Stage B（Top5，但为算 Hit@1/3/5 取 5；再取 50 用于 Recall@50）
        try:
            a50 = stage_a_candidates(session, claim, top_k=50)
        except Exception as exc:  # noqa: BLE001
            a50 = []
            err = str(exc)[:100]
        else:
            err = ""
        b5 = stage_b_rerank(session, claim, a50, top_k=5) if a50 else []
        # Stage A Recall@50（页面级 + 块级）
        a_page_hit = any((c.document_id, c.page_number) in gold_pages for c in a50)
        a_block_hit = any(c.block_id in gold_blocks for c in a50)
        # Stage B Hit@K / Recall@K / MRR
        def b_hit_rank(k: int, page_level: bool) -> int | None:
            for i, c in enumerate(b5[:k], start=1):
                if page_level:
                    if (c.document_id, c.page_number) in gold_pages:
                        return i
                else:
                    if c.block_id in gold_blocks:
                        return i
            return None

        ph1, ph3, ph5 = b_hit_rank(1, True), b_hit_rank(3, True), b_hit_rank(5, True)
        bh1, bh3, bh5 = b_hit_rank(1, False), b_hit_rank(3, False), b_hit_rank(5, False)
        mrr_page = (1.0 / ph1) if ph1 else 0.0
        mrr_block = (1.0 / bh1) if bh1 else 0.0
        # duplicate rate（top5 中同页同表重复）
        top5_ids = [c.block_id for c in b5]
        dup = len(top5_ids) - len(set(top5_ids))
        dup_rate = round(dup / max(len(top5_ids), 1), 3)
        per_claim.append({
            "claim_id": cid, "dataset": claim.get("_dataset"),
            "gold_pages": sorted(gold_pages), "gold_blocks": sorted(gold_blocks),
            "stage_a_page_recall_50": a_page_hit, "stage_a_block_recall_50": a_block_hit,
            "stage_a_count": len(a50),
            "page_hit_1": ph1 is not None, "page_hit_3": ph3 is not None, "page_hit_5": ph5 is not None,
            "block_hit_1": bh1 is not None, "block_hit_3": bh3 is not None, "block_hit_5": bh5 is not None,
            "mrr_page": round(mrr_page, 4), "mrr_block": round(mrr_block, 4),
            "no_result": len(b5) == 0, "retrieved": len(b5),
            "top5_duplicate_rate": dup_rate,
            "error": err or None,
            "top10": [
                {"rank": i, "block_id": c.block_id, "page": c.page_number, "document_id": c.document_id,
                 "final_score": round(c.final_score, 4),
                 "gold_page_hit": (c.document_id, c.page_number) in gold_pages,
                 "gold_block_hit": c.block_id in gold_blocks,
                 "query_contributions": c.query_contributions,
                 "text": _bt(c.block_id)[:60]}
                for i, c in enumerate(b5, start=1)
            ],
        })

    total = len(per_claim)
    agg = {
        "stage_a_page_recall_50": round(sum(1 for p in per_claim if p["stage_a_page_recall_50"]) / total, 4),
        "stage_a_block_recall_50": round(sum(1 for p in per_claim if p["stage_a_block_recall_50"]) / total, 4),
        "page_hit_1": round(sum(1 for p in per_claim if p["page_hit_1"]) / total, 4),
        "page_hit_3": round(sum(1 for p in per_claim if p["page_hit_3"]) / total, 4),
        "page_hit_5": round(sum(1 for p in per_claim if p["page_hit_5"]) / total, 4),
        "block_hit_1": round(sum(1 for p in per_claim if p["block_hit_1"]) / total, 4),
        "block_hit_3": round(sum(1 for p in per_claim if p["block_hit_3"]) / total, 4),
        "block_hit_5": round(sum(1 for p in per_claim if p["block_hit_5"]) / total, 4),
        "mrr_page": round(sum(p["mrr_page"] for p in per_claim) / total, 4),
        "mrr_block": round(sum(p["mrr_block"] for p in per_claim) / total, 4),
        "no_result_rate": round(sum(1 for p in per_claim if p["no_result"]) / total, 4),
        "top5_duplicate_rate": round(sum(p["top5_duplicate_rate"] for p in per_claim) / total, 4),
    }
    # Recall@K（Stage B：Top K 命中的 Gold Evidence 数 / Gold Evidence 总数）
    gold_total = sum(len(p["gold_pages"]) for p in per_claim)
    recall = {}
    for k in (1, 3, 5):
        hits = 0
        for p in per_claim:
            for c in p["top10"][:k]:
                if c["gold_block_hit"] or c["gold_page_hit"]:
                    hits += 1
                    break
        recall[f"recall_at_{k}"] = round(hits / gold_total, 4) if gold_total else 0.0
    agg.update(recall)

    # 不变量检查（任务十三）
    invariants = {
        "0<=Hit1<=Hit3<=Hit5": 0.0 <= agg["page_hit_1"] <= agg["page_hit_3"] <= agg["page_hit_5"] <= 1.0,
        "0<=BlockHit1<=BlockHit3<=BlockHit5": 0.0 <= agg["block_hit_1"] <= agg["block_hit_3"] <= agg["block_hit_5"] <= 1.0,
        "Recall1<=Recall3<=Recall5": recall["recall_at_1"] <= recall["recall_at_3"] <= recall["recall_at_5"],
        "CandidateRecall50>=Recall5": agg["stage_a_block_recall_50"] >= recall["recall_at_5"],
    }

    result = {
        "phase": "23.10",
        "script": "phase23_10_reranker_eval",
        "pipeline": "Stage A(Top50) → Stage B(Top5)",
        "total_claims": total,
        "metrics": agg,
        "invariants": invariants,
        "all_invariants_passed": all(invariants.values()),
        "targets": {
            "Candidate Page Recall@50 >= 0.95": agg["stage_a_page_recall_50"] >= 0.95,
            "Candidate Block Recall@50 >= 0.90": agg["stage_a_block_recall_50"] >= 0.90,
            "Page Hit@5 >= 0.80": agg["page_hit_5"] >= 0.80,
            "Block Hit@5 >= 0.70": agg["block_hit_5"] >= 0.70,
            "Recall@5 >= 0.80": recall["recall_at_5"] >= 0.80,
            "MRR >= 0.60": agg["mrr_page"] >= 0.60,
            "No-result <= 0.05": agg["no_result_rate"] <= 0.05,
        },
        "per_claim": per_claim,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "phase23_10_metrics.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    cand = {"phase": "23.10", "total": total, "per_claim_top10": per_claim}
    (ARTIFACTS / "phase23_10_candidates.json").write_text(json.dumps(cand, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(f"StageA page/block Recall@50 = {agg['stage_a_page_recall_50']} / {agg['stage_a_block_recall_50']}")
    print(f"Page Hit@1/3/5 = {agg['page_hit_1']} / {agg['page_hit_3']} / {agg['page_hit_5']}")
    print(f"Block Hit@1/3/5 = {agg['block_hit_1']} / {agg['block_hit_3']} / {agg['block_hit_5']}")
    print(f"Recall@1/3/5 = {recall['recall_at_1']} / {recall['recall_at_3']} / {recall['recall_at_5']}")
    print(f"MRR(page)={agg['mrr_page']} No-result={agg['no_result_rate']} dup={agg['top5_duplicate_rate']}")
    print(f"invariants: {invariants}")
    print(f"targets: {result['targets']}")
    session.close()
    return result


if __name__ == "__main__":
    run_eval()
