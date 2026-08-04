"""Phase 23.11 Leave-One-Company-Out Tuning Script (Task 9).

Two-fold cross-validation:
- Fold A: tune on 五粮液, validate on 美的集团
- Fold B: tune on 美的集团, validate on 五粮液

Tunable parameters (ONLY these):
- Evidence Gate thresholds (metric_match_threshold,
  high_quality_threshold, medium_quality_threshold)
- quality_margin
- Structured/Narrative channel weights (implicit via routing)
- Top1/Top3 selection
- ambiguity_threshold

Forbidden: claim-specific params, company-specific params, Gold Page
features, block_id features, repeated tuning on validation set.

Each fold persists frozen parameters and first-validation results.

Output: backend/artifacts/cross_validation/phase23_11_leave_one_company_out.json

Usage:
    PYTHONPATH=. python scripts/phase23_11_leave_one_company_out.py
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass

from app.db import SessionLocal
from app.services.claim_router import route_claim
from app.services.evidence_gate import (
    GateConfig,
    evaluate_all,
)
from app.services.evidence_selector import (
    SelectorConfig,
    select,
)
from app.services.verification.verification_service import (
    verify_evidence_set,
)
from app.services.verification_context import VerificationContext

BACKEND = Path(__file__).resolve().parent.parent
OUT_PATH = BACKEND / "artifacts" / "cross_validation" / "phase23_11_leave_one_company_out.json"


@dataclass
class ParamGrid:
    """Search grid for tunable parameters."""

    metric_match_thresholds: tuple[float, ...] = (0.4, 0.5, 0.6)
    high_quality_thresholds: tuple[float, ...] = (0.6, 0.7, 0.8)
    medium_quality_thresholds: tuple[float, ...] = (0.3, 0.4, 0.5)
    ambiguity_margins: tuple[float, ...] = (0.03, 0.05, 0.10)
    strategies: tuple[str, ...] = ("Top1", "Top3")


def load_development_claims() -> list[dict]:
    """Load 43 Development Claims split by company."""
    from app.services.evidence_retrieval.service import load_gold_claims

    claims = load_gold_claims("demo")
    return claims


def split_by_company(claims: list[dict]) -> dict[str, list[dict]]:
    """Split claims into 五粮液 / 美的集团 / other buckets."""
    buckets: dict[str, list[dict]] = {"五粮液": [], "美的集团": [], "other": []}
    for c in claims:
        entity = str(c.get("entity") or c.get("entity_name") or "").strip()
        if "五粮液" in entity:
            buckets["五粮液"].append(c)
        elif "美的" in entity:
            buckets["美的集团"].append(c)
        else:
            buckets["other"].append(c)
    return buckets


def evaluate_config(
    session,
    claims: list[dict],
    gate_cfg: GateConfig,
    sel_cfg: SelectorConfig,
) -> dict:
    """Evaluate a (gate_cfg, sel_cfg) pair on the given claims.

    Returns accuracy, coverage, abstentions.
    """
    from app.services.verification.base import VerificationResult

    correct = 0
    coverage_count = 0
    abstentions = 0
    total = len(claims)

    for claim in claims:
        cid = str(claim.get("claim_id") or "?")
        gold = str(claim.get("gold") or claim.get("gold_verdict") or "UNKNOWN")
        routing = route_claim(claim)
        ctx = VerificationContext(
            evidence_source="real_e2e",
            gate_config=gate_cfg,
            selector_config=sel_cfg,
        )
        # Retrieve candidates via existing channel
        from app.services.evidence_retrieval.service import retrieve_for_claim

        cands_raw = retrieve_for_claim(session, claim, top_k=10)
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
                cid, "INSUFFICIENT_EVIDENCE", confidence=0.2,
                reason=f"error: {exc}",
            )
        pred = result.verification_status
        if pred == gold:
            correct += 1
        if pred == "INSUFFICIENT_EVIDENCE":
            abstentions += 1
        else:
            coverage_count += 1

    return {
        "accuracy": round(correct / max(total, 1), 4),
        "coverage": round(coverage_count / max(total, 1), 4),
        "abstentions": abstentions,
        "correct": correct,
        "total": total,
    }


def tune_fold(
    session,
    train_claims: list[dict],
    validate_claims: list[dict],
    fold_name: str,
) -> dict:
    """Tune on train_claims, freeze best config, evaluate on validate_claims.

    First validation only (no repeated tuning on validation set).
    """
    grid = ParamGrid()
    best_score = -1.0
    best_gate = None
    best_sel = None
    best_train_metrics = None
    tried = []

    # Grid search on TRAINING set
    for mmt in grid.metric_match_thresholds:
        for hqt in grid.high_quality_thresholds:
            for mqt in grid.medium_quality_thresholds:
                if mqt >= hqt:
                    continue
                for am in grid.ambiguity_margins:
                    for strat in grid.strategies:
                        gate_cfg = GateConfig(
                            metric_match_threshold=mmt,
                            high_quality_threshold=hqt,
                            medium_quality_threshold=mqt,
                        )
                        sel_cfg = SelectorConfig(
                            strategy=strat,
                            max_evidence=3,
                            ambiguity_margin=am,
                        )
                        train_metrics = evaluate_config(
                            session, train_claims, gate_cfg, sel_cfg
                        )
                        score = train_metrics["accuracy"]
                        tried.append({
                            "metric_match_threshold": mmt,
                            "high_quality_threshold": hqt,
                            "medium_quality_threshold": mqt,
                            "ambiguity_margin": am,
                            "strategy": strat,
                            "train_accuracy": score,
                        })
                        if score > best_score:
                            best_score = score
                            best_gate = gate_cfg
                            best_sel = sel_cfg
                            best_train_metrics = train_metrics

    # Freeze best config, evaluate ONCE on validation set
    validate_metrics = evaluate_config(
        session, validate_claims, best_gate, best_sel
    )

    return {
        "fold": fold_name,
        "train_company": "五粮液" if fold_name == "A" else "美的集团",
        "validate_company": "美的集团" if fold_name == "A" else "五粮液",
        "best_train_accuracy": best_score,
        "best_train_metrics": best_train_metrics,
        "frozen_params": {
            "metric_match_threshold": best_gate.metric_match_threshold,
            "high_quality_threshold": best_gate.high_quality_threshold,
            "medium_quality_threshold": best_gate.medium_quality_threshold,
            "ambiguity_margin": best_sel.ambiguity_margin,
            "strategy": best_sel.strategy,
        },
        "first_validation_metrics": validate_metrics,
        "grid_search_count": len(tried),
    }


def run_leave_one_company_out() -> int:
    session = SessionLocal()
    try:
        all_claims = load_development_claims()
        buckets = split_by_company(all_claims)

        wuliangye = buckets["五粮液"]
        midea = buckets["美的集团"]
        other = buckets["other"]

        # Fold A: train on 五粮液, validate on 美的集团
        fold_a = tune_fold(
            session, wuliangye, midea, "A"
        ) if wuliangye and midea else {"error": "missing 五粮液 or 美的集团 claims"}

        # Fold B: train on 美的集团, validate on 五粮液
        fold_b = tune_fold(
            session, midea, wuliangye, "B"
        ) if midea and wuliangye else {"error": "missing 美的集团 or 五粮液 claims"}

        # Stable weights: take interval across both folds
        stable = {}
        if "frozen_params" in fold_a and "frozen_params" in fold_b:
            for key in fold_a["frozen_params"]:
                a_val = fold_a["frozen_params"][key]
                b_val = fold_b["frozen_params"][key]
                if isinstance(a_val, (int, float)):
                    stable[key] = {
                        "fold_a": a_val,
                        "fold_b": b_val,
                        "stable_value": round((a_val + b_val) / 2, 4),
                    }
                else:
                    stable[key] = {"fold_a": a_val, "fold_b": b_val}

        output = {
            "phase": "23.11",
            "script": "phase23_11_leave_one_company_out",
            "description": "Two-fold leave-one-company-out CV (五粮液 <-> 美的集团)",
            "claim_counts": {
                "五粮液": len(wuliangye),
                "美的集团": len(midea),
                "other": len(other),
                "total": len(all_claims),
            },
            "tunable_parameters": [
                "metric_match_threshold",
                "high_quality_threshold",
                "medium_quality_threshold",
                "ambiguity_margin",
                "strategy (Top1/Top3)",
            ],
            "forbidden": [
                "claim-specific parameters",
                "company-specific parameters",
                "Gold Page features",
                "block_id features",
                "repeated tuning on validation set",
            ],
            "fold_a": fold_a,
            "fold_b": fold_b,
            "stable_weights": stable,
        }

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Leave-one-company-out results written to {OUT_PATH}")
        print(f"  五粮液 claims: {len(wuliangye)}")
        print(f"  美的集团 claims: {len(midea)}")
        if "error" not in fold_a:
            print(f"  Fold A train acc: {fold_a['best_train_accuracy']:.3f}")
            print(f"  Fold A validate acc: {fold_a['first_validation_metrics']['accuracy']:.3f}")
        if "error" not in fold_b:
            print(f"  Fold B train acc: {fold_b['best_train_accuracy']:.3f}")
            print(f"  Fold B validate acc: {fold_b['first_validation_metrics']['accuracy']:.3f}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run_leave_one_company_out())
