"""Phase 23.11.4 Evaluation Cohorts — 三个独立评测队列.

Usage:
    from app.services.evaluation_cohorts import get_cohorts, load_claim_data
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent
CANONICAL_SCRIPT = BACKEND / "scripts" / "phase23_11_4_gold_inventory.py"
INVENTORY_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_4_gold_inventory.json"


def get_cohorts(claims: list, ev_by: dict[str, list]) -> dict:
    """Classify all 43 claims into three cohorts.
    
    Returns dict with:
        evidence_bearing: list of CanonicalClaim with VALID gold evidence
        intentional_insufficient: list of CanonicalClaim with INTENTIONAL_NO_EVIDENCE
        annotation_blocked: list of CanonicalClaim with MISSING_GOLD_ANNOTATION
        oracle_evaluable: evidence_bearing (valid oracle test subjects)
    """
    evidence_bearing = []
    intentional_insufficient = []
    annotation_blocked = []

    for cc in claims:
        cid = cc.claim_id
        ev_list = ev_by.get(cid, [])
        expected = cc.expected_verdict

        if not ev_list:
            if expected == "INSUFFICIENT_EVIDENCE":
                intentional_insufficient.append(cc)
            else:
                annotation_blocked.append(cc)
        else:
            evidence_bearing.append(cc)

    return {
        "evidence_bearing": evidence_bearing,
        "intentional_insufficient": intentional_insufficient,
        "annotation_blocked": annotation_blocked,
        "oracle_evaluable": evidence_bearing,
        "counts": {
            "total": len(claims),
            "evidence_bearing": len(evidence_bearing),
            "intentional_insufficient": len(intentional_insufficient),
            "annotation_blocked": len(annotation_blocked),
            "oracle_evaluable": len(evidence_bearing),
            "sum_check": len(evidence_bearing) + len(intentional_insufficient) + len(annotation_blocked),
        },
    }


def get_evidence_by_claim() -> dict[str, list[dict]]:
    """Load gold_evidence.json from demo+holdout."""
    import json
    ev_by: dict[str, list[dict]] = {}
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_evidence.json"
        if not p.exists():
            continue
        for e in json.loads(p.read_text(encoding="utf-8")).get("evidence", []):
            cid = str(e.get("claim_id") or "")
            if cid:
                ev_by.setdefault(cid, []).append(e)
    return ev_by


def get_raw_claims_by_id() -> dict[str, dict]:
    """Load gold_claims.json from demo+holdout."""
    import json
    out: dict[str, dict] = {}
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_claims.json"
        if not p.exists():
            continue
        for c in json.loads(p.read_text(encoding="utf-8")).get("claims", []):
            cid = str(c.get("claim_id") or "")
            if cid:
                c.setdefault("_dataset", ds)
                out[cid] = c
    return out


def build_claim_dict(cc, raw: dict) -> dict:
    """Build a dict for core_verify from CanonicalClaim + raw claim."""
    base = dict(raw)
    base.setdefault("claim_id", cc.claim_id)
    base.setdefault("entity", cc.company)
    base.setdefault("original_text", cc.claim_text)
    base.setdefault("period", cc.period)
    base.setdefault("scope", cc.scope)
    base.setdefault("unit", cc.unit)
    base.setdefault("metric", cc.metric)
    if "value" not in base or base.get("value") is None:
        base["value"] = cc.value
    return base