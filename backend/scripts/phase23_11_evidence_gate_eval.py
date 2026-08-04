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


def _load_labeled_claims() -> tuple[list[dict], list[dict]]:
    """Load 43 Development Claims joined with gold verdicts + gold evidence.

    Returns (claims, per_claim_seed) where each claim dict carries:
      claim_id, entity/company, original_text, period, metric, value,
      unit, scope, gold (expected_verdict), gold_evidence_ids (list[str]),
      gold_pages (list[int]) — page numbers extracted from gold_evidence.

    Uses the canonical loader (evaluation_claim_schema) which joins
    gold_claims + gold_verifications + gold_evidence by claim_id.
    """
    import json as _json
    from app.services.evaluation_claim_schema import (
        load_canonical_claims,
    )

    # Build text lookup from gold_evidence.json (EVD-id → evidence_text).
    gold_text_by_evd: dict[str, str] = {}
    data_root = Path(__file__).resolve().parent.parent.parent / "data"
    for ds in ("demo", "holdout"):
        ge_path = data_root / ds / "annotations" / "gold_evidence.json"
        if not ge_path.exists():
            continue
        ge_data = _json.loads(ge_path.read_text(encoding="utf-8"))
        for ev in ge_data.get("evidence", []):
            eid = str(ev.get("evidence_id") or "")
            txt = str(ev.get("evidence_text", "") or "").strip()
            if eid and txt:
                gold_text_by_evd[eid] = txt

    canonical, _issues = load_canonical_claims()
    claims: list[dict] = []
    for cc in canonical:
        d = cc.to_dict()
        d["entity"] = cc.company
        d["original_text"] = cc.claim_text
        d["gold"] = cc.expected_verdict
        d["gold_verdict"] = cc.expected_verdict
        geids = cc.gold_evidence_ids or []
        d["gold_evidence_ids"] = [str(x) for x in geids]
        # gold_texts: normalized evidence texts for block-level matching
        d["gold_texts"] = sorted({
            gold_text_by_evd.get(eid, "").strip()
            for eid in geids if eid in gold_text_by_evd
        })
        claims.append(d)
    return claims, []


def run_gate_eval() -> int:
    session = SessionLocal()
    try:
        claims, _ = _load_labeled_claims()
        from app.services.evidence_retrieval.service import (
            retrieve_for_claim,
        )

        cfg = GateConfig()
        sel_cfg = SelectorConfig(strategy="Top3", max_evidence=3)

        # Aggregate counters
        # Gold evidence acceptance (recall-oriented)
        gold_evidence_total = 0  # total gold evidence ids seen across claims
        gold_evidence_accepted = 0  # gold evidence accepted by gate
        gold_evidence_rejected = 0  # gold evidence rejected by gate

        # Candidate-level noise (precision-oriented)
        # "noise" = a candidate that is NOT in gold_evidence_ids but is
        # ACCEPTED by the gate. "rejected gold" = gold evidence rejected.
        accepted_noise_count = 0  # accepted candidates that are not gold
        accepted_total_count = 0  # all accepted candidates
        accepted_gold_count = 0  # accepted candidates that ARE gold

        rejected_noise_count = 0  # rejected candidates that are not gold
        rejected_gold_count_total = 0  # rejected candidates that ARE gold

        ambiguity_count = 0
        total_claims = len(claims)

        per_claim: list[dict] = []
        for claim in claims:
            cid = str(claim.get("claim_id") or "?")
            gold_eids = set(claim.get("gold_evidence_ids") or [])
            gold_pages = set(claim.get("gold_pages") or [])
            routing = route_claim(claim)
            # Retrieve candidates via existing channel
            cands_raw = retrieve_for_claim(session, claim, top_k=10)
            # Normalize to gate candidate format; keep a text map for
            # evidence_id lookup.
            candidates: list[dict] = []
            for c in cands_raw:
                eid = str(c.get("block_id") or "?")
                candidates.append({
                    "evidence_id": eid,
                    "block_id": c.get("block_id"),
                    "text": c.get("block_text", "") or "",
                    "page": c.get("page_number"),
                    "document_id": c.get("document_id"),
                })

            gate_results = evaluate_all(claim, candidates, routing, cfg)
            _, meta = select(gate_results, routing, sel_cfg)

            # Build set of accepted evidence_ids
            accepted_ids = {r.evidence_id for r in gate_results if r.accepted}
            all_cand_ids = {c.get("evidence_id") for c in candidates}

            # Gold matching: text-based block-level matching.
            # Each candidate's text is checked against gold_texts.
            # A candidate is gold if its text CONTAINS the gold evidence text
            # (or vice versa — normalized comparison).
            # Page-level matching is ONLY used as auxiliary diagnosis, NOT
            # for gold determination (Phase 23.11.4 §3).
            cand_by_eid = {c.get("evidence_id"): c for c in candidates}
            gold_texts = set(claim.get("gold_texts") or [])

            def _normalize(t: str) -> str:
                """Normalize text for comparison: strip, collapse whitespace."""
                import re
                return re.sub(r'\s+', ' ', t).strip()

            def _is_gold_cand(r_eid: str) -> bool:
                # direct EVD-id match
                if r_eid in gold_eids:
                    return True
                # text-based block-level matching
                cand = cand_by_eid.get(r_eid)
                if not cand:
                    return False
                cand_text = _normalize(cand.get("text", "") or "")
                if not cand_text:
                    return False
                for gt in gold_texts:
                    gt_norm = _normalize(gt)
                    if not gt_norm:
                        continue
                    # Check mutual containment
                    if gt_norm in cand_text or cand_text in gt_norm:
                        return True
                return False

            # Count accepted/rejected vs gold/noise at candidate level
            for r in gate_results:
                is_gold = _is_gold_cand(r.evidence_id)
                if r.accepted:
                    accepted_total_count += 1
                    if is_gold:
                        accepted_gold_count += 1
                    else:
                        accepted_noise_count += 1
                else:
                    if is_gold:
                        rejected_gold_count_total += 1
                    else:
                        rejected_noise_count += 1

            # Gold evidence acceptance (recall of gold evidence by gate)
            # For each gold text, check whether any accepted candidate's text
            # matches (block-level text matching, NOT page-level).
            # Page-level is ONLY auxiliary diagnosis (Phase 23.11.4 §3).
            accepted_texts = {
                _normalize(cand_by_eid[eid].get("text", "") or "")
                for eid in accepted_ids
                if eid in cand_by_eid
            }
            for gt in gold_texts:
                gt_norm = _normalize(gt)
                if not gt_norm:
                    continue
                gold_evidence_total += 1
                if any(gt_norm in at or at in gt_norm for at in accepted_texts if at):
                    gold_evidence_accepted += 1
                else:
                    gold_evidence_rejected += 1

            if meta.ambiguity_flag:
                ambiguity_count += 1

            per_claim.append({
                "claim_id": cid,
                "route": routing.route,
                "candidates_before_gate": meta.candidates_before_gate,
                "candidates_after_gate": meta.candidates_after_gate,
                "accepted_count": len(accepted_ids),
                "ambiguity_flag": meta.ambiguity_flag,
                "gold_evidence_ids": sorted(gold_eids),
                "gold_pages": sorted(gold_pages),
                "accepted_ids": sorted(accepted_ids),
            })

        # Aggregate metrics
        # precision = accepted gold / all accepted
        precision = accepted_gold_count / max(accepted_total_count, 1)
        # recall = accepted gold / (accepted gold + rejected gold)
        # i.e. of all gold evidence that reached the gate, how much was kept
        denom_recall = accepted_gold_count + rejected_gold_count_total
        recall = accepted_gold_count / max(denom_recall, 1)
        # accepted_noise_rate = accepted noise / all accepted
        accepted_noise_rate = accepted_noise_count / max(accepted_total_count, 1)
        # rejected_gold_rate = rejected gold / (accepted gold + rejected gold)
        rejected_gold_rate = rejected_gold_count_total / max(denom_recall, 1)
        avg_selected = accepted_total_count / max(total_claims, 1)
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
            "counts": {
                "total_claims": total_claims,
                "accepted_total": accepted_total_count,
                "accepted_gold": accepted_gold_count,
                "accepted_noise": accepted_noise_count,
                "rejected_gold": rejected_gold_count_total,
                "rejected_noise": rejected_noise_count,
                "gold_evidence_total": gold_evidence_total,
                "gold_evidence_accepted": gold_evidence_accepted,
                "gold_evidence_rejected": gold_evidence_rejected,
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
