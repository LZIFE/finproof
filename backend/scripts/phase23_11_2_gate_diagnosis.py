"""Phase 23.11.2 Gold Rejection Diagnosis (Task 2).

Per-claim diagnose why each of the 37 Gold Evidence candidates was rejected
by the Phase 23.11 Evidence Gate, with root_cause taxonomy (§2):

- CANONICAL_SCHEMA_MISMATCH
- FEATURE_MISSING_TREATED_AS_FALSE
- ENTITY_FALSE_NEGATIVE
- METRIC_FALSE_NEGATIVE
- PERIOD_FALSE_NEGATIVE
- UNIT_FALSE_NEGATIVE
- SCOPE_FALSE_NEGATIVE
- ROUTE_MISCLASSIFICATION
- THRESHOLD_TOO_HIGH
- SELECTOR_INPUT_BUG
- GOLD_EVIDENCE_INCOMPLETE
- TRUE_CONTRADICTION

Counts per root_cause class. No笼统"threshold too strict".

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_2_gate_diagnosis.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import SessionLocal
from app.services.evaluation_claim_schema import load_canonical_claims
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_one
from app.services.canonical_evidence import adapt_core_oracle

ART = BACKEND / "artifacts"
EVIDENCE_DIR = ART / "evidence_gate"
OUT_PATH = EVIDENCE_DIR / "phase23_11_2_gold_rejection_diagnosis.json"

# Root cause taxonomy (§2)
ROOT_CAUSES = (
    "CANONICAL_SCHEMA_MISMATCH",
    "FEATURE_MISSING_TREATED_AS_FALSE",
    "ENTITY_FALSE_NEGATIVE",
    "METRIC_FALSE_NEGATIVE",
    "PERIOD_FALSE_NEGATIVE",
    "UNIT_FALSE_NEGATIVE",
    "SCOPE_FALSE_NEGATIVE",
    "ROUTE_MISCLASSIFICATION",
    "THRESHOLD_TOO_HIGH",
    "SELECTOR_INPUT_BUG",
    "GOLD_EVIDENCE_INCOMPLETE",
    "TRUE_CONTRADICTION",
)


def load_gold_evidence_by_claim() -> dict[str, list[dict]]:
    """{claim_id: [evidence_dict,...]} from gold_evidence.json (demo+holdout)."""
    out: dict[str, list[dict]] = {}
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_evidence.json"
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for e in data.get("evidence", []):
            cid = str(e.get("claim_id") or "")
            if cid:
                out.setdefault(cid, []).append(e)
    return out


def _is_missing_treated_as_false(claim: dict, candidate: dict, reason: str) -> bool:
    """Did Gate reject because a missing field was treated as 0.0/False?

    Phase 23.11 Gate: _metric_match returns 0.0 when no alias hit; _period_match
    returns 0.0 when period not in text; etc. Missing → 0.0 → below threshold.
    """
    return (
        "metric match" in reason and "below threshold" in reason
    ) or (
        "quality score" in reason and "below medium threshold" in reason
    )


def _classify_root_cause(
    claim: dict, candidate: dict, ce, routing, reason: str, scores: dict,
) -> str:
    """Classify single root_cause from rejection reason + score breakdown."""
    # TRUE_CONTRADICTION: explicit相反事实 (period_score=0 AND scope_score=0)
    if "period conflict" in reason or "scope conflict" in reason:
        # Check if it's真正冲突 vs只是没找到
        claim_period = str(claim.get("period") or "")
        ev_text = candidate.get("evidence_text") or candidate.get("text") or ""
        claim_scope = str(claim.get("scope") or "consolidated")
        # If evidence clearly mentions a DIFFERENT period/scope → TRUE_CONTRADICTION
        # else → FALSE_NEGATIVE (gate didn't find it)
        if "period conflict" in reason:
            # Heuristic: if evidence text has the claim period substring but gate
            # scored 0 → FALSE_NEGATIVE; if has different year → TRUE_CONTRADICTION
            if claim_period and claim_period[:4] in ev_text:
                return "PERIOD_FALSE_NEGATIVE"
            return "TRUE_CONTRADICTION"
        if "scope conflict" in reason:
            return "SCOPE_FALSE_NEGATIVE" if scores.get("scope", 0) > 0 else "TRUE_CONTRADICTION"

    # ENTITY mismatch: candidate text doesn't mention claim entity.
    # Gold evidence is financial-table numeric (e.g. "营业收入 456,451,731")
    # which does NOT restate company name — this is normal table evidence
    # form, NOT a real mismatch. Missing entity → UNKNOWN (soft), not Hard Reject.
    if "entity mismatch" in reason:
        ev_text = candidate.get("evidence_text") or candidate.get("text") or ""
        entity = str(claim.get("entity") or "")
        if entity and entity in ev_text:
            return "ENTITY_FALSE_NEGATIVE"
        # Table evidence legitimately omits entity → missing treated as False
        return "FEATURE_MISSING_TREATED_AS_FALSE"

    # CAUSALITY route without causal language
    if "CAUSALITY" in reason:
        return "FEATURE_MISSING_TREATED_AS_FALSE"

    # Metric below threshold
    if "metric match" in reason:
        metric_score = scores.get("metric", 0.0)
        # If metric IS in text but scored 0 → FALSE_NEGATIVE
        ev_text = candidate.get("evidence_text") or candidate.get("text") or ""
        claim_metric = str(claim.get("metric") or "")
        if claim_metric and claim_metric in ev_text:
            return "METRIC_FALSE_NEGATIVE"
        # If gold evidence genuinely doesn't mention metric → INCOMPLETE
        return "GOLD_EVIDENCE_INCOMPLETE"

    # Quality below medium threshold (completeness collapse)
    if "quality score" in reason:
        # Which component drove completeness to 0?
        # If period_score=0 and evidence has no period → INCOMPLETE
        ev_text = candidate.get("evidence_text") or candidate.get("text") or ""
        claim_period = str(claim.get("period") or "")
        if claim_period and claim_period[:4] not in ev_text:
            # Evidence genuinely lacks period
            if scores.get("period", 0.0) == 0.0:
                return "GOLD_EVIDENCE_INCOMPLETE"
            return "PERIOD_FALSE_NEGATIVE"
        # If evidence has period but scored 0 → FALSE_NEGATIVE
        if claim_period and claim_period[:4] in ev_text and scores.get("period", 0.0) == 0.0:
            return "PERIOD_FALSE_NEGATIVE"
        # Generic threshold issue
        return "THRESHOLD_TOO_HIGH"

    # Selector input bug (gate accepted but selector empty)
    if "selector" in reason.lower():
        return "SELECTOR_INPUT_BUG"

    return "THRESHOLD_TOO_HIGH"


def diagnose() -> int:
    claims, _ = load_canonical_claims()
    gold_ev_by = load_gold_evidence_by_claim()
    raw_claims_by: dict[str, dict] = {}
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_claims.json"
        if not p.exists():
            continue
        for c in json.loads(p.read_text(encoding="utf-8")).get("claims", []):
            cid = str(c.get("claim_id") or "")
            if cid:
                raw_claims_by[cid] = c

    gate_cfg = GateConfig()  # Phase 23.11 default thresholds
    rows: list[dict] = []
    root_counter: Counter = Counter()

    for cc in claims:
        cid = cc.claim_id
        gold_ev = gold_ev_by.get(cid, [])
        if not gold_ev:
            continue  # no gold evidence to reject; skip
        raw = raw_claims_by.get(cid, {})
        claim = dict(raw)
        claim.setdefault("entity", cc.company)
        claim.setdefault("original_text", cc.claim_text)
        routing = route_claim(claim)
        # Adapt gold to CanonicalEvidence (for schema comparison tracking)
        ce_list, _ = adapt_core_oracle(gold_ev, claim, routing.route)
        for ev, ce in zip(gold_ev, ce_list):
            result = evaluate_one(claim, ev, routing, gate_cfg)
            if result.accepted:
                continue  # only diagnose rejected gold
            scores = {
                "metric": result.metric_match, "period": result.period_match,
                "scope": result.scope_match, "unit": result.unit_match,
                "numeric": result.numeric_match, "route": result.route_match,
            }
            rc = _classify_root_cause(
                claim, ev, ce, routing, result.rejection_reason, scores,
            )
            root_counter[rc] += 1
            rows.append({
                "claim_id": cid,
                "claim_text": cc.claim_text,
                "route": routing.route,
                "gold_evidence_id": str(ev.get("evidence_id") or "?"),
                "gold_evidence_text": str(ev.get("evidence_text") or ev.get("text") or "")[:200],
                "company": cc.company,
                "metric": cc.metric,
                "period": cc.period,
                "unit": cc.unit,
                "scope": cc.scope,
                "entity_match": result.entity_match,
                "metric_match": round(result.metric_match, 3),
                "period_match": round(result.period_match, 3),
                "unit_match": round(result.unit_match, 3),
                "scope_match": round(result.scope_match, 3),
                "route_match": round(result.route_match, 3),
                "completeness_score": round(result.completeness_score, 3),
                "gate_threshold": {
                    "metric_match_threshold": gate_cfg.metric_match_threshold,
                    "high_quality_threshold": gate_cfg.high_quality_threshold,
                    "medium_quality_threshold": gate_cfg.medium_quality_threshold,
                },
                "final_quality_score": round(result.final_quality_score, 3),
                "rejection_reason": result.rejection_reason,
                "root_cause": rc,
                "expected_fix": _expected_fix(rc),
            })

    output = {
        "phase": "23.11.2",
        "script": "phase23_11_2_gate_diagnosis",
        "description": "Per-claim diagnosis of 37 GATE_REJECTED_GOLD (Phase 23.11 Gate)",
        "total_rejected_gold": len(rows),
        "root_cause_counts": dict(root_counter),
        "root_cause_taxonomy": list(ROOT_CAUSES),
        "diagnosis": rows,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gold rejection diagnosis written to {OUT_PATH}")
    print(f"  total rejected gold: {len(rows)}")
    print(f"  root_cause counts:")
    for rc, n in sorted(root_counter.items(), key=lambda x: -x[1]):
        print(f"    {n:>3}  {rc}")
    return 0


def _expected_fix(rc: str) -> str:
    fixes = {
        "CANONICAL_SCHEMA_MISMATCH": "Adapt gold evidence to CanonicalEvidence; populate company/entity from claim",
        "FEATURE_MISSING_TREATED_AS_FALSE": "Three-state logic: missing → UNKNOWN (soft penalty), not MISMATCH",
        "ENTITY_FALSE_NEGATIVE": "Improve entity matching: substring + alias; Gold evidence DOES mention entity",
        "METRIC_FALSE_NEGATIVE": "Improve metric matching: metric_aliases + canonical; evidence DOES mention metric",
        "PERIOD_FALSE_NEGATIVE": "Period parse: extract year from evidence text; evidence DOES mention period",
        "UNIT_FALSE_NEGATIVE": "Unit conversion: 亿元/万元/千元/元 interchangeable",
        "SCOPE_FALSE_NEGATIVE": "Scope parse: 归母/合并/扣非 keyword matching",
        "ROUTE_MISCLASSIFICATION": "Re-route claim via ClaimRouter priority",
        "THRESHOLD_TOO_HIGH": "Calibrate threshold via leave-one-company-out Pareto",
        "SELECTOR_INPUT_BUG": "Fix Selector: never return empty when accepted_count > 0",
        "GOLD_EVIDENCE_INCOMPLETE": "Gold evidence genuinely lacks field; use UNKNOWN soft penalty",
        "TRUE_CONTRADICTION": "Real conflict; keep Hard Reject",
    }
    return fixes.get(rc, "review")


if __name__ == "__main__":
    raise SystemExit(diagnose())
