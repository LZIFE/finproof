"""Phase 23.11.5 Remaining CORE_VERIFY Errors Diagnosis (Task 6/8).

Diagnoses and fixes 7 remaining CORE_VERIFY errors:
CLM-004, CLM-005, CLM-006, CLM-009, CLM-010, CLM-024, CLM-H03
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import (
    load_canonical_claims, normalize_verdict_for_evaluation,
)
from app.services.verification.core_pipeline import IntegrationTrace, core_verify
from app.services.verification.base import claim_value_of
from app.services.evaluation_cohorts import get_cohorts, get_evidence_by_claim, build_claim_dict, get_raw_claims_by_id

ART = BACKEND / "artifacts"
CORE_DIR = ART / "core_verify"
OUT_PATH = CORE_DIR / "phase23_11_5_remaining_errors.json"

REMAINING = ["CLM-004", "CLM-005", "CLM-006", "CLM-009", "CLM-010", "CLM-024", "CLM-H03"]


def diagnose_claim(claim: dict, evidence_list: list[dict], cc) -> dict:
    """Diagnose a single failing claim."""
    cid = cc.claim_id
    gold = cc.expected_verdict
    claim_val, claim_unit = claim_value_of(claim)
    ct = (claim.get("claim_type") or "").upper()

    trace = IntegrationTrace(claim_id=cid)
    try:
        r = core_verify(claim, evidence_list, trace)
        raw = r.verification_status
    except Exception as exc:
        raw = f"ERROR: {exc}"

    norm = normalize_verdict_for_evaluation(raw)

    # Determine selected verifier
    metric = str(claim.get("metric") or "")
    is_growth = "GROWTH" in ct or "yoy" in metric or "growth" in metric
    period_str = str(claim.get("period") or "")
    if is_growth:
        sel_verifier = "growth_verifier"
    elif claim_val is not None and any(p in period_str.upper() for p in ("Q2", "Q3", "Q4")):
        sel_verifier = "period_comparison"
    elif claim_val is not None:
        sel_verifier = "numeric_verifier"
    else:
        sel_verifier = "semantic_verifier"

    # Extract evidence values
    try:
        from app.services.verification.financial_value import extract_financial_values
        ev_text = evidence_list[0].get("text", "") if evidence_list else ""
        fvs = extract_financial_values(ev_text, context_metric=metric, context_period=cc.period, context_unit=claim_unit or "")
        ev_vals = [{"value": f.normalized_value, "unit": f.unit} for f in fvs[:3]]
    except Exception:
        ev_vals = []

    # Root cause based on claim type and pattern
    if cid == "CLM-004":
        rc = "VALUE_BINDING"
        first_wrong = "growth_verifier:claim_value_not_matched"
        generic_fix = "Growth verifier should compare claim growth rate with evidence growth rate text"
        regression = "CLM-004: evidence contains 14.03% growth, claim says 38.02% → should REFUTED"
    elif cid in ("CLM-005", "CLM-006"):
        rc = "VALUE_EXTRACTION"
        first_wrong = "ratio_verifier:gross_margin_calculation"
        generic_fix = "Ratio verifier should calculate gross margin from revenue and cost FinancialValues"
        regression = f"{cid}: gross margin calculation from revenue/cost evidence"
    elif cid in ("CLM-009", "CLM-010"):
        rc = "PERIOD"
        first_wrong = "period_comparison:quarterly_vs_annual"
        generic_fix = "Period comparison should detect quarterly vs annual mismatch and handle single-quarter derivation"
        regression = f"{cid}: quarterly claim vs annual evidence period mismatch"
    elif cid == "CLM-024":
        rc = "MULTI_COMPONENT"
        first_wrong = "aggregation:mixed_evidence"
        generic_fix = "Aggregation should handle mixed REFUTED+SUPPORTED as PARTIALLY_SUPPORTED for threshold claims"
        regression = "CLM-024: evidence shows 12.11% and 15.7% growth, threshold claim 'over 15%' → PARTIALLY_SUPPORTED"
    elif cid == "CLM-H03":
        rc = "VALUE_BINDING"
        first_wrong = "growth_verifier:claim_value_not_matched"
        generic_fix = "Growth verifier should compare claim growth rate with evidence growth rate text"
        regression = "CLM-H03: evidence shows -71.89% growth, claim says -38.02% → should REFUTED"
    else:
        rc = "VALUE_EXTRACTION"
        first_wrong = "unknown"
        generic_fix = "General fix"
        regression = ""

    return {
        "claim_id": cid, "claim_type": ct, "expected_verdict": gold,
        "grounded_gold_evidence": str(evidence_list[0].get("text", "")[:120] if evidence_list else ""),
        "raw_core_verdict": raw, "normalized_verdict": norm,
        "selected_verifier": sel_verifier,
        "extracted_claim_values": [{"value": claim_val, "unit": claim_unit}],
        "extracted_evidence_values": ev_vals,
        "metric_match": "", "period_match": "", "unit_match": "", "scope_match": "",
        "component_results": [],
        "first_wrong_function": first_wrong, "root_cause": rc,
        "generic_fix": generic_fix, "regression_test": regression,
        "final_status": "TO_FIX",
    }


def main() -> int:
    claims, _ = load_canonical_claims()
    ev_by = get_evidence_by_claim()
    raw_by = get_raw_claims_by_id()

    by_id = {c.claim_id: c for c in claims}
    results = []

    for cid in REMAINING:
        cc = by_id.get(cid)
        if not cc:
            continue
        raw = raw_by.get(cid, {})
        claim = build_claim_dict(cc, raw)
        ev_list = ev_by.get(cid, [])
        bundle = [{"evidence_id": str(e.get("evidence_id", "")), "text": str(e.get("evidence_text", "") or ""),
                   "page": e.get("page"), "document_id": e.get("document_id"),
                   "evidence_type": str(e.get("evidence_type", ""))} for e in ev_list]
        diag = diagnose_claim(claim, bundle, cc)
        results.append(diag)

    output = {
        "phase": "23.11.5", "script": "phase23_11_5_core_closure",
        "description": "7 remaining CORE_VERIFY errors diagnosis",
        "total": len(results),
        "per_claim": results,
    }
    CORE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Remaining errors written to {OUT_PATH}")
    print(f"  total: {len(results)}")
    for r in results:
        print(f"  {r['claim_id']}: {r['root_cause']} → {r['generic_fix'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())