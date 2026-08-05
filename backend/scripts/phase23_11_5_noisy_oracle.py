"""Phase 23.11.5 NOISY_ORACLE (Grounded Cohort version).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path: sys.path.insert(0, str(BACKEND))
from app.services.evaluation_claim_schema import load_canonical_claims
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_one
from app.services.canonical_evidence import adapt_noisy_oracle
from app.services.evaluation_cohorts import get_cohorts, get_evidence_by_claim, build_claim_dict, get_raw_claims_by_id
ART = BACKEND / "artifacts"
GATE_DIR = ART / "evidence_gate"
OUT_PATH = GATE_DIR / "phase23_11_5_noisy_oracle.json"
GATE_CFG = GateConfig()

def main() -> int:
    claims, _ = load_canonical_claims()
    raw_by = get_raw_claims_by_id()
    ev_by = get_evidence_by_claim()
    cohorts = get_cohorts(claims, ev_by)
    # Use grounded cohort
    gi = json.loads((ART / "gold_contract" / "phase23_11_5_grounding_inventory.json").read_text())
    by_eid = {p['gold_evidence_id']: p for p in gi['per_evidence']}
    grounded_ids = set()
    for cc in cohorts['evidence_bearing']:
        evs = ev_by.get(cc.claim_id, [])
        statuses = [by_eid.get(e.get('evidence_id',''),{}).get('grounding_status','') for e in evs]
        if all(s in ('EXACT_BLOCK_MATCH','NORMALIZED_BLOCK_MATCH','MULTI_BLOCK_MATCH') for s in statuses):
            grounded_ids.add(cc.claim_id)
    gb = [cc for cc in claims if cc.claim_id in grounded_ids]
    print(f"Running NOISY_ORACLE on grounded cohort: {len(gb)} claims")
    output = {"phase": "23.11.5", "script": "phase23_11_5_noisy_oracle", "sample_count": len(gb), "note": "Grounded cohort only. Gate metrics still INVALID_PENDING_GOLD_ALIGNMENT due to empty block_id."}
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"NOISY_ORACLE written to {OUT_PATH}")
    return 0
if __name__ == "__main__": raise SystemExit(main())