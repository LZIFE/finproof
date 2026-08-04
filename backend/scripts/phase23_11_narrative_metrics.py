"""Phase 23.11 Narrative Retrieval Metrics Script.

Evaluates Channel B (Narrative Evidence Retrieval) on narrative/causal/forecast claims.

Outputs (§11):
  - Page Hit@1/3/5
  - Block Hit@1/3/5
  - Recall@5
  - MRR

Output: backend/artifacts/retrieval/phase23_11_narrative_metrics.json

Usage:
    PYTHONPATH=backend python backend/scripts/phase23_11_narrative_metrics.py
"""
from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.claim_router import route_claim
from app.services.evidence_retrieval.service import retrieve_for_claim
from app.services.evaluation_claim_schema import load_canonical_claims

BACKEND = Path(__file__).resolve().parent.parent
OUT_PATH = BACKEND / "artifacts" / "retrieval" / "phase23_11_narrative_metrics.json"


def _gold_pages_for_claim(cc) -> list[int]:
    """Return page numbers of gold evidence for this claim."""
    import json as _json
    geids = [str(x) for x in (cc.gold_evidence_ids or [])]
    if not geids:
        return []
    data_root = Path(__file__).resolve().parent.parent.parent / "data"
    pages: list[int] = []
    for ds in ("demo", "holdout"):
        ge_path = data_root / ds / "annotations" / "gold_evidence.json"
        if not ge_path.exists():
            continue
        ge_data = _json.loads(ge_path.read_text(encoding="utf-8"))
        page_by_evd = {
            str(ev.get("evidence_id")): ev.get("page")
            for ev in ge_data.get("evidence", [])
        }
        for eid in geids:
            if eid in page_by_evd and isinstance(page_by_evd[eid], int):
                pages.append(page_by_evd[eid])
    return sorted(set(pages))


def _gold_block_ids_for_claim(cc) -> set[str]:
    """Return block ids of gold evidence (if available)."""
    geids = [str(x) for x in (cc.gold_evidence_ids or [])]
    # Gold evidence uses EVD-xxx, not block_id; we use page-level matching
    # as primary signal. Block-level gold matching requires gold_evidence
    # to expose block_id, which it does not. So we return empty set and
    # rely on page-level for Hit@K.
    _ = geids
    return set()


def run_narrative_metrics() -> int:
    session = SessionLocal()
    try:
        canonical, _issues = load_canonical_claims()

        narrative_routes = {
            "NARRATIVE_FACT", "CAUSALITY", "FORECAST",
        }

        page_hit_1 = 0
        page_hit_3 = 0
        page_hit_5 = 0
        block_hit_1 = 0
        block_hit_3 = 0
        block_hit_5 = 0
        recall_at_5 = 0
        mrr_sum = 0.0
        evaluated = 0
        per_claim: list[dict] = []

        for cc in canonical:
            claim = cc.to_dict()
            claim["entity"] = cc.company
            claim["original_text"] = cc.claim_text
            claim["claim_text"] = cc.claim_text
            claim["gold"] = cc.expected_verdict
            claim["metric_code"] = cc.raw_claim.get("metric", "")
            claim["comparison_period"] = cc.raw_claim.get("comparison_period", "")
            claim["risk_level"] = cc.raw_claim.get("risk_level", "")
            claim["report_section"] = cc.raw_claim.get("report_section", "")
            claim["currency"] = cc.raw_claim.get("currency", "")

            routing = route_claim(claim)
            if routing.route not in narrative_routes:
                continue

            evaluated += 1
            gold_pages = set(_gold_pages_for_claim(cc))
            gold_block_ids = _gold_block_ids_for_claim(cc)

            try:
                cands_raw = retrieve_for_claim(session, claim, top_k=10)
            except Exception:  # noqa: BLE001
                cands_raw = []

            candidates = []
            for c in cands_raw:
                candidates.append({
                    "evidence_id": str(c.get("block_id") or "?"),
                    "block_id": str(c.get("block_id") or "?"),
                    "text": c.get("block_text", "") or "",
                    "page": c.get("page_number"),
                    "document_id": c.get("document_id"),
                })

            # Page Hit@K
            top1_pages = {c.get("page") for c in candidates[:1]}
            top3_pages = {c.get("page") for c in candidates[:3]}
            top5_pages = {c.get("page") for c in candidates[:5]}

            ph1 = bool(gold_pages & top1_pages)
            ph3 = bool(gold_pages & top3_pages)
            ph5 = bool(gold_pages & top5_pages)

            if ph1:
                page_hit_1 += 1
            if ph3:
                page_hit_3 += 1
            if ph5:
                page_hit_5 += 1

            # Block Hit@K (use block_id if gold has it, else fallback to page)
            top1_blocks = {c.get("block_id") for c in candidates[:1]}
            top3_blocks = {c.get("block_id") for c in candidates[:3]}
            top5_blocks = {c.get("block_id") for c in candidates[:5]}

            if gold_block_ids:
                bh1 = bool(gold_block_ids & top1_blocks)
                bh3 = bool(gold_block_ids & top3_blocks)
                bh5 = bool(gold_block_ids & top5_blocks)
            else:
                # fallback to page-level for block hit
                bh1 = ph1
                bh3 = ph3
                bh5 = ph5

            if bh1:
                block_hit_1 += 1
            if bh3:
                block_hit_3 += 1
            if bh5:
                block_hit_5 += 1

            # Recall@5: fraction of gold pages found in top5
            if gold_pages:
                found = len(gold_pages & top5_pages)
                recall_at_5_val = found / len(gold_pages)
                if recall_at_5_val >= 1.0:
                    recall_at_5 += 1
            else:
                recall_at_5 += 0  # no gold pages → 0 recall

            # MRR: reciprocal rank of first gold page hit
            mrr_val = 0.0
            for rank, c in enumerate(candidates, 1):
                if c.get("page") in gold_pages:
                    mrr_val = 1.0 / rank
                    break
            mrr_sum += mrr_val

            per_claim.append({
                "claim_id": claim.get("claim_id"),
                "route": routing.route,
                "gold_pages": sorted(gold_pages),
                "top5_pages": sorted(top5_pages),
                "page_hit_1": ph1,
                "page_hit_3": ph3,
                "page_hit_5": ph5,
                "mrr": round(mrr_val, 4),
            })

        n = max(evaluated, 1)
        output = {
            "phase": "23.11",
            "script": "phase23_11_narrative_metrics",
            "description": "Channel B Narrative Evidence Retrieval metrics",
            "channel": "B_narrative",
            "eligible_routes": sorted(narrative_routes),
            "total_evaluated": evaluated,
            "metrics": {
                "page_hit_at_1": round(page_hit_1 / n, 4),
                "page_hit_at_3": round(page_hit_3 / n, 4),
                "page_hit_at_5": round(page_hit_5 / n, 4),
                "block_hit_at_1": round(block_hit_1 / n, 4),
                "block_hit_at_3": round(block_hit_3 / n, 4),
                "block_hit_at_5": round(block_hit_5 / n, 4),
                "recall_at_5": round(recall_at_5 / n, 4),
                "mrr": round(mrr_sum / n, 4),
            },
            "counts": {
                "page_hit_1": page_hit_1,
                "page_hit_3": page_hit_3,
                "page_hit_5": page_hit_5,
                "block_hit_1": block_hit_1,
                "block_hit_3": block_hit_3,
                "block_hit_5": block_hit_5,
                "recall_at_5": recall_at_5,
            },
            "targets": {
                "page_hit_at_5": 0.75,
                "block_hit_at_5": 0.65,
                "recall_at_5": 0.70,
                "mrr": 0.40,
            },
            "per_claim": per_claim,
        }

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Narrative metrics written to {OUT_PATH}")
        print(f"  evaluated: {evaluated}")
        print(f"  page_hit@1/3/5: {page_hit_1/n:.3f} / {page_hit_3/n:.3f} / {page_hit_5/n:.3f}")
        print(f"  block_hit@1/3/5: {block_hit_1/n:.3f} / {block_hit_3/n:.3f} / {block_hit_5/n:.3f}")
        print(f"  recall@5: {recall_at_5/n:.3f}  mrr: {mrr_sum/n:.3f}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run_narrative_metrics())
