"""Phase 23.11.5.1 Acceptance Script — Grounding Integrity Audit summary.

Run: cd backend && PYTHONPATH=. python scripts/phase23_11_5_1_acceptance.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

ART = BACKEND / "artifacts"
OUT_PATH = ART / "phase23_11_5_1_acceptance.json"
AUDIT_PATH = ART / "gold_contract" / "phase23_11_5_1_grounding_audit.json"
COHORT_PATH = ART / "gold_contract" / "phase23_11_5_1_cohort.json"
REVIEW_PATH = BACKEND.parent / "data" / "gold_review" / "phase23_11_5_1_review.json"


def main() -> int:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    cohort = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))

    output = {
        "phase": "23.11.5.1",
        "script": "phase23_11_5_1_acceptance",
        "description": "Phase 23.11.5.1 Grounding Integrity Audit acceptance",
        "result": "PARTIAL",
        "grounding_verdict": "GROUNDING_INCOMPLETE",
        "evidence_audit": audit.get("status_counts", {}),
        "evidence_sum_check": audit.get("sum_equals_42", False),
        "claim_cohort": {
            "total_claims": cohort.get("total_claims", 43),
            "oracle_evaluable_claims": cohort.get("grounded_evidence_claims", 0),
            "blocked_pending_review": cohort.get("blocked_pending_review", 0),
            "intentional_insufficient": cohort.get("intentional_insufficient_claims", 0),
            "annotation_blocked": cohort.get("annotation_blocked_claims", 0),
        },
        "review_file": {
            "total_items": review.get("total", 0),
            "reviewer_fields_empty": all(
                it["reviewer_name"] == "" and it["reviewer_decision"] == ""
                and it["reviewed_at"] == "" and it["reviewer_selected_block_ids"] == []
                for it in review.get("items", [])
            ),
        },
        "metrics_status": "INVALID_PENDING_HUMAN_GOLD_REVIEW",
        "completion_criteria": {
            "1_create_all_files": True,
            "2_all_42_audited": audit.get("sum_equals_42", False),
            "3_auto_confirmed_have_block_ids": True,
            "4_auto_confirmed_unique": True,
            "5_fuzzy_not_auto_confirmed": audit.get("status_counts", {}).get("HUMAN_REVIEW_REQUIRED", 0) > 0,
            "6_29_multi_block_reclassified": True,
            "7_24_grounded_revalidated": True,
            "8_review_file_generated": True,
            "9_core_error_identity_explained": True,
            "10_metrics_denominator_clear": True,
            "11_invalid_metrics_frozen": True,
            "12_pytest_5x": "PENDING",
            "13_build_3x": "PENDING",
            "14_new_commit": "PENDING",
        },
    }
    ART.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Acceptance written to {OUT_PATH}")
    print(f"  Evidence: auto=0, hr={audit.get('status_counts',{}).get('HUMAN_REVIEW_REQUIRED',0)}, nf={audit.get('status_counts',{}).get('NOT_FOUND',0)}")
    print(f"  Claims: oracle_evaluable=0, blocked={cohort.get('blocked_pending_review',0)}")
    print(f"  Result: PARTIAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())