"""Phase 23.11 Development E2E Script.

Runs full Real E2E on all 43 Development Claims with the 5 strategies
defined in §12:
  1. Phase 23.9 original (from phase23_9_development_e2e.json)
  2. Phase 23.10 original (from phase23_10_development_e2e.json)
  3. Phase 23.11 Top1 strategy
  4. Phase 23.11 Top3 strategy
  5. Phase 23.11 Gate strategy (default)

Outputs identical metrics for each strategy:
  Accuracy, Macro-F1, coverage, abstention, retrieval failures,
  verification failures.

Output: backend/artifacts/e2e/phase23_11_development_e2e.json

Usage:
    PYTHONPATH=backend python backend/scripts/phase23_11_development_e2e.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from sklearn.metrics import f1_score

from app.db import SessionLocal
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_all
from app.services.evidence_selector import SelectorConfig, select
from app.services.evidence_retrieval.service import retrieve_for_claim
from app.services.verification.verification_service import (
    verify_evidence_set,
)
from app.services.verification_context import VerificationContext
from app.services.verification.base import VerificationResult

BACKEND = Path(__file__).resolve().parent.parent
OUT_PATH = BACKEND / "artifacts" / "e2e" / "phase23_11_development_e2e.json"


def _load_labeled_claims() -> list[dict]:
    """Load 43 Development Claims joined with gold verdicts."""
    from app.services.evaluation_claim_schema import (
        load_canonical_claims,
    )

    canonical, _issues = load_canonical_claims()
    claims: list[dict] = []
    for cc in canonical:
        d = cc.to_dict()
        d["entity"] = cc.company
        d["original_text"] = cc.claim_text
        d["claim_text"] = cc.claim_text
        d["gold"] = cc.expected_verdict
        d["gold_verdict"] = cc.expected_verdict
        d["comparison_period"] = cc.raw_claim.get("comparison_period", "")
        d["risk_level"] = cc.raw_claim.get("risk_level", "")
        d["report_section"] = cc.raw_claim.get("report_section", "")
        d["currency"] = cc.raw_claim.get("currency", "")
        d["metric_code"] = cc.raw_claim.get("metric", "")
        claims.append(d)
    return claims


def _macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    """Compute macro-F1 across all label classes."""
    labels = sorted(set(y_true) | set(y_pred))
    if not labels:
        return 0.0
    return float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0))


def _run_strategy(
    session,
    claims: list[dict],
    strategy_name: str,
    sel_strategy: str,
    max_evidence: int,
) -> dict:
    """Run a single strategy and return metrics dict."""
    gate_cfg = GateConfig()
    sel_cfg = SelectorConfig(
        strategy=sel_strategy,
        max_evidence=max_evidence,
        ambiguity_margin=0.05,
    )

    correct = 0
    abstentions = 0
    coverage_count = 0
    retrieval_failures = 0
    verification_failures = 0
    y_true: list[str] = []
    y_pred: list[str] = []
    per_claim: list[dict] = []

    for claim in claims:
        cid = str(claim.get("claim_id") or "?")
        gold = str(claim.get("gold") or "UNKNOWN")
        routing = route_claim(claim)
        ctx = VerificationContext(
            evidence_source="real_e2e",
            gate_config=gate_cfg,
            selector_config=sel_cfg,
        )

        # Retrieve candidates
        try:
            cands_raw = retrieve_for_claim(session, claim, top_k=10)
        except Exception:  # noqa: BLE001
            cands_raw = []
        if not cands_raw:
            retrieval_failures += 1

        candidates = []
        for c in cands_raw:
            candidates.append({
                "evidence_id": str(c.get("block_id") or "?"),
                "block_id": c.get("block_id"),
                "text": c.get("block_text", "") or "",
                "page": c.get("page_number"),
                "document_id": c.get("document_id"),
            })

        try:
            result = verify_evidence_set(claim, candidates, routing, ctx)
        except Exception as exc:  # noqa: BLE001
            result = VerificationResult(
                cid, "INSUFFICIENT_EVIDENCE",
                confidence=0.2, reason=f"error: {exc}",
            )

        pred = result.verification_status
        is_correct = pred == gold
        if is_correct:
            correct += 1
        else:
            verification_failures += 1
        if pred == "INSUFFICIENT_EVIDENCE":
            abstentions += 1
        else:
            coverage_count += 1

        y_true.append(gold)
        y_pred.append(pred)

        per_claim.append({
            "claim_id": cid,
            "route": routing.route,
            "gold": gold,
            "pred": pred,
            "correct": is_correct,
            "candidates_before_gate": ctx.candidates_before_gate,
            "candidates_after_gate": ctx.candidates_after_gate,
        })

    total = len(claims)
    accuracy = correct / total if total else 0.0
    coverage = coverage_count / total if total else 0.0
    macro_f1 = _macro_f1(y_true, y_pred)

    # Per-class F1
    labels = sorted(set(y_true) | set(y_pred))
    per_class_f1 = {}
    if labels:
        from sklearn.metrics import f1_score as _f1
        for label in labels:
            per_class_f1[label] = float(
                _f1(y_true, y_pred, labels=[label], average="macro", zero_division=0)
            )

    pred_dist = dict(Counter(y_pred))

    return {
        "strategy": strategy_name,
        "selector_strategy": sel_strategy,
        "max_evidence": max_evidence,
        "total_claims": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class_f1": {k: round(v, 4) for k, v in per_class_f1.items()},
        "coverage": round(coverage, 4),
        "abstentions": abstentions,
        "retrieval_failures": retrieval_failures,
        "verification_failures": verification_failures,
        "pred_distribution": pred_dist,
        "per_claim": per_claim,
    }


def run_development_e2e() -> int:
    session = SessionLocal()
    try:
        claims = _load_labeled_claims()

        # Run all 5 strategies
        results = []

        # Strategy 3: Phase 23.11 Top1
        results.append(_run_strategy(
            session, claims, "phase23_11_top1", "Top1", 1,
        ))

        # Strategy 4: Phase 23.11 Top3
        results.append(_run_strategy(
            session, claims, "phase23_11_top3", "Top3", 3,
        ))

        # Strategy 5: Phase 23.11 Gate (default = Top3)
        results.append(_run_strategy(
            session, claims, "phase23_11_gate", "Top3", 3,
        ))

        # Load Phase 23.9 and 23.10 original results for comparison
        phase23_9_path = BACKEND / "artifacts" / "e2e" / "phase23_9_development_e2e.json"
        phase23_10_path = BACKEND / "artifacts" / "e2e" / "phase23_10_development_e2e.json"

        phase23_9_summary = {}
        if phase23_9_path.exists():
            p9 = json.loads(phase23_9_path.read_text(encoding="utf-8"))
            phase23_9_summary = {
                "accuracy": p9.get("accuracy") or p9.get("metrics", {}).get("accuracy", 0),
                "macro_f1": p9.get("macro_f1") or p9.get("metrics", {}).get("macro_f1", 0),
                "coverage": p9.get("coverage") or p9.get("metrics", {}).get("coverage", 0),
                "source": str(phase23_9_path.name),
            }

        phase23_10_summary = {}
        if phase23_10_path.exists():
            p10 = json.loads(phase23_10_path.read_text(encoding="utf-8"))
            phase23_10_summary = {
                "accuracy": p10.get("accuracy") or p10.get("metrics", {}).get("accuracy", 0),
                "macro_f1": p10.get("macro_f1") or p10.get("metrics", {}).get("macro_f1", 0),
                "coverage": p10.get("coverage") or p10.get("metrics", {}).get("coverage", 0),
                "source": str(phase23_10_path.name),
            }

        output = {
            "phase": "23.11",
            "script": "phase23_11_development_e2e",
            "description": "Phase 23.11 Real E2E: 5 strategies × 43 Development Claims",
            "total_claims": len(claims),
            "strategies": results,
            "comparison": {
                "phase23_9": phase23_9_summary,
                "phase23_10": phase23_10_summary,
                "phase23_11_top1": {
                    "accuracy": results[0]["accuracy"],
                    "macro_f1": results[0]["macro_f1"],
                    "coverage": results[0]["coverage"],
                },
                "phase23_11_top3": {
                    "accuracy": results[1]["accuracy"],
                    "macro_f1": results[1]["macro_f1"],
                    "coverage": results[1]["coverage"],
                },
                "phase23_11_gate": {
                    "accuracy": results[2]["accuracy"],
                    "macro_f1": results[2]["macro_f1"],
                    "coverage": results[2]["coverage"],
                },
            },
            "targets": {
                "real_e2e_accuracy": 0.70,
                "real_e2e_macro_f1": 0.60,
                "coverage": 0.65,
                "selective_accuracy": 0.80,
                "verification_errors": 3,
            },
            "notes": [
                "Phase 23.9 and 23.10 original results loaded from artifact JSONs.",
                "Phase 23.11 strategies use the unified verify_evidence_set entry.",
                "Gate/Selector now carry candidate text into core_verify (fix for E2E accuracy).",
            ],
        }

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Development E2E written to {OUT_PATH}")
        for r in results:
            print(f"  {r['strategy']}: acc={r['accuracy']:.3f} mf1={r['macro_f1']:.3f} "
                  f"cov={r['coverage']:.3f} abst={r['abstentions']}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run_development_e2e())
