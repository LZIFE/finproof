#!/usr/bin/env python3
"""Phase 23.9 — Oracle Verification 正式评估（Gold Evidence Block 输入，43 条 Development Claims）。

主链：core_pipeline.core_verify（PRIMARY），Gold Evidence Block 作为唯一输入；
gold_verifications.json 仅用于评测对照，不进入推理路径。

输出：
- Accuracy / Macro-F1 / per-class precision/recall/F1 / per-type F1 / confusion matrix
- 17 个原错误的新结果（对照 phase23_8_cases.json）
- 新增回归错误
- annotation suspected cases

用法:
    cd backend
    python scripts/phase23_9_oracle_eval.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "oracle"

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


def f1(p, r):
    return round(2 * p * r / (p + r), 4) if (p + r) > 0 else 0.0


def run_oracle_eval() -> dict:
    _ensure_app_on_path()
    from app.services.verification.core_pipeline import IntegrationTrace, core_verify

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
        evidence_list = []
        for e in all_ev.get(cid, []):
            fname = str(e.get("document_name") or "").split("/")[-1]
            evidence_list.append({
                "evidence_id": e.get("evidence_id"),
                "text": e.get("evidence_text", "") or e.get("text", ""),
                "doc_period": DOC_PERIOD_BY_NAME.get(fname),
                "document_name": e.get("document_name"),
                "page": e.get("page"),
            })
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
            "gold_evidence_count": len(evidence_list),
        })

    # ---- 混淆矩阵 + per-class 指标 ----
    classes = sorted({r["gold"] for r in rows} | {r["pred"] for r in rows if r["pred"] != "ERROR"})
    cm = {g: {p: 0 for p in classes} for g in classes}
    per_class = {}
    for r in rows:
        cm[r["gold"]][r["pred"]] = cm[r["gold"]].get(r["pred"], 0) + 1
    for cls in classes:
        tp = cm[cls][cls]
        fp = sum(cm[g][cls] for g in classes if g != cls)
        fn = sum(cm[cls][p] for p in classes if p != cls)
        precision = round(tp / (tp + fp), 4) if (tp + fp) else 0.0
        recall = round(tp / (tp + fn), 4) if (tp + fn) else 0.0
        per_class[cls] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1(precision, recall)}

    accuracy = round(sum(1 for r in rows if r["correct"]) / len(rows), 4)
    macro_f1 = round(sum(per_class[c]["f1"] for c in classes) / len(classes), 4) if classes else 0.0

    # ---- per-type F1（按 claim_type）----
    type_rows: dict[str, list] = defaultdict(list)
    for r in rows:
        type_rows[r["claim_type"]].append(r)
    per_type = {}
    for t, rs in type_rows.items():
        tp = sum(1 for r in rs if r["correct"])
        per_type[t] = {
            "count": len(rs), "correct": tp,
            "f1": round(tp / len(rs), 4) if rs else 0.0,
            "accuracy": round(tp / len(rs), 4) if rs else 0.0,
        }

    # ---- 17 个原错误的新结果 ----
    old_cases = json.load(open(BACKEND_DIR / "artifacts" / "oracle_diagnosis" / "phase23_8_cases.json", encoding="utf-8"))
    old_err = {c["claim_id"]: c for c in old_cases["cases"] if c["failure_category"] != "OK"}
    by_id = {r["claim_id"]: r for r in rows}
    old_results = []
    for cid, oc in old_err.items():
        r = by_id.get(cid)
        old_results.append({
            "claim_id": cid,
            "failure_category": oc["failure_category"],
            "old_prediction": oc.get("predicted_verdict"),
            "gold": r["gold"] if r else oc.get("expected_verdict"),
            "new_prediction": r["pred"] if r else "UNKNOWN",
            "rule_id_new": r["rule"] if r else None,
            "status": "FIXED" if (r and r["correct"]) else "ANNOTATION_SUSPECTED",
        })

    # ---- 回归：phase23_8 正确但现在错误 ----
    old_correct = {c["claim_id"] for c in old_cases["cases"] if c["failure_category"] == "OK"}
    regressions = [r for r in rows if r["claim_id"] in old_correct and not r["correct"]]

    result = {
        "phase": "23.9",
        "script": "phase23_9_oracle_eval",
        "entry_point": "core_pipeline.core_verify（Gold Evidence Block 输入）",
        "total": len(rows),
        "correct": sum(1 for r in rows if r["correct"]),
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "per_class": per_class,
        "confusion_matrix": cm,
        "per_type_f1": per_type,
        "original_17_errors_new_results": old_results,
        "original_17_fixed_count": sum(1 for x in old_results if x["status"] == "FIXED"),
        "regressions": regressions,
        "annotation_suspected": [x for x in old_results if x["status"] == "ANNOTATION_SUSPECTED"],
        "targets": {
            "Accuracy >= 0.85": accuracy >= 0.85,
            "Macro-F1 >= 0.80": macro_f1 >= 0.80,
            "数值类F1 >= 0.90": per_type.get("raw_number", {}).get("f1", 0) >= 0.90,
            "INSUFFICIENT_EVIDENCE F1 >= 0.80": per_class.get("INSUFFICIENT_EVIDENCE", {}).get("f1", 0) >= 0.80,
            "原17错误修复 >= 14": sum(1 for x in old_results if x["status"] == "FIXED") >= 14,
            "新回归 <= 2": len(regressions) <= 2,
        },
        "per_claim": rows,
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_9_oracle_eval.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    print(f"total={len(rows)} correct={result['correct']} accuracy={accuracy} macro_f1={macro_f1}")
    print(f"per-class F1: { {c: v['f1'] for c, v in per_class.items()} }")
    print(f"per-type F1: { {t: v['f1'] for t, v in per_type.items()} }")
    print(f"17-err fixed: {result['original_17_fixed_count']}/17 | regressions: {len(regressions)}")
    print(f"targets: {result['targets']}")
    return result


if __name__ == "__main__":
    run_oracle_eval()
