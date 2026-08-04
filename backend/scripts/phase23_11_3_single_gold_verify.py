"""Phase 23.11.3 Single-Gold core_verify Validation (Task 6).

Isolate Selector and Aggregation: feed each of 43 CORE_ORACLE claims exactly
ONE Gold Evidence directly to core_verify → normalize_verdict_for_evaluation.

Purpose (§6): confirm core_verify itself is correct when isolated.
- If Single-Gold still 0.2093 → root cause in core_verify or Verdict mapping,
  NOT Aggregation.
- If Single-Gold recovers high accuracy → root cause in Selector/Aggregation.

Output: backend/artifacts/aggregation/phase23_11_3_single_gold_verify.json
  per-claim: claim_id, expected_verdict, core_verify_raw_verdict,
             normalized_verdict, correct, rule_id, trace
  metrics: Single-Gold Accuracy, Macro-F1, per-class F1

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_3_single_gold_verify.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import (
    load_canonical_claims, normalize_verdict_for_evaluation,
)
from app.services.verification.core_pipeline import IntegrationTrace, core_verify

ART = BACKEND / "artifacts"
AGG_DIR = ART / "aggregation"
OUT_PATH = AGG_DIR / "phase23_11_3_single_gold_verify.json"


def load_gold_evidence_by_claim() -> dict[str, list[dict]]:
    """{claim_id: [evidence_dict,...]} from gold_evidence.json (demo+holdout)."""
    out: dict[str, list[dict]] = {}
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_evidence.json"
        if not p.exists():
            continue
        for e in json.loads(p.read_text(encoding="utf-8")).get("evidence", []):
            cid = str(e.get("claim_id") or "")
            if cid:
                out.setdefault(cid, []).append(e)
    return out


def load_raw_claims_by_id() -> dict[str, dict]:
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


def _build_claim_dict(cc, raw):
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


def _build_evidence_bundle(e: dict) -> list[dict]:
    """Build single-evidence bundle in the format core_verify expects."""
    return [{
        "evidence_id": str(e.get("evidence_id") or "?"),
        "text": str(e.get("evidence_text") or e.get("text") or ""),
        "page": e.get("page"),
        "document_id": e.get("document_id"),
        "evidence_type": e.get("evidence_type", ""),
    }]


def main() -> int:
    claims, _ = load_canonical_claims()
    gold_ev_by = load_gold_evidence_by_claim()
    raw_by = load_raw_claims_by_id()

    rows = []
    correct = 0
    confusion: dict = defaultdict(int)
    pred_c: Counter = Counter()
    gold_c: Counter = Counter()
    missing = 0
    raw_verdict_c: Counter = Counter()

    for cc in claims:
        cid = cc.claim_id
        gold_ev = gold_ev_by.get(cid, [])
        raw = raw_by.get(cid, {})
        claim = _build_claim_dict(cc, raw)
        if not gold_ev:
            missing += 1
            rows.append({
                "claim_id": cid, "expected_verdict": cc.expected_verdict,
                "core_verify_raw_verdict": "NO_GOLD_EVIDENCE",
                "normalized_verdict": "INSUFFICIENT_EVIDENCE",
                "correct": False, "rule_id": "",
                "trace": "no gold evidence available",
            })
            confusion[(cc.expected_verdict, "INSUFFICIENT_EVIDENCE")] += 1
            pred_c["INSUFFICIENT_EVIDENCE"] += 1
            gold_c[cc.expected_verdict] += 1
            continue
        # Take ONLY the first gold evidence (isolate single-evidence)
        e = gold_ev[0]
        bundle = _build_evidence_bundle(e)
        trace = IntegrationTrace(claim_id=cid)
        try:
            result = core_verify(claim, bundle, trace)
            raw_verdict = result.verification_status
        except Exception as exc:  # noqa: BLE001
            raw_verdict = f"ERROR: {exc}"
            missing += 1
        norm = normalize_verdict_for_evaluation(raw_verdict)
        gold = cc.expected_verdict
        is_correct = norm == gold
        if is_correct:
            correct += 1
        # Extract rule_id from trace if available
        rule_id = ""
        if hasattr(trace, "detail") and isinstance(trace.detail, dict):
            for k in ("rule_id", "matched_rule", "verification_rule"):
                if k in trace.detail:
                    rule_id = str(trace.detail[k])
                    break
        confusion[(gold, norm)] += 1
        pred_c[norm] += 1
        gold_c[gold] += 1
        raw_verdict_c[raw_verdict] += 1
        rows.append({
            "claim_id": cid, "expected_verdict": gold,
            "core_verify_raw_verdict": raw_verdict,
            "normalized_verdict": norm, "correct": is_correct,
            "rule_id": rule_id,
            "trace": str(trace.detail)[:300] if hasattr(trace, "detail") else "",
        })

    total = len(claims)
    accuracy = correct / total if total else 0.0
    # per-class F1
    labels = sorted(set(gold_c) | set(pred_c))
    per_class = {}
    for lbl in labels:
        tp = confusion.get((lbl, lbl), 0)
        fp = sum(v for (g, p), v in confusion.items() if p == lbl and g != lbl)
        fn = sum(v for (g, p), v in confusion.items() if g == lbl and p != lbl)
        prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
        per_class[lbl] = {
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / max(prec + rec, 1e-9), 4),
            "support": gold_c.get(lbl, 0),
        }
    macro_f1 = sum(v["f1"] for v in per_class.values()) / max(len(per_class), 1)

    output = {
        "phase": "23.11.3",
        "script": "phase23_11_3_single_gold_verify",
        "description": "Isolate Selector/Aggregation: feed 1 Gold Evidence directly to core_verify",
        "sample_count": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "missing": missing,
        "raw_verdict_distribution": dict(raw_verdict_c),
        "confusion_matrix": {f"{g}|{p}": n for (g, p), n in sorted(confusion.items())},
        "diagnosis": {
            "if_single_gold_still_low": "root cause in core_verify or Verdict mapping, NOT Aggregation",
            "if_single_gold_recovers": "root cause in Selector or Aggregation",
            "current_single_gold_accuracy": round(accuracy, 4),
            "current_core_oracle_accuracy": 0.2093,
            "same_as_core_oracle": abs(accuracy - 0.2093) < 0.01,
        },
        "per_claim": rows,
    }
    AGG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Single-Gold verify written to {OUT_PATH}")
    print(f"  sample_count: {total}")
    print(f"  Single-Gold Accuracy: {accuracy:.4f}")
    print(f"  Single-Gold Macro-F1: {macro_f1:.4f}")
    print(f"  missing (no gold): {missing}")
    print(f"  raw_verdict_distribution: {dict(raw_verdict_c)}")
    print(f"  same as Core Oracle 0.2093? {abs(accuracy - 0.2093) < 0.01}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
