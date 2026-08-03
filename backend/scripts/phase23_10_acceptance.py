#!/usr/bin/env python3
"""Phase 23.10 — Acceptance 汇总：读取全部 Phase 23.10 产物，检查完成标准。

产物依赖（须先运行）：
  python scripts/phase23_10_leakage_audit.py
  python scripts/phase23_10_metamorphic_eval.py
  python scripts/phase23_10_failure_diagnosis.py
  python scripts/phase23_10_reranker_eval.py
  python scripts/phase23_10_hard_negative.py
  python scripts/phase23_10_leave_one_company_out.py
  python scripts/phase23_10_e2e.py
  python scripts/phase23_10_metric_integrity.py

输出：backend/artifacts/phase23_10_acceptance.json

用法:
    cd backend
    python scripts/phase23_10_acceptance.py
"""

from __future__ import annotations

import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS = BACKEND_DIR / "artifacts"


def _load(rel: str) -> dict | None:
    p = ARTIFACTS / rel
    if not p.exists():
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def run_acceptance() -> dict:
    leak = _load("integrity/phase23_10_oracle_leakage_audit.json")
    meta = _load("integrity/phase23_10_metamorphic_results.json")
    diag = _load("retrieval/phase23_10_failure_diagnosis.json")
    metrics = _load("retrieval/phase23_10_metrics.json")
    hard = _load("retrieval/phase23_10_hard_negatives.json")
    loo = _load("retrieval/phase23_10_leave_one_company_out.json")
    integrity = _load("retrieval/phase23_10_metric_integrity.json")
    e2e = _load("e2e/phase23_10_development_e2e.json")
    oracle = _load("oracle/phase23_9_oracle_eval.json")

    m = (metrics or {}).get("metrics", {})
    meta_rates = (meta or {}).get("rates", {})
    loo_full = (loo or {}).get("full_development_with_stable_weights", {})
    e2e_errd = (e2e or {}).get("error_decomposition", {})

    checks = {
        "1_leakage_audit_clean": bool(leak and leak.get("final_status") == "CLEAN"),
        "2_no_claim_specific_hardcode": bool(leak and not leak.get("runtime_claim_id_branches")),
        "3_metamorphic_invariance_ge90": bool(meta_rates.get("invariance", 0) >= 0.90),
        "4_metamorphic_contradiction_ge90": bool(meta_rates.get("contradiction", 0) >= 0.90),
        "5_candidate_page_recall50_ge095": bool(m.get("stage_a_page_recall_50", 0) >= 0.95),
        "6_candidate_block_recall50_ge090": bool(m.get("stage_a_block_recall_50", 0) >= 0.90),
        "7_page_hit5_ge080": bool(m.get("page_hit_5", 0) >= 0.80),
        "8_block_hit5_ge070": bool(m.get("block_hit_5", 0) >= 0.70),
        "9_recall5_ge080": bool(m.get("recall_at_5", 0) >= 0.80),
        "10_mrr_ge060": bool(m.get("mrr_page", 0) >= 0.60),
        "11_no_result_le005": bool(m.get("no_result_rate", 1) <= 0.05),
        "12_e2e_accuracy_ge075": bool(e2e and e2e.get("accuracy", 0) >= 0.75),
        "13_e2e_macro_f1_ge065": bool(e2e and e2e.get("macro_f1", 0) >= 0.65),
        "14_retrieval_failure_le5": bool(e2e_errd.get("retrieval_failure", 99) <= 5),
        "15_oracle_accuracy_ge090": bool(oracle and oracle.get("accuracy", 0) >= 0.90),
        "16_oracle_macro_f1_ge085": bool(oracle and oracle.get("macro_f1", 0) >= 0.85),
        "17_hitk_monotonicity": bool(metrics and metrics.get("all_invariants_passed")),
        "18_loo_no_leakage": bool(loo and all(f.get("leakage_note") for f in loo.get("folds", []))),
    }
    missing = [name for name, d in [
        ("phase23_10_oracle_leakage_audit.json", leak),
        ("phase23_10_metamorphic_results.json", meta),
        ("phase23_10_failure_diagnosis.json", diag),
        ("phase23_10_metrics.json", metrics),
        ("phase23_10_hard_negatives.json", hard),
        ("phase23_10_leave_one_company_out.json", loo),
        ("phase23_10_metric_integrity.json", integrity),
        ("phase23_10_development_e2e.json", e2e),
    ] if d is None]

    result = {
        "phase": "23.10",
        "script": "phase23_10_acceptance",
        "generated_artifacts": {
            "leakage_audit": bool(leak), "metamorphic": bool(meta), "failure_diagnosis": bool(diag),
            "metrics": bool(metrics), "hard_negatives": bool(hard), "leave_one_out": bool(loo),
            "metric_integrity": bool(integrity), "e2e": bool(e2e),
        },
        "missing_artifacts": missing,
        "key_numbers": {
            "oracle_accuracy": (oracle or {}).get("accuracy"),
            "oracle_macro_f1": (oracle or {}).get("macro_f1"),
            "metamorphic_rates": meta_rates,
            "stage_a_page_recall_50": m.get("stage_a_page_recall_50"),
            "stage_a_block_recall_50": m.get("stage_a_block_recall_50"),
            "page_hit_5": m.get("page_hit_5"),
            "block_hit_5": m.get("block_hit_5"),
            "recall_at_5": m.get("recall_at_5"),
            "mrr_page": m.get("mrr_page"),
            "no_result_rate": m.get("no_result_rate"),
            "e2e_accuracy": (e2e or {}).get("accuracy"),
            "e2e_macro_f1": (e2e or {}).get("macro_f1"),
            "e2e_error_decomposition": e2e_errd,
        },
        "acceptance_checks": checks,
        "passed_checks": [k for k, v in checks.items() if v is True],
        "failed_checks": [k for k, v in checks.items() if v is False],
        "readiness": "READY" if not [k for k, v in checks.items() if v is False] and not missing else "NOT_READY",
        "readiness_note": "READY 需同时满足 18 项检查无 False + 产物齐全 + 外部验证（pytest×5/build×3/评测×2/新 commit）",
    }
    out = ARTIFACTS / "phase23_10_acceptance.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(f"missing: {missing}")
    print(f"failed_checks: {result['failed_checks']}")
    print(f"readiness: {result['readiness']}")
    return result


if __name__ == "__main__":
    run_acceptance()
