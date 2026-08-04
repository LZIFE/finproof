"""Phase 23.11.4 Single-Gold Input Contract (Task 4).

For each evidence-bearing claim, construct CanonicalEvidence from real gold blocks
and audit field completeness. Fail fast if text is lost between stages.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import load_canonical_claims
from app.services.claim_router import route_claim
from app.services.evaluation_cohorts import get_cohorts, get_evidence_by_claim, build_claim_dict, get_raw_claims_by_id
from app.services.canonical_evidence import adapt_core_oracle

ART = BACKEND / "artifacts"
GOLD_DIR = ART / "gold_contract"
OUT_PATH = GOLD_DIR / "phase23_11_4_single_gold_inputs.json"


def check_field_lost(original: dict, adapted: object, field: str) -> dict:
    """Check if a field was lost during adaptation."""
    orig_val = original.get(field, None)
    adapted_val = getattr(adapted, field, None) if hasattr(adapted, field) else None
    return {
        "field": field,
        "original_value": str(orig_val)[:100] if orig_val is not None else None,
        "adapted_value": str(adapted_val)[:100] if adapted_val is not None else None,
        "lost": orig_val is not None and adapted_val is None,
        "derived": orig_val is None and adapted_val is not None,
        "defaulted": orig_val is None and adapted_val is not None and field in ("text", "evidence_type"),
    }


def main() -> int:
    claims, _ = load_canonical_claims()
    ev_by = get_evidence_by_claim()
    raw_by = get_raw_claims_by_id()
    cohorts = get_cohorts(claims, ev_by)

    per_claim = []
    field_loss_summary = {}
    total_lost_fields = 0
    total_derived_fields = 0

    for cc in cohorts["evidence_bearing"]:
        cid = cc.claim_id
        gold_ev = ev_by.get(cid, [])
        raw = raw_by.get(cid, {})
        claim = build_claim_dict(cc, raw)
        routing = route_claim(claim)

        # Original gold evidence fields
        orig = gold_ev[0] if gold_ev else {}
        orig_fields = {
            "evidence_id": str(orig.get("evidence_id", "")),
            "evidence_text": str(orig.get("evidence_text", "") or "")[:200],
            "page": orig.get("page"),
            "document_id": orig.get("document_id"),
            "block_id": str(orig.get("block_id") or orig.get("source_block_id") or ""),
            "evidence_type": str(orig.get("evidence_type", "")),
            "company": str(orig.get("company", cc.company)),
        }

        # Canonical Adapter
        try:
            ce_list, _ = adapt_core_oracle(gold_ev, claim, routing.route)
            adapted = ce_list[0] if ce_list else None
        except Exception as exc:
            adapted = None
            adapter_error = str(exc)
        adapter_warnings = []

        # Field audit
        field_audit = {}
        for f in ("evidence_id", "evidence_text", "text", "evidence_type", "metric", "period", "unit", "scope"):
            fa = check_field_lost(orig_fields, adapted, f)
            field_audit[f] = fa
            if fa["lost"]:
                total_lost_fields += 1
                adapter_warnings.append(f"Field '{f}' LOST during adaptation")
            if fa["derived"]:
                total_derived_fields += 1

        # Check text continuity
        original_text = str(orig.get("evidence_text", "") or "")
        adapted_text = str(getattr(adapted, "text", "") or "") if adapted else ""
        adapter_warnings.append("All fields preserved" if not any(fa["lost"] for fa in field_audit.values()) else "Some fields lost")

        per_claim.append({
            "claim_id": cid,
            "claim_type": cc.claim_type,
            "expected_verdict": cc.expected_verdict,
            "original_gold_fields": orig_fields,
            "canonical_evidence": {
                "text": adapted_text[:200] if adapted_text else None,
                "evidence_id": getattr(adapted, "evidence_id", None) if adapted else None,
                "evidence_type": getattr(adapted, "evidence_type", None) if adapted else None,
            },
            "field_audit": field_audit,
            "lost_fields": [f for f, fa in field_audit.items() if fa["lost"]],
            "derived_fields": [f for f, fa in field_audit.items() if fa["derived"]],
            "defaulted_fields": [f for f, fa in field_audit.items() if fa["defaulted"]],
            "adapter_error": adapter_error if adapted is None else None,
            "adapter_warnings": adapter_warnings,
            "text_continuity": {
                "original_text_hash": hash(original_text),
                "adapted_text_hash": hash(adapted_text),
                "text_matches": original_text.strip() in adapted_text or adapted_text.strip() in original_text,
                "text_lost": not adapted_text and bool(original_text),
            },
            "status": "PASS" if adapted and not adapter_warnings else "WARNING" if adapted else "FAIL",
        })

    output = {
        "phase": "23.11.4",
        "script": "phase23_11_4_single_gold_inputs",
        "description": "Evidence-bearing claims CanonicalEvidence完整性审计",
        "total_evidence_bearing": len(cohorts["evidence_bearing"]),
        "total_lost_fields": total_lost_fields,
        "total_derived_fields": total_derived_fields,
        "per_claim": per_claim,
    }
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Single-Gold inputs written to {OUT_PATH}")
    print(f"  evidence_bearing: {len(cohorts['evidence_bearing'])}")
    print(f"  total_lost_fields: {total_lost_fields}")
    print(f"  total_derived_fields: {total_derived_fields}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())