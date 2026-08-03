#!/usr/bin/env python3
"""Phase 23.9 — 两折公司留一 Cross-validation（Development 明确标记，非 Blind）。

背景修复（Phase 23.9）：
- Phase 23.8 为「三折公司留一」，但宁德时代无完整 Gold 标注 → Fold 2 SKIPPED，
  仍自称三折且 SKIPPED 被计入平均，不合规。
- 修复：明确改为「两折公司留一」——
  Fold 1：评测公司 = 美的集团（demo，26 条 Development Claims）
  Fold 2：评测公司 = 五粮液（holdout，17 条 Development Claims）
  - 宁德时代无 Gold → 不得伪造 Gold，不作为评测折；不把 SKIPPED 计入平均值。
  - 所有 Fold 输出相同指标（Oracle Accuracy/Macro-F1、Real-E2E Accuracy/Macro-F1、
    样本数说明、No-result Rate）。
  - 明确标记为 Development Cross-validation，不是真正 Blind Holdout。
  - 完成后若人工补全宁德 Gold，可恢复三折（本阶段不执行）。

用法:
    cd backend
    python scripts/phase23_9_company_leave_one_out.py
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "cross_validation"

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


def macro_f1(preds: list[str], golds: list[str]) -> float:
    classes = sorted(set(golds) | set(preds))
    fs = []
    for cls in classes:
        tp = sum(1 for p, g in zip(preds, golds) if p == g == cls)
        fp = sum(1 for p, g in zip(preds, golds) if p == cls and g != cls)
        fn = sum(1 for p, g in zip(preds, golds) if p != cls and g == cls)
        p_, r_ = (tp / (tp + fp)) if (tp + fp) else 0.0, (tp / (tp + fn)) if (tp + fn) else 0.0
        fs.append(f1(p_, r_))
    return round(sum(fs) / len(fs), 4) if fs else 0.0


def load_gold(dataset: str):
    claims = json.load(open(DATA_DIR / dataset / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])
    evs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_evidence.json", encoding="utf-8")).get("evidence", [])
    vrs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_verifications.json", encoding="utf-8")).get("verifications", [])
    ev_by: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        ev_by[e.get("claim_id", "")].append(e)
    vr_by = {v.get("claim_id", ""): v for v in vrs}
    return claims, dict(ev_by), vr_by


def run_two_fold() -> dict:
    _ensure_app_on_path()
    from app.db import SessionLocal, init_db
    from app.services import document_service
    from app.services.evidence_retrieval.service import retrieve_for_claim
    from app.services.verification.core_pipeline import IntegrationTrace, core_verify

    # 干净库 + 导入 Development 源文档（demo: 年报/半年报/一季报；holdout: 年报）
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
    from app.models import Document
    doc_by_name = {d.original_filename: d.id for d in session.query(Document).all()}

    demo_claims, demo_ev, demo_vr = load_gold("demo")
    holdout_claims, holdout_ev, holdout_vr = load_gold("holdout")

    # 两折公司留一（宁德时代无 Gold → 不作为评测折，不伪造）
    folds = [
        {"fold": 1, "eval_company": "美的集团", "dataset": "demo",
         "claims": demo_claims, "ev": demo_ev, "vr": demo_vr},
        {"fold": 2, "eval_company": "五粮液", "dataset": "holdout",
         "claims": holdout_claims, "ev": holdout_ev, "vr": holdout_vr},
    ]

    fold_results = []
    for fold in folds:
        claims = fold["claims"]
        rows = []
        for claim in claims:
            cid = claim["claim_id"]
            gold = fold["vr"].get(cid, {}).get("expected_verdict", "UNKNOWN")
            gold_evs = fold["ev"].get(cid, [])
            gold_pages = set()
            for e in gold_evs:
                did = doc_by_name.get(str(e.get("document_name") or "").split("/")[-1])
                if did is not None and e.get("page") is not None:
                    gold_pages.add((did, e["page"]))
            # ---- Oracle：Gold Evidence Block 输入 ----
            oracle_ev = []
            for e in gold_evs:
                fname = str(e.get("document_name") or "").split("/")[-1]
                oracle_ev.append({
                    "evidence_id": e.get("evidence_id"),
                    "text": e.get("evidence_text", "") or e.get("text", ""),
                    "doc_period": DOC_PERIOD_BY_NAME.get(fname),
                    "document_name": e.get("document_name"), "page": e.get("page"),
                })
            try:
                vr_o = core_verify(claim, oracle_ev, IntegrationTrace(claim_id=cid))
                oracle_pred = vr_o.verification_status
            except Exception as exc:  # noqa: BLE001
                oracle_pred = "ERROR"
            # ---- Real E2E：真实检索 Top-5 ----
            try:
                cands = retrieve_for_claim(session, claim, top_k=5) or []
            except Exception as exc:  # noqa: BLE001
                cands = []
            e2e_ev = [{
                "evidence_id": c.get("block_id"), "block_id": c.get("block_id"),
                "text": c.get("block_text", "") or "", "doc_period": None,
                "document_name": None, "page": c.get("page_number"),
            } for c in cands]
            try:
                vr_e = core_verify(claim, e2e_ev, IntegrationTrace(claim_id=cid))
                e2e_pred = vr_e.verification_status
            except Exception as exc:  # noqa: BLE001
                e2e_pred = "ERROR"
            gold_page_in_top5 = any((c.get("document_id"), c.get("page_number")) in gold_pages for c in cands[:5])
            rows.append({
                "claim_id": cid, "gold": gold, "oracle_pred": oracle_pred, "e2e_pred": e2e_pred,
                "oracle_correct": oracle_pred == gold, "e2e_correct": e2e_pred == gold,
                "gold_page_in_top5": gold_page_in_top5, "retrieved": len(cands),
                "no_result": len(cands) == 0,
            })

        n = len(rows)
        oracle_acc = round(sum(1 for r in rows if r["oracle_correct"]) / n, 4)
        e2e_acc = round(sum(1 for r in rows if r["e2e_correct"]) / n, 4)
        oracle_mf1 = macro_f1([r["oracle_pred"] for r in rows], [r["gold"] for r in rows])
        e2e_mf1 = macro_f1([r["e2e_pred"] for r in rows], [r["gold"] for r in rows])
        no_result_rate = round(sum(1 for r in rows if r["no_result"]) / n, 4)
        evidence_recall5 = round(sum(1 for r in rows if r["gold_page_in_top5"]) / n, 4)
        fold_results.append({
            "fold": fold["fold"],
            "eval_company": fold["eval_company"],
            "dataset": fold["dataset"],
            "sample_count": n,
            "sample_claims": [r["claim_id"] for r in rows],
            "oracle": {"accuracy": oracle_acc, "macro_f1": oracle_mf1},
            "real_e2e": {"accuracy": e2e_acc, "macro_f1": e2e_mf1,
                         "no_result_rate": no_result_rate, "evidence_recall_at_5": evidence_recall5},
            "per_claim": rows,
        })

    # 平均 = 两折可用折平均（宁德不作为折，无 SKIPPED 计入）
    avg_oracle_acc = round(sum(f["oracle"]["accuracy"] for f in fold_results) / len(fold_results), 4)
    avg_oracle_mf1 = round(sum(f["oracle"]["macro_f1"] for f in fold_results) / len(fold_results), 4)
    avg_e2e_acc = round(sum(f["real_e2e"]["accuracy"] for f in fold_results) / len(fold_results), 4)
    avg_e2e_mf1 = round(sum(f["real_e2e"]["macro_f1"] for f in fold_results) / len(fold_results), 4)

    result = {
        "phase": "23.9",
        "script": "phase23_9_company_leave_one_out",
        "validation_type": "Development Cross-validation（两折公司留一）",
        "not_blind_note": "这是 Development Cross-validation，不是真正 Blind Holdout。"
                          "Blind Holdout 仍需两家新公司文件 + 人工 Gold 确认，当前仍 BLOCKED。",
        "fix_note": "Phase 23.8 的三折含宁德时代 SKIPPED 折且计入平均，已修正为两折："
                    "宁德时代无 Gold，不伪造、不作为评测折、不计入平均。人工补全宁德 Gold 后可恢复三折。",
        "folds": fold_results,
        "averages": {
            "oracle": {"accuracy": avg_oracle_acc, "macro_f1": avg_oracle_mf1},
            "real_e2e": {"accuracy": avg_e2e_acc, "macro_f1": avg_e2e_mf1},
            "note": "仅对两折（美的/五粮液）平均；宁德时代 SKIPPED 不计入平均",
        },
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_9_company_leave_one_out.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    for f in fold_results:
        print(f"Fold{f['fold']} {f['eval_company']}: n={f['sample_count']} "
              f"Oracle acc/mf1={f['oracle']['accuracy']}/{f['oracle']['macro_f1']} "
              f"E2E acc/mf1={f['real_e2e']['accuracy']}/{f['real_e2e']['macro_f1']}")
    print(f"AVG Oracle acc/mf1={avg_oracle_acc}/{avg_oracle_mf1} | AVG E2E acc/mf1={avg_e2e_acc}/{avg_e2e_mf1}")
    return result


if __name__ == "__main__":
    run_two_fold()
