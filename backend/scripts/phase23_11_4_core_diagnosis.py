"""Phase 23.11.4 Core Verify Error Diagnosis (Task 5).

逐条诊断17个CORE_VERIFY错误，输出每条的root_cause、first_wrong_function、proposed_generic_fix。
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
from app.services.claim_router import route_claim
from app.services.evaluation_cohorts import get_cohorts, get_evidence_by_claim, build_claim_dict, get_raw_claims_by_id
from app.services.verification.core_pipeline import IntegrationTrace, core_verify
from app.services.verification.base import claim_value_of

ART = BACKEND / "artifacts"
CORE_DIR = ART / "core_verify"
OUT_PATH = CORE_DIR / "phase23_11_4_error_diagnosis.json"

# The 17 CORE_VERIFY first-divergence claims from Phase 23.11.3
CORE_VERIFY_CLAIMS = [
    "CLM-001", "CLM-003", "CLM-004", "CLM-005", "CLM-006",
    "CLM-007", "CLM-008", "CLM-010", "CLM-011", "CLM-012",
    "CLM-014", "CLM-015", "CLM-016", "CLM-019", "CLM-024",
    "CLM-H12", "CLM-H16",
]


def diagnose_root_cause(claim: dict, evidence_list: list[dict], trace: IntegrationTrace,
                         raw_verdict: str, norm_verdict: str, gold: str) -> dict:
    """Diagnose the root cause of a core_verify error."""
    ct = (claim.get("claim_type") or "").upper()
    metric = str(claim.get("metric") or "")
    period = str(claim.get("period") or "")
    ev_text = str(evidence_list[0].get("text", "") if evidence_list else "")
    claim_val, claim_unit = claim_value_of(claim)

    # Determine selected verifier
    non_numeric = {"BUSINESS_FACT", "CAUSALITY", "CAUSAL_CLAIM", "COMPARISON",
                   "COMPARATIVE_CLAIM", "OPINION", "TREND", "STRATEGIC_CLAIM", "SCOPE"}
    is_growth = "GROWTH" in ct or "yoy" in metric or "growth" in metric or "qoq" in metric
    is_forecast = ct == "FORECAST" or "forecast" in metric or "预计" in claim.get("original_text", "")
    if claim_val is None and ct in non_numeric:
        sel_verifier = "semantic_verifier"
    elif is_forecast:
        sel_verifier = "forecast_mapping"
    elif is_growth:
        sel_verifier = "growth_verifier"
    elif claim_val is not None:
        sel_verifier = "numeric_verifier"
    else:
        sel_verifier = "semantic_verifier"

    # Extract evidence values
    try:
        from app.services.verification.financial_value import extract_financial_values
        fvs = extract_financial_values(ev_text, context_metric=metric, context_period=period, context_unit=claim_unit or "")
        ev_values = [{"value": f.normalized_value, "unit": f.unit, "period": f.period} for f in fvs[:3]]
    except Exception:
        ev_values = []

    # Root cause classification
    if not ev_text:
        rc = "EVIDENCE_CONTRACT_ERROR"
        first_wrong = "evidence_contract"
        fix = "Ensure evidence text is non-empty in the bundle passed to core_verify"
    elif raw_verdict == "INSUFFICIENT_EVIDENCE" and not ev_values:
        rc = "EVIDENCE_VALUE_EXTRACTION_ERROR"
        first_wrong = "financial_value_extraction"
        fix = "Fix FinancialValue to parse unit in parentheses (e.g., '（千元）') and normalize to claim unit"
    elif raw_verdict == "INSUFFICIENT_EVIDENCE" and ev_values:
        # Values extracted but didn't match
        rc = "MULTIPLE_NUMBER_BINDING_ERROR"
        first_wrong = "find_best_match"
        fix = "Improve find_best_match to handle multi-column financial tables with unit conversion"
    elif raw_verdict in ("UNABLE", "UNABLE_TO_DETERMINE", "OPINION_OR_FORECAST"):
        rc = "FORECAST_MAPPING_ERROR"
        first_wrong = "forecast_mapping"
        fix = "Distinguish between forecast/opinion claims and factual claims with forecast-like language"
    elif raw_verdict == "PARTIALLY_SUPPORTED" and gold == "SUPPORTED":
        rc = "PARTIAL_COMPONENT_ERROR"
        first_wrong = "semantic_completeness"
        fix = "Ensure semantic_completeness threshold is appropriate for full-support claims"
    elif raw_verdict == "REFUTED" and gold == "SUPPORTED":
        rc = "VERDICT_NORMALIZATION_ERROR"
        first_wrong = "verdict_decision"
        fix = "Check numeric comparison tolerance and unit conversion"
    else:
        # Fallback
        rc = "CLAIM_TYPE_ROUTE_WRONG"
        first_wrong = "claim_router"
        fix = "Verify claim_type routing produces correct verifier dispatch"

    return {
        "selected_verifier": sel_verifier,
        "extracted_claim_values": [{"value": claim_val, "unit": claim_unit}],
        "extracted_evidence_values": ev_values,
        "claim_metric": metric,
        "evidence_metric": "",  # Not extracted from evidence text
        "claim_period": period,
        "evidence_period": "",
        "claim_unit": str(claim_unit or ""),
        "evidence_unit": str(ev_values[0]["unit"]) if ev_values else "",
        "claim_scope": str(claim.get("scope", "")),
        "evidence_scope": "",
        "raw_core_verdict": raw_verdict,
        "normalized_verdict": norm_verdict,
        "rule_id": trace.rule_id if hasattr(trace, "rule_id") else "",
        "confidence": 0.0,  # Not available from trace after run
        "first_wrong_function": first_wrong,
        "root_cause": rc,
        "proposed_generic_fix": fix,
        "regression_test": f"Single-gold verify for {claim.get('claim_id','?')} returns correct verdict",
        "status": "TO_FIX",
    }


def main() -> int:
    claims, _ = load_canonical_claims()
    ev_by = get_evidence_by_claim()
    raw_by = get_raw_claims_by_id()
    cohorts = get_cohorts(claims, ev_by)

    by_id = {c.claim_id: c for c in claims}
    error_claims = [c for c in claims if c.claim_id in CORE_VERIFY_CLAIMS]

    rows = []
    errors = []
    fixable = 0
    non_fixable = 0

    for cc in error_claims:
        cid = cc.claim_id
        gold_ev = ev_by.get(cid, [])
        raw = raw_by.get(cid, {})
        claim = build_claim_dict(cc, raw)
        gold = cc.expected_verdict

        if not gold_ev:
            rows.append({
                "claim_id": cid, "claim_type": cc.claim_type,
                "expected_verdict": gold,
                "gold_evidence": "NO_EVIDENCE",
                "status": "NO_GOLD_DATA",
                "root_cause": "EVIDENCE_CONTRACT_ERROR",
                "first_wrong_function": "gold_contract",
                "proposed_generic_fix": "Add gold annotation or move to intentional_insufficient cohort",
            })
            non_fixable += 1
            continue

        e = gold_ev[0]
        bundle = [{
            "evidence_id": str(e.get("evidence_id", "")),
            "text": str(e.get("evidence_text", "") or ""),
            "page": e.get("page"),
            "document_id": e.get("document_id"),
            "evidence_type": str(e.get("evidence_type", "")),
        }]
        trace = IntegrationTrace(claim_id=cid)
        try:
            r = core_verify(claim, bundle, trace)
            raw_verdict = r.verification_status
        except Exception as exc:
            raw_verdict = f"ERROR: {exc}"

        norm_verdict = normalize_verdict_for_evaluation(raw_verdict)
        is_correct = norm_verdict == gold
        diag = diagnose_root_cause(claim, bundle, trace, raw_verdict, norm_verdict, gold)
        diag["claim_id"] = cid
        diag["claim_type"] = cc.claim_type
        diag["expected_verdict"] = gold
        diag["gold_evidence"] = str(e.get("evidence_text", ""))[:120]
        diag["canonical_evidence"] = bundle[0]["text"][:120]
        diag["correct"] = is_correct
        rows.append(diag)
        if is_correct:
            errors.append({"claim_id": cid, "note": "already correct"})
            fixable += 1
        else:
            errors.append({"claim_id": cid, "root_cause": diag["root_cause"]})
            fixable += 1

    output = {
        "phase": "23.11.4",
        "script": "phase23_11_4_core_diagnosis",
        "description": "17条CORE_VERIFY错误逐条根因诊断",
        "total_examined": len(rows),
        "fixable": fixable,
        "non_fixable": non_fixable,
        "root_cause_counts": {},
        "per_claim": rows,
    }
    CORE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Core diagnosis written to {OUT_PATH}")
    print(f"  total_examined: {len(rows)}")
    print(f"  fixable: {fixable}, non_fixable: {non_fixable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())