"""Phase 23.11.3 §5 Verdict Mapping Table & Coverage Test.

Generates backend/artifacts/aggregation/phase23_11_3_verdict_mapping.json:

- 完整映射表 (canonical passthrough + legacy internal + extended conflict/ambiguous
  + unknown fallback)
- 全状态覆盖测试: every known internal status + adversarial inputs must map
  through normalize_verdict_for_evaluation() — the SINGLE function that Oracle /
  Noisy Oracle / Real E2E / confusion matrix / API must all call.

Forbidden (§5):
- 各脚本自行映射 (scripts must import normalize_verdict_for_evaluation)
- 字符串 contains 判断
- UNKNOWN 默认映射为 SUPPORTED
- OPINION_OR_FORECAST 随意映射为 SUPPORTED

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_3_verdict_mapping.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import (
    CANONICAL_VERDICTS,
    _EXTENDED_TO_CANONICAL,
    _INTERNAL_TO_CANONICAL,
    all_known_internal_statuses,
    normalize_verdict_for_evaluation,
)

OUT_PATH = BACKEND / "artifacts" / "aggregation" / "phase23_11_3_verdict_mapping.json"

# Adversarial inputs that MUST NOT map to SUPPORTED (or map to abstention)
ADVERSARIAL = [
    "", None, " ", "SUPPORTED", "supported", "  Refuted  ", "PARTIAL",
    "INSUFFICIENT", "UNABLE", "UNDETERMINED", "OPINION", "FORECAST",
    "CONFLICT", "CONFLICTING_EVIDENCE", "AMBIGUOUS", "AMBIGUOUS_EVIDENCE",
    "UNKNOWN", "NONE", "PENDING", "ERROR", "NO_EVIDENCE", "PARTIALLY",
    "GARBAGE_STATUS", "MIXED_OR_UNKNOWN",
]


def build_mapping_table() -> dict:
    """Full mapping table: input status → canonical external verdict."""
    table: dict[str, str] = {}
    for s in sorted(CANONICAL_VERDICTS):
        table[f"{s} (canonical)"] = normalize_verdict_for_evaluation(s)
    for k in sorted(_INTERNAL_TO_CANONICAL):
        table[f"{k} (internal/legacy)"] = normalize_verdict_for_evaluation(k)
    for k in sorted(_EXTENDED_TO_CANONICAL):
        table[f"{k} (extended)"] = normalize_verdict_for_evaluation(k)
    return table


def run_coverage() -> dict:
    """Coverage over all known statuses + adversarial inputs.

    Verifies the invariant: UNKNOWN-family / OPINION-family never map to
    SUPPORTED, and every known status maps to a CANONICAL_VERDICTS member.
    """
    statuses = all_known_internal_statuses()
    results = []
    violations = []
    for s in statuses:
        out = normalize_verdict_for_evaluation(s)
        results.append({"input": s, "output": out})
        if out not in CANONICAL_VERDICTS:
            violations.append({"input": s, "output": out, "why": "output not canonical"})
    for s in ADVERSARIAL:
        out = normalize_verdict_for_evaluation(s)
        results.append({"input": repr(s), "output": out})
        if s in ("OPINION", "FORECAST", "OPINION_OR_FORECAST"):
            if out == "SUPPORTED":
                violations.append({"input": repr(s), "output": out,
                                   "why": "OPINION_OR_FORECAST must NOT map to SUPPORTED"})
        if s in ("UNKNOWN", "NONE", "PENDING", "ERROR", "", None):
            if out == "SUPPORTED":
                violations.append({"input": repr(s), "output": out,
                                   "why": "UNKNOWN-family must NOT map to SUPPORTED"})
    return {"statuses_tested": len(statuses), "total_cases": len(results),
            "results": results, "violations": violations}


def main() -> int:
    table = build_mapping_table()
    coverage = run_coverage()

    forbidden_violations = coverage["violations"]
    output = {
        "phase": "23.11.3",
        "script": "phase23_11_3_verdict_mapping",
        "description": "§5 唯一 Verdict 映射函数 normalize_verdict_for_evaluation 的完整映射表与全状态覆盖测试",
        "canonical_verdicts": sorted(CANONICAL_VERDICTS),
        "mapping_table": table,
        "coverage_test": {
            "statuses_tested": coverage["statuses_tested"],
            "adversarial_cases": len(ADVERSARIAL),
            "total_cases": coverage["total_cases"],
            "violations": coverage["violations"],
            "pass": len(forbidden_violations) == 0,
        },
        "rules": {
            "single_function": "Oracle/Noisy Oracle/Real E2E/confusion matrix/API must all call normalize_verdict_for_evaluation",
            "forbidden": [
                "scripts implement their own mapping",
                "string contains judgement",
                "UNKNOWN default → SUPPORTED",
                "OPINION_OR_FORECAST → SUPPORTED",
            ],
        },
        "per_case": coverage["results"],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"verdict mapping written to {OUT_PATH}")
    print(f"  statuses tested: {coverage['statuses_tested']}, adversarial: {len(ADVERSARIAL)}")
    print(f"  violations: {len(forbidden_violations)}  ->  PASS={len(forbidden_violations) == 0}")
    for v in forbidden_violations:
        print("  VIOLATION:", v)
    return 0 if not forbidden_violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
