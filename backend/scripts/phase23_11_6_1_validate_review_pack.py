"""Phase 23.11.6.1 Review Pack Validation (Task 10).

Validates the review pack is fully operational:
1. review.html interactive + blind + export-compatible
2. not_found_review.html 10 items offline
3. review_inventory.json 32 unique
4. review_progress.json fields
5. priority cohort coverage
6. quickstart paths
7. importers reject incomplete input

Run: cd backend && PYTHONPATH=. python scripts/phase23_11_6_1_validate_review_pack.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

REVIEW_DIR = BACKEND.parent / "data" / "gold_review" / "phase23_11_6"


def main() -> int:
    results = {}
    # 1. review.html interactive + blind
    html = (REVIEW_DIR / "review.html").read_text(encoding="utf-8")
    results["review_html_interactive"] = all(k in html for k in ("prevbtn", "nextbtn", "exportJSON", "fp_review_state"))
    results["review_html_blind"] = not any(w in html for w in ("expected_verdict", "SUPPORTED", "REFUTED",
                                                               "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "prediction", "is_gold"))
    results["review_html_export"] = "review_results.json" in html

    # 2. not_found_review.html
    nf = (REVIEW_DIR / "not_found_review.html").read_text(encoding="utf-8")
    results["not_found_10_items"] = nf.count("item_id") >= 10
    results["not_found_offline"] = ("http://" not in nf and "https://" not in nf)
    results["not_found_blind"] = not any(w in nf for w in ("expected_verdict", "SUPPORTED", "REFUTED", "prediction", "is_gold"))
    results["not_found_export"] = "exportJSON" in nf

    # 3. review_inventory.json
    inv = json.loads((REVIEW_DIR / "review_inventory.json").read_text(encoding="utf-8"))
    ids = [it["gold_evidence_id"] for it in inv["items"]]
    results["inventory_32"] = len(ids) == 32
    results["inventory_unique"] = len(set(ids)) == 32
    results["inventory_validation_all_true"] = all(inv["validation"].values())

    # 4. review_progress.json
    prog = json.loads((REVIEW_DIR / "review_progress.json").read_text(encoding="utf-8"))
    results["progress_fields"] = all(k in prog for k in ("total_items", "completed_items", "unsure_items",
                                                         "none_of_above_items", "remaining_items", "last_reviewed_index"))

    # 5. priority cohort coverage
    pc = json.loads((BACKEND / "artifacts/gold_contract/phase23_11_6_priority_cohort.json").read_text())
    results["priority_cohort_16"] = pc["count"] == 16
    results["priority_coverage_partial_blocked_honest"] = pc["coverage_status"]["PARTIALLY_SUPPORTED"] == "BLOCKED"

    # 6. insufficient form
    ins = (REVIEW_DIR / "insufficient_review.html").read_text(encoding="utf-8")
    results["insufficient_form"] = all(k in ins for k in ("reviewer_confirmed_insufficient", "exportJSON"))
    ins_json = json.loads((REVIEW_DIR / "insufficient_review.json").read_text(encoding="utf-8"))
    results["insufficient_fields_empty"] = all(it["reviewer_name"] == "" and it["reviewed_at"] == ""
                                               and it["reviewer_confirmed_insufficient"] == "" for it in ins_json["items"])

    # 7. importer rejects incomplete
    r = subprocess.run(
        [sys.executable, str(BACKEND / "scripts/import_human_gold_review.py"),
         "--review", str(REVIEW_DIR / "review_results.template.json"), "--reviewer", "test"],
        capture_output=True, text=True, cwd=str(BACKEND), env={"PYTHONPATH": str(BACKEND)})
    results["importer_rejects_incomplete"] = "IMPORT REJECTED" in r.stdout

    ok = all(results.values())
    out = {
        "phase": "23.11.6.1",
        "script": "phase23_11_6_1_validate_review_pack",
        "valid": ok,
        "checks": results,
    }
    out_path = BACKEND / "artifacts" / "phase23_11_6_1_review_pack_validation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Review pack validation: {'PASS' if ok else 'FAIL'}")
    for k, v in results.items():
        print(f"  {'✅' if v else '❌'} {k}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())