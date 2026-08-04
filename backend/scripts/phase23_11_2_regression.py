"""Phase 23.11.2 Regression Verification (Task 10).

Compares Phase 23.11.1 vs Phase 23.11.2 per-claim for the 37 original
abstentions (§11). Outputs phase23_11_2_abstention_diff.json with:
- old_gate_result / new_gate_result
- old_selector_result / new_selector_result
- old_verdict / new_verdict / gold_verdict
- fixed / regression

Targets (§11):
- ≥30/37 Gold Evidence no longer wrongly rejected
- ≤3 new noise误接收导致的错误
- All regression cases单独列出

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_2_regression.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

ART = BACKEND / "artifacts"
E2E_DIR = ART / "e2e"
OUT_PATH = E2E_DIR / "phase23_11_2_abstention_diff.json"

# Phase 23.11.1 abstention diagnosis (37 entries)
OLD_ABSTENTION_PATH = E2E_DIR / "phase23_11_abstention_diagnosis.json"
# Phase 23.11.2 REAL_E2E result (new)
NEW_E2E_PATH = E2E_DIR / "phase23_11_2_real_e2e.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    old_abstentions = load_json(OLD_ABSTENTION_PATH)
    if not isinstance(old_abstentions, list):
        print(f"No old abstentions found at {OLD_ABSTENTION_PATH}")
        return 1
    new_e2e = load_json(NEW_E2E_PATH)
    new_per_claim = {r["claim_id"]: r for r in new_e2e.get("per_claim", [])} if new_e2e else {}

    diff_rows: list[dict] = []
    fixed_count = 0
    regression_count = 0
    still_abstain_count = 0

    for old in old_abstentions:
        cid = old.get("claim_id")
        new = new_per_claim.get(cid, {})
        old_verdict = old.get("final_verdict") or old.get("pred") or "INSUFFICIENT_EVIDENCE"
        new_verdict = new.get("pred", "UNKNOWN")
        gold = old.get("expected_verdict") or new.get("gold") or "UNKNOWN"

        old_gate = {
            "candidates_before": old.get("candidates_before_gate", 0),
            "candidates_after": old.get("candidates_after_gate", 0),
            "selected_count": old.get("selected_count", 0),
        }
        new_gate = {
            "candidates_before": new.get("candidates_before_gate", 0),
            "candidates_after": new.get("candidates_after_gate", 0),
        }
        new_sel_count = len(new.get("selected", [])) if isinstance(new.get("selected"), list) else 0

        old_abstain = old_verdict == "INSUFFICIENT_EVIDENCE"
        new_abstain = new_verdict == "INSUFFICIENT_EVIDENCE"

        # fixed: was abstain (wrongly) and now non-abstain matching gold
        fixed = old_abstain and (not new_abstain) and (new_verdict == gold)
        # regression: was correct (non-abstain matching gold) and now wrong
        old_correct = (not old_abstain) and (old_verdict == gold)
        new_correct = (not new_abstain) and (new_verdict == gold)
        regression = old_correct and (not new_correct)
        # still abstain
        if new_abstain:
            still_abstain_count += 1
        if fixed:
            fixed_count += 1
        if regression:
            regression_count += 1

        diff_rows.append({
            "claim_id": cid,
            "company": old.get("company"),
            "route": old.get("route"),
            "gold_verdict": gold,
            "old_verdict": old_verdict,
            "new_verdict": new_verdict,
            "old_gate_result": old_gate,
            "new_gate_result": new_gate,
            "old_selector_result": {"selected_count": old.get("selected_count", 0)},
            "new_selector_result": {"selected_count": new_sel_count},
            "old_abstention_reason": old.get("abstention_reason"),
            "fixed": fixed,
            "regression": regression,
            "still_abstain": new_abstain,
        })

    # §11 targets
    target_min_fixed = 30
    target_max_noise_regressions = 3

    regressions_only = [r for r in diff_rows if r["regression"]]

    output = {
        "phase": "23.11.2",
        "script": "phase23_11_2_regression",
        "description": "Per-claim diff of 37 original abstentions: Phase 23.11.1 vs 23.11.2",
        "baseline": {
            "phase23_11_1_abstentions": len(old_abstentions),
            "phase23_11_1_commit": "3de338f",
        },
        "summary": {
            "total_original_abstentions": len(old_abstentions),
            "fixed_count": fixed_count,
            "still_abstain_count": still_abstain_count,
            "regression_count": regression_count,
            "target_min_fixed": target_min_fixed,
            "target_max_noise_regressions": target_max_noise_regressions,
            "fixed_target_met": fixed_count >= target_min_fixed,
            "noise_regression_target_met": regression_count <= target_max_noise_regressions,
        },
        "regressions_listed": regressions_only,
        "diff": diff_rows,
    }
    E2E_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Abstention diff written to {OUT_PATH}")
    print(f"  total original abstentions: {len(old_abstentions)}")
    print(f"  fixed (now correct): {fixed_count}")
    print(f"  still abstain: {still_abstain_count}")
    print(f"  regressions: {regression_count}")
    print(f"  target ≥30 fixed: {'MET' if fixed_count >= 30 else 'MISS'} ({fixed_count})")
    print(f"  target ≤3 noise regressions: {'MET' if regression_count <= 3 else 'MISS'} ({regression_count})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
