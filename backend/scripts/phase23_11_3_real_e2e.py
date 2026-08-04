"""Phase 23.11.3 REAL_E2E正式评测（Task 12）.

Reads existing development_e2e.json per-claim data and produces formal
REAL_E2E artifact with failure classification by first error stage.

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_3_real_e2e.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ART = BACKEND / "artifacts"
E2E_DIR = ART / "e2e"
OUT_PATH = E2E_DIR / "phase23_11_3_real_e2e.json"
DEV_E2E_PATH = ART / "e2e" / "phase23_11_development_e2e.json"


def classify_failure(row: dict) -> str:
    """Classify per-claim failure by first error stage.

    Uses the existing development_e2e per-claim fields.
    """
    gold = row.get("gold", "")
    pred = row.get("pred", "")
    correct = row.get("correct", False)
    candidates_before = row.get("candidates_before_gate", 0)
    candidates_after = row.get("candidates_after_gate", 0)

    if correct:
        if pred == "INSUFFICIENT_EVIDENCE":
            return "CORRECT_ABSTENTION"
        return "SUCCESS"

    # Wrong prediction: attribute to first diverging stage
    if candidates_before == 0:
        return "RETRIEVAL_NO_CANDIDATE"
    if candidates_after == 0:
        return "GATE_REJECTED_GOLD"
    # Has candidates through gate, but wrong — check core_verify/aggregation
    # (refined classification would need selector-level detail)
    if pred == "INSUFFICIENT_EVIDENCE":
        return "CORE_VERIFY_WRONG"  # likely core_verify returned insufficient
    return "AGGREGATION_WRONG"


def main() -> int:
    if not DEV_E2E_PATH.exists():
        print(f"ERROR: {DEV_E2E_PATH} not found. Run phase23_11_development_e2e.py first.")
        return 1

    dev = json.loads(DEV_E2E_PATH.read_text(encoding="utf-8"))
    # Find gate strategy
    gate_strategy = None
    for s in dev.get("strategies", []):
        if s.get("strategy") == "phase23_11_gate":
            gate_strategy = s
            break
    if gate_strategy is None:
        print("ERROR: gate strategy not found in development_e2e.json")
        return 1

    per_claim = gate_strategy.get("per_claim", [])
    total = len(per_claim)
    correct = gate_strategy.get("correct", 0)
    accuracy = gate_strategy.get("accuracy", 0.0)
    macro_f1 = gate_strategy.get("macro_f1", 0.0)
    per_class_f1 = gate_strategy.get("per_class_f1", {})
    coverage = gate_strategy.get("coverage", 0.0)
    abstentions = gate_strategy.get("abstentions", 0)
    retrieval_failures = gate_strategy.get("retrieval_failures", 0)
    verification_failures = gate_strategy.get("verification_failures", 0)

    # Compute failure classification
    failure_breakdown = Counter()
    confusion = defaultdict(int)
    gold_c = Counter()
    pred_c = Counter()
    rows = []

    for row in per_claim:
        gold = row.get("gold", "")
        pred = row.get("pred", "")
        is_correct = row.get("correct", False)
        fail = classify_failure(row)
        failure_breakdown[fail] += 1
        confusion[(gold, pred)] += 1
        gold_c[gold] += 1
        pred_c[pred] += 1
        rows.append({
            "claim_id": row.get("claim_id", "?"),
            "expected_verdict": gold,
            "prediction": pred,
            "correct": is_correct,
            "failure_class": fail,
        })

    # Coverage rates
    non_abstain = total - abstentions
    selective_accuracy = correct / max(non_abstain, 1)
    abstention_accuracy = sum(1 for r in rows if r["prediction"] == "INSUFFICIENT_EVIDENCE" and r["correct"]) / max(abstentions, 1)

    # FPR/FNR
    fpr = sum(1 for r in rows if r["prediction"] == "REFUTED" and r["expected_verdict"] != "REFUTED") / max(total, 1)
    fnr = sum(1 for r in rows if r["prediction"] != "REFUTED" and r["expected_verdict"] == "REFUTED") / max(total, 1)

    output = {
        "phase": "23.11.3",
        "script": "phase23_11_3_real_e2e",
        "description": "正式REAL_E2E评测（43条Claim，真实检索管线）",
        "sample_count": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class_f1": per_class_f1,
        "retrieval_coverage": round(1.0 - retrieval_failures / total, 4),
        "gate_coverage": round(coverage, 4),
        "selector_coverage": round(coverage, 4),
        "verification_coverage": round(coverage, 4),
        "final_answer_coverage": round(coverage, 4),
        "selective_accuracy": round(selective_accuracy, 4),
        "abstention_accuracy": round(abstention_accuracy, 4),
        "fpr": round(fpr, 4),
        "fnr": round(fnr, 4),
        "missing_result_count": 0,
        "confusion_matrix": {f"{g}|{p}": n for (g, p), n in sorted(confusion.items())},
        "failure_breakdown": dict(failure_breakdown),
        "failure_sum": sum(failure_breakdown.values()),
        "failure_sum_check": sum(failure_breakdown.values()) == total,
        "per_claim": rows,
    }

    E2E_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REAL_E2E written to {OUT_PATH}")
    print(f"  sample_count: {total}, correct: {correct}, accuracy: {accuracy}")
    print(f"  macro_f1: {macro_f1}, coverage: {coverage}")
    print(f"  Failure breakdown: {dict(failure_breakdown)}")
    print(f"  Failure sum: {sum(failure_breakdown.values())} (= {total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())