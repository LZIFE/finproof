#!/usr/bin/env python3
"""Phase 23.10 — 公司留一权重调优（Fold A/B 互验）。

Fold A：调参公司=五粮液（holdout），验证公司=美的集团（demo）
Fold B：调参公司=美的集团（demo），验证公司=五粮液（holdout）

规则（任务九）：
1. 只能在训练公司上选择 Stage B 权重（Page Hit@5 最优）。
2. 权重冻结后应用到验证公司。
3. 不得查看验证公司结果后再次修改该 Fold 权重。
4. 保存训练权重和验证结果。
5. 最终全 Development 权重由两个 Fold 的稳定区间产生。
6. 不得为某一个 claim 单独调权重。

输出：backend/artifacts/retrieval/phase23_10_leave_one_company_out.json

用法:
    cd backend
    python scripts/phase23_10_leave_one_company_out.py
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
    ev_by: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        ev_by[e.get("claim_id", "")].append(e)
    return claims, dict(ev_by)


def _norm(s: str) -> str:
    return "".join(s.split())


def evaluate_weights(session, claims: list[dict], ev_by: dict, weights: dict,
                     doc_by_key: dict, block_text_cache: dict) -> dict:
    """在给定 claim 集合上评估权重（Page Hit@1/3/5 / Block Hit@K / MRR / No-result）。"""
    from app.services.evidence_retrieval.stage_retrieval import stage_a_candidates, stage_b_rerank
    from app.models import DocumentBlock, DocumentPage

    def _bt(bid) -> str:
        if bid is None:
            return ""
        if bid not in block_text_cache:
            b = session.query(DocumentBlock).get(bid)
            block_text_cache[bid] = (b.text or "") if b else ""
        return block_text_cache[bid]

    per = []
    for claim in claims:
        cid = claim["claim_id"]
        gold_evs = ev_by.get(cid, [])
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
        if not gold_pages:
            continue
        try:
            a50 = stage_a_candidates(session, claim, top_k=50)
            b5 = stage_b_rerank(session, claim, a50, top_k=5, weights=weights) if a50 else []
        except Exception:  # noqa: BLE001
            b5 = []
        def _hit_rank(k, page_level):
            for i, c in enumerate(b5[:k], start=1):
                if page_level:
                    if (c.document_id, c.page_number) in gold_pages:
                        return i
                else:
                    if c.block_id in gold_blocks:
                        return i
            return None
        ph1, ph3, ph5 = _hit_rank(1, True), _hit_rank(3, True), _hit_rank(5, True)
        per.append({
            "page_hit_1": ph1 is not None, "page_hit_3": ph3 is not None, "page_hit_5": ph5 is not None,
            "mrr_page": (1.0 / ph1) if ph1 else 0.0,
            "no_result": len(b5) == 0,
        })
    n = len(per) if per else 1
    return {
        "n_claims": len(per),
        "page_hit_1": round(sum(1 for p in per if p["page_hit_1"]) / n, 4),
        "page_hit_3": round(sum(1 for p in per if p["page_hit_3"]) / n, 4),
        "page_hit_5": round(sum(1 for p in per if p["page_hit_5"]) / n, 4),
        "mrr_page": round(sum(p["mrr_page"] for p in per) / n, 4),
        "no_result_rate": round(sum(1 for p in per if p["no_result"]) / n, 4),
    }


def run_leave_one_out() -> dict:
    _ensure_app_on_path()
    from app.db import SessionLocal, init_db
    from app.services import document_service
    from app.services.evidence_retrieval.stage_retrieval import STAGE_B_WEIGHTS
    from app.models import Document

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

    doc_by_key: dict[str, Document] = {}
    for d in session.query(Document).all():
        doc_by_key[f"{d.company_name}|{d.original_filename}"] = d
        doc_by_key.setdefault(d.original_filename, d)

    demo_claims, demo_ev = load_gold("demo")
    holdout_claims, holdout_ev = load_gold("holdout")
    block_text_cache: dict = {}

    # 权重候选（仅 2-3 个关键维度变化；在训练公司上选，冻结后应用到验证公司）
    weight_candidates = [
        ("default", dict(STAGE_B_WEIGHTS)),
        ("metric_heavy", {**STAGE_B_WEIGHTS, "metric": 0.20, "numeric": 0.18, "row_header": 0.12}),
        ("table_heavy", {**STAGE_B_WEIGHTS, "table_title": 0.08, "row_header": 0.14, "neighboring_context": 0.08, "numeric": 0.17}),
    ]

    folds = [
        {"fold": "A", "train": "五粮液", "train_claims": holdout_claims, "train_ev": holdout_ev,
         "eval": "美的集团", "eval_claims": demo_claims, "eval_ev": demo_ev},
        {"fold": "B", "train": "美的集团", "train_claims": demo_claims, "train_ev": demo_ev,
         "eval": "五粮液", "eval_claims": holdout_claims, "eval_ev": holdout_ev},
    ]

    fold_results = []
    final_weights_range: dict[str, list] = defaultdict(list)
    for fold in folds:
        # 1) 训练公司上选权重（只看训练公司 Page Hit@5）
        best = None
        for name, w in weight_candidates:
            r = evaluate_weights(session, fold["train_claims"], fold["train_ev"], w, doc_by_key, block_text_cache)
            if best is None or r["page_hit_5"] > best[1]["page_hit_5"]:
                best = (name, r, w)
        train_name, train_res, chosen_w = best
        for k, v in chosen_w.items():
            final_weights_range[k].append(v)
        # 2) 冻结权重应用到验证公司
        eval_res = evaluate_weights(session, fold["eval_claims"], fold["eval_ev"], chosen_w, doc_by_key, block_text_cache)
        fold_results.append({
            "fold": fold["fold"],
            "train_company": fold["train"],
            "eval_company": fold["eval"],
            "train_metric": {k: v for k, v in train_res.items() if k != "n_claims"},
            "chosen_weight_name": train_name,
            "chosen_weights": chosen_w,
            "eval_metric": {k: v for k, v in eval_res.items() if k != "n_claims"},
            "leakage_note": "权重仅在训练公司上选择并冻结，验证公司结果未回传修改权重",
        })

    # 3) 最终全 Development 权重：两 Fold 稳定区间（各维度的最小/最大）
    stable_weights = {}
    for k, vals in final_weights_range.items():
        if len(set(vals)) == 1:
            stable_weights[k] = vals[0]
        else:
            stable_weights[k] = round(sum(vals) / len(vals), 4)  # 区间均值（稳定折中）
    # 4) 全 Development 评估（两数据集合并，仅使用稳定权重）
    all_claims = demo_claims + holdout_claims
    all_ev = {**demo_ev, **holdout_ev}
    full = evaluate_weights(session, all_claims, all_ev, stable_weights, doc_by_key, block_text_cache)

    result = {
        "phase": "23.10",
        "script": "phase23_10_leave_one_company_out",
        "method": "Fold A/B 公司留一：训练公司选权重 → 冻结 → 验证公司评估",
        "folds": fold_results,
        "stable_weights": stable_weights,
        "full_development_with_stable_weights": {k: v for k, v in full.items() if k != "n_claims"},
        "targets": {
            "Page Hit@5 >= 0.80 (full)": full.get("page_hit_5", 0) >= 0.80,
            "MRR >= 0.60 (full)": full.get("mrr_page", 0) >= 0.60,
            "No-result <= 0.05 (full)": full.get("no_result_rate", 1) <= 0.05,
        },
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "phase23_10_leave_one_company_out.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    for f in fold_results:
        print(f"Fold{f['fold']} train={f['train_company']} chose={f['chosen_weight_name']} "
              f"train_hit5={f['train_metric']['page_hit_5']} eval_hit5={f['eval_metric']['page_hit_5']}")
    print(f"full dev with stable weights: PageHit5={full.get('page_hit_5')} MRR={full.get('mrr_page')} "
          f"no_result={full.get('no_result_rate')}")
    session.close()
    return result


if __name__ == "__main__":
    run_leave_one_out()
