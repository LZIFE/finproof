"""Phase 23.11.6 Post-Review Validation Runner (Task 9).

Run ONLY after human review results are imported. If no human review exists,
stop immediately and output WAITING_FOR_HUMAN_REVIEW — do NOT compute frozen metrics.

Run: cd backend && PYTHONPATH=. python scripts/run_post_review_validation.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

GOLD_V2 = BACKEND.parent / "data" / "annotations" / "gold_evidence_v2.json"
MANIFEST = BACKEND.parent / "data" / "gold_manifest.json"


def main() -> int:
    # 1. Check imported human review exists
    if not GOLD_V2.exists():
        print("WAITING_FOR_HUMAN_REVIEW")
        print("  Reason: data/annotations/gold_evidence_v2.json does not exist — human review not imported yet.")
        print("  Frozen metrics (Gate Precision/Recall, Accepted Noise Rate, Rejected Gold Rate,")
        print("  Gold Top1/Top3, Block Hit@K, all Development Oracle metrics) will NOT be computed.")
        print("  Run: python scripts/import_human_gold_review.py --review <review_results.json> --reviewer <name>")
        return 0

    gold_v2 = json.loads(GOLD_V2.read_text(encoding="utf-8"))
    confirmed = [e for e in gold_v2.get("evidence", []) if e.get("gold_confirm_status") == "CONFIRMED"]
    if not confirmed:
        print("WAITING_FOR_HUMAN_REVIEW")
        print("  Reason: gold_evidence_v2.json exists but 0 evidence CONFIRMED.")
        return 0

    # 2. Human review exists → run validation pipeline (blocked in this phase)
    print("HUMAN_REVIEW_IMPORTED")
    print(f"  Confirmed evidence: {len(confirmed)}")
    print("  Post-review pipeline (Manifest verify → Cohort recompute → Single-Gold →")
    print("  CORE_ORACLE → NOISY_ORACLE → REAL_E2E → Block Hit@K → Gate Precision/Recall)")
    print("  will run in a later phase per phase23_11_6 §10. Not executed now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())