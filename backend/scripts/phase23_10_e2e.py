#!/usr/bin/env python3
"""Phase 23.10 — Development Real E2E 评估（真实检索 Top-K → core_verify）。

链路：Stage A(Top50) → Stage B(Top5) → core_pipeline.core_verify（多 Evidence 聚合记录）。
不使用 Gold Evidence 作为输入；gold 数据仅用于评测对照。

输出：
- Accuracy / Macro-F1 / per-class F1
- Abstention Accuracy / False Positive Rate / False Negative Rate / Unsupported Claim Rate
- retrieval_failure / verification_failure / both_failure
- multi_evidence 聚合记录（selected/rejected）

用法:
    cd backend
    python scripts/phase23_10_e2e.py
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
ARTIFACTS = BACKEND_DIR / "artifacts" / "e2e"


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def f1(p, r):
    return round(2 * p * r / (p + r), 4) if (p + r) > 0 else 0.0


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


def run_e2e() -> dict:
    _ensure_app_on_path()
    from app.db import SessionLocal, init_db
    from app.services import document_service
    from app.services.evidence_retrieval.stage_retrieval import stage_a_candidates, stage_b_rerank
    from app.services.verification.core_pipeline import IntegrationTrace, core_verify
    from app.services.verification.multi_evidence import aggregate_evidence_analysis
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

    block_text_cache: dict = {}

    def _bt(bid) -> str:
        if bid is None:
            return ""
        if bid not in block_text_cache:
            b = session.query(DocumentBlock).get(bid)
            block_text_cache[bid] = (b.text or "") if b else ""
        return block_text_cache[bid]

    rows = []
    for claim in all_claims:
        cid = claim["claim_id"]
        gold = all_vr.get(cid, {}).get("expected_verdict", "UNKNOWN")
        gold_evs = all_ev.get(cid, [])
        gold_pages: set = set()
        for e in gold_evs:
            fname = str(e.get("document_name") or "").split("/")[-1]
            entity = str(claim.get("entity") or claim.get("entity_name") or "")
            doc = doc_by_key.get(f"{entity}|{fname}") or doc_by_key.get(fname)
            if doc is not None and e.get("page") is not None:
                gold_pages.add((doc.id, e["page"]))
        # 真实检索（两阶段）
        try:
            a50 = stage_a_candidates(session, claim, top_k=50)
            b5 = stage_b_rerank(session, claim, a50, top_k=5) if a50 else []
        except Exception as exc:  # noqa: BLE001
            b5 = []
            retr_err = str(exc)[:100]
        else:
            retr_err = ""
        evidence_list = []
        for c in b5:
            evidence_list.append({
                "evidence_id": c.block_id, "block_id": c.block_id,
                "text": c.block_text or "", "doc_period": None,
                "document_name": None, "page": c.page_number,
                "company": claim.get("entity") or claim.get("entity_name"),
            })
        gold_page_in_top5 = any((c.document_id, c.page_number) in gold_pages for c in b5[:5])
        no_result = len(b5) == 0
        trace = IntegrationTrace(claim_id=cid)
        try:
            vr = core_verify(claim, evidence_list, trace)
            pred = vr.verification_status
            rule = vr.rule_id
        except Exception as exc:  # noqa: BLE001
            pred = "ERROR"
            rule = f"exc:{str(exc)[:80]}"
        # 多 Evidence 聚合记录
        try:
            agg = aggregate_evidence_analysis(claim, evidence_list, final_result=vr, trace=trace)
            agg_d = agg.to_dict()
        except Exception:  # noqa: BLE001
            agg_d = {}
        rows.append({
            "claim_id": cid, "dataset": claim.get("_dataset"), "claim_type": claim.get("claim_type", ""),
            "gold": gold, "pred": pred, "rule": rule, "correct": pred == gold,
            "no_result": no_result, "retrieved": len(b5),
            "gold_page_in_top5": gold_page_in_top5,
            "retrieval_error": retr_err or None,
            "multi_evidence": agg_d,
        })

    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    # per-class
    classes = sorted({r["gold"] for r in rows} | {r["pred"] for r in rows if r["pred"] != "ERROR"})
    cm = {g: {p: 0 for p in classes} for g in classes}
    for r in rows:
        cm[r["gold"]][r["pred"]] = cm[r["gold"]].get(r["pred"], 0) + 1
    per_class = {}
    for cls in classes:
        tp = cm[cls][cls]
        fp = sum(cm[g][cls] for g in classes if g != cls)
        fn = sum(cm[cls][p] for p in classes if p != cls)
        p_, r_ = (tp / (tp + fp)) if (tp + fp) else 0.0, (tp / (tp + fn)) if (tp + fn) else 0.0
        per_class[cls] = {"tp": tp, "precision": round(p_, 4), "recall": round(r_, 4), "f1": f1(p_, r_)}
    accuracy = round(correct / total, 4)
    macro_f1 = round(sum(per_class[c]["f1"] for c in classes) / len(classes), 4) if classes else 0.0
    # 专项
    abstain = [r for r in rows if r["pred"] in ("INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE", "OPINION_OR_FORECAST")]
    abstain_acc = round(sum(1 for r in abstain if r["correct"]) / len(abstain), 4) if abstain else 0.0
    neg = sum(1 for r in rows if r["gold"] != "SUPPORTED")
    pos = sum(1 for r in rows if r["gold"] == "SUPPORTED")
    fp_n = sum(1 for r in rows if r["gold"] != "SUPPORTED" and r["pred"] == "SUPPORTED")
    fn_n = sum(1 for r in rows if r["gold"] == "SUPPORTED" and r["pred"] != "SUPPORTED")
    unsupported = [r for r in rows if r["gold"] in ("SUPPORTED",) and r["pred"] not in ("SUPPORTED",)]
    err_decomp = {"retrieval_failure": 0, "verification_failure": 0, "both_failure": 0}
    for r in rows:
        if r["correct"]:
            continue
        if not r["gold_page_in_top5"]:
            if r["pred"] == "ERROR" or r["no_result"]:
                err_decomp["both_failure"] += 1
            else:
                err_decomp["retrieval_failure"] += 1
        else:
            err_decomp["verification_failure"] += 1

    result = {
        "phase": "23.10",
        "script": "phase23_10_e2e",
        "pipeline": "Stage A(Top50) → Stage B(Top5) → core_verify + multi_evidence",
        "total": total, "correct": correct, "accuracy": accuracy, "macro_f1": macro_f1,
        "per_class_f1": per_class,
        "abstention_accuracy": abstain_acc,
        "false_positive_rate": round(fp_n / neg, 4) if neg else 0.0,
        "false_negative_rate": round(fn_n / pos, 4) if pos else 0.0,
        "unsupported_claim_rate": round(len(unsupported) / total, 4),
        "no_result_rate": round(sum(1 for r in rows if r["no_result"]) / total, 4),
        "error_decomposition": err_decomp,
        "error_claims": [{"claim_id": r["claim_id"], "gold": r["gold"], "pred": r["pred"],
                          "rule": r["rule"], "gold_page_in_top5": r["gold_page_in_top5"]}
                         for r in rows if not r["correct"]],
        "targets": {
            "Accuracy >= 0.75": accuracy >= 0.75,
            "Macro-F1 >= 0.65": macro_f1 >= 0.65,
            "retrieval_failure <= 5": err_decomp["retrieval_failure"] <= 5,
            "verification_failure <= 2": err_decomp["verification_failure"] <= 2,
            "both_failure <= 1": err_decomp["both_failure"] <= 1,
        },
        "per_claim": rows,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "phase23_10_development_e2e.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(f"total={total} accuracy={accuracy} macro_f1={macro_f1}")
    print(f"abstain_acc={abstain_acc} FPR={result['false_positive_rate']} FNR={result['false_negative_rate']}")
    print(f"err_decomp={err_decomp} targets={result['targets']}")
    session.close()
    return result


if __name__ == "__main__":
    run_e2e()
