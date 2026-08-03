#!/usr/bin/env python3
"""Phase 23.9 — Development Real E2E 评估（真实 Retrieval Top-K，不使用 Gold Evidence）。

链路：真实检索 retrieve_for_claim(top_k=5) → core_pipeline.core_verify → Verdict。
gold_claims.json 提供主张输入；gold_evidence/gold_verifications 仅用于评测对照。

输出（Development Set）：
- Accuracy / Macro-F1 / per-class F1
- No-result Rate / Evidence Recall@5 / Abstention Accuracy / False Positive Rate / False Negative Rate
- 错误分解：retrieval failure / verification failure / both failure

用法:
    cd backend
    python scripts/phase23_9_e2e.py
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "e2e"

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


def run_e2e() -> dict:
    _ensure_app_on_path()
    from app.db import SessionLocal, init_db
    from app.services import document_service
    from app.services.evidence_retrieval.service import retrieve_for_claim
    from app.services.verification.core_pipeline import IntegrationTrace, core_verify

    # ---- 干净库 + 导入 4 份 Development 源文档 ----
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

    # ---- 文档名 → (doc_id) 映射（gold evidence 页命中判定用）----
    from app.models import Document
    doc_by_name = {d.original_filename: d.id for d in session.query(Document).all()}

    all_claims, all_ev, all_vr = [], {}, {}
    for ds in ["demo", "holdout"]:
        claims, ev, vr = load_gold(ds)
        for c in claims:
            c["_dataset"] = ds
        all_claims.extend(claims)
        all_ev.update(ev)
        all_vr.update(vr)

    rows = []
    for claim in all_claims:
        cid = claim["claim_id"]
        gold = all_vr.get(cid, {}).get("expected_verdict", "UNKNOWN")
        gold_evs = all_ev.get(cid, [])
        gold_pages = set()
        for e in gold_evs:
            did = doc_by_name.get(str(e.get("document_name") or "").split("/")[-1])
            if did is not None and e.get("page") is not None:
                gold_pages.add((did, e["page"]))

        try:
            candidates = retrieve_for_claim(session, claim, top_k=5) or []
        except Exception as exc:  # noqa: BLE001
            candidates = []
            retr_err = str(exc)[:120]
        else:
            retr_err = ""
        evidence_list = []
        for c in candidates:
            evidence_list.append({
                "evidence_id": c.get("block_id"),
                "block_id": c.get("block_id"),
                "text": c.get("block_text", "") or "",
                "doc_period": None,
                "document_name": None,
                "page": c.get("page_number"),
            })
        gold_page_in_top5 = any((c.get("document_id"), c.get("page_number")) in gold_pages for c in candidates[:5])
        no_result = len(candidates) == 0

        trace = IntegrationTrace(claim_id=cid)
        try:
            vr = core_verify(claim, evidence_list, trace)
            pred = vr.verification_status
            rule = vr.rule_id
        except Exception as exc:  # noqa: BLE001
            pred = "ERROR"
            rule = f"exc:{str(exc)[:80]}"
        rows.append({
            "claim_id": cid, "dataset": claim.get("_dataset"), "claim_type": claim.get("claim_type", ""),
            "gold": gold, "pred": pred, "rule": rule, "correct": pred == gold,
            "no_result": no_result, "retrieved": len(candidates),
            "gold_page_in_top5": gold_page_in_top5,
            "gold_evidence_count": len(gold_evs),
            "retrieval_error": retr_err or None,
            "trace": trace.to_dict(),
        })

    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])

    # ---- per-class ----
    classes = sorted({r["gold"] for r in rows} | {r["pred"] for r in rows if r["pred"] != "ERROR"})
    cm = {g: {p: 0 for p in classes} for g in classes}
    for r in rows:
        cm[r["gold"]][r["pred"]] = cm[r["gold"]].get(r["pred"], 0) + 1
    per_class = {}
    for cls in classes:
        tp = cm[cls][cls]
        fp = sum(cm[g][cls] for g in classes if g != cls)
        fn = sum(cm[cls][p] for p in classes if p != cls)
        precision = round(tp / (tp + fp), 4) if (tp + fp) else 0.0
        recall = round(tp / (tp + fn), 4) if (tp + fn) else 0.0
        per_class[cls] = {"tp": tp, "precision": precision, "recall": recall, "f1": f1(precision, recall)}

    # ---- 专项指标 ----
    no_result_rate = round(sum(1 for r in rows if r["no_result"]) / total, 4)
    evidence_recall5 = round(sum(1 for r in rows if r["gold_page_in_top5"]) / total, 4)
    # Abstention：系统 abstain（INSUFFICIENT/UNABLE/OPINION）时预测是否与 gold 一致
    abstain_rows = [r for r in rows if r["pred"] in ("INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE", "OPINION_OR_FORECAST")]
    abstain_acc = round(sum(1 for r in abstain_rows if r["correct"]) / len(abstain_rows), 4) if abstain_rows else 0.0
    # FPR：gold 非 SUPPORTED 但预测 SUPPORTED；FNR：gold SUPPORTED 但预测非 SUPPORTED
    neg_total = sum(1 for r in rows if r["gold"] != "SUPPORTED")
    pos_total = sum(1 for r in rows if r["gold"] == "SUPPORTED")
    fp_count = sum(1 for r in rows if r["gold"] != "SUPPORTED" and r["pred"] == "SUPPORTED")
    fn_count = sum(1 for r in rows if r["gold"] == "SUPPORTED" and r["pred"] != "SUPPORTED")
    fpr = round(fp_count / neg_total, 4) if neg_total else 0.0
    fnr = round(fn_count / pos_total, 4) if pos_total else 0.0

    # ---- 错误分解 ----
    errors = [r for r in rows if not r["correct"]]
    err_decomp = {"retrieval_failure": 0, "verification_failure": 0, "both_failure": 0}
    for r in errors:
        if not r["gold_page_in_top5"]:
            if r["pred"] == "ERROR" or r["no_result"]:
                err_decomp["both_failure"] += 1
            else:
                err_decomp["retrieval_failure"] += 1
        else:
            err_decomp["verification_failure"] += 1

    accuracy = round(correct / total, 4)
    macro_f1 = round(sum(per_class[c]["f1"] for c in classes) / len(classes), 4) if classes else 0.0

    result = {
        "phase": "23.9",
        "script": "phase23_9_e2e",
        "pipeline": "真实检索 retrieve_for_claim(top_k=5) → core_pipeline.core_verify",
        "note": "不使用 Gold Evidence 作为输入；gold 数据仅用于评测对照",
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "per_class_f1": per_class,
        "confusion_matrix": cm,
        "no_result_rate": no_result_rate,
        "no_result_claims": [r["claim_id"] for r in rows if r["no_result"]],
        "evidence_recall_at_5": evidence_recall5,
        "abstention_accuracy": abstain_acc,
        "false_positive_rate": fpr,
        "false_negative_rate": fnr,
        "error_decomposition": err_decomp,
        "error_claims": [{"claim_id": r["claim_id"], "gold": r["gold"], "pred": r["pred"], "rule": r["rule"],
                          "gold_page_in_top5": r["gold_page_in_top5"]} for r in errors],
        "targets": {
            "Macro-F1 >= 0.60": macro_f1 >= 0.60,
            "Accuracy >= 0.70": accuracy >= 0.70,
            "No-result Rate <= 0.15": no_result_rate <= 0.15,
        },
        "per_claim": rows,
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_9_development_e2e.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    print(f"total={total} correct={correct} accuracy={accuracy} macro_f1={macro_f1}")
    print(f"no_result_rate={no_result_rate} evidence_recall@5={evidence_recall5} abstain_acc={abstain_acc} FPR={fpr} FNR={fnr}")
    print(f"err_decomp={err_decomp}")
    print(f"targets: {result['targets']}")
    return result


if __name__ == "__main__":
    run_e2e()
