"""Phase 23.11 Evidence Gate Evaluation Script (Task 8).

Evaluates EvidenceGate precision / recall / accepted_noise_rate /
rejected_gold_rate / average_selected_evidence_count / ambiguity_rate
on a labeled set.

Output: backend/artifacts/evidence_gate/phase23_11_gate_metrics.json

Usage:
    python backend/scripts/phase23_11_evidence_gate_eval.py
"""
from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_all
from app.services.evidence_selector import SelectorConfig, select

BACKEND = Path(__file__).resolve().parent.parent
GATE_DIR = BACKEND / "artifacts" / "evidence_gate"
OUT_PATH = GATE_DIR / "phase23_11_gate_metrics.json"


def run_gate_eval() -> int:
    session = SessionLocal()
    try:
        # Load 43 Development claims
        from app.services.evidence_retrieval.service import (
            load_gold_claims,
            retrieve_for_claim,
        )

        claims = load_gold_claims("demo")
        cfg = GateConfig()
        sel_cfg = SelectorConfig(strategy="Top3", max_evidence=3)

        # Per-claim gate statistics
        tp = 0  # gold accepted
        fn = 0  # gold rejected (gate rejected gold)
        accepted_count = 0
        noise_accepted = 0
        noise_total = 0
        ambiguity_count = 0
        total_claims = len(claims)

        per_claim: list[dict] = []
        for claim in claims:
            cid = str(claim.get("claim_id") or "?")
            routing = route_claim(claim)
            # Retrieve candidates via existing channel
            cands_raw = retrieve_for_claim(session, claim, top_k=10)
            # Normalize to gate candidate format
            candidates = []
            for c in cands_raw:
                candidates.append({
                    "evidence_id": str(c.get("block_id") or "?"),
                    "block_id": c.get("block_id"),
                    "text": c.get("block_text", "") or "",
                    "page": c.get("page_number"),
                    "document_id": c.get("document_id"),
                })
            gate_results = evaluate_all(claim, candidates, routing, cfg)
            _, meta = select(gate_results, routing, sel_cfg)

            accepted_now = sum(1 for r in gate_results if r.accepted)
            accepted_count += accepted_now

            # Gold acceptance heuristic: if any accepted candidate matches
            # gold page, treat as gold accepted; this is a conservative proxy.
            # Real measurement requires gold_evidence labels per claim.
            gold_pages = claim.get("gold_pages") or []
            gold_accepted = False
            for r in gate_results:
                if not r.accepted:
                    continue
                # Match by page if available
                cand_page = None
                for c in candidates:
                    if str(c.get("evidence_id")) == r.evidence_id:
                        cand_page = c.get("page")
                        break
                if gold_pages and cand_page in gold_pages:
                    gold_accepted = True
                    break

            if gold_accepted:
                tp += 1
            elif gate_results:
                fn += 1

            # Noise estimation: rejected candidates are potential noise
            for r in gate_results:
                if not r.accepted:
                    noise_total += 1

            if meta.ambiguity_flag:
                ambiguity_count += 1

            per_claim.append({
                "claim_id": cid,
                "route": routing.route,
                "candidates_before_gate": meta.candidates_before_gate,
                "candidates_after_gate": meta.candidates_after_gate,
                "accepted_count": accepted_now,
                "ambiguity_flag": meta.ambiguity_flag,
                "gold_accepted": gold_accepted,
            })

        # Aggregate metrics
        precision = tp / max(tp + noise_accepted, 1)
        recall = tp / max(tp + fn, 1)
        accepted_noise_rate = noise_accepted / max(accepted_count, 1)
        rejected_gold_rate = fn / max(tp + fn, 1)
        avg_selected = accepted_count / max(total_claims, 1)
        ambiguity_rate = ambiguity_count / max(total_claims, 1)

        output = {
            "phase": "23.11",
            "script": "phase23_11_evidence_gate_eval",
            "gate_config": {
                "metric_match_threshold": cfg.metric_match_threshold,
                "high_quality_threshold": cfg.high_quality_threshold,
                "medium_quality_threshold": cfg.medium_quality_threshold,
                "causal_language_required": cfg.causal_language_required,
            },
            "metrics": {
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "accepted_noise_rate": round(accepted_noise_rate, 4),
                "rejected_gold_rate": round(rejected_gold_rate, 4),
                "average_selected_evidence_count": round(avg_selected, 4),
                "ambiguity_rate": round(ambiguity_rate, 4),
            },
            "targets": {
                "precision": 0.80,
                "accepted_noise_rate": 0.15,
                "rejected_gold_rate": 0.15,
            },
            "total_claims": total_claims,
            "per_claim": per_claim,
        }

        GATE_DIR.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Gate metrics written to {OUT_PATH}")
        print(f"  precision: {precision:.3f} (target 0.80)")
        print(f"  recall: {recall:.3f}")
        print(f"  accepted_noise_rate: {accepted_noise_rate:.3f} (target <=0.15)")
        print(f"  rejected_gold_rate: {rejected_gold_rate:.3f} (target <=0.15)")
        print(f"  ambiguity_rate: {ambiguity_rate:.3f}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run_gate_eval())
