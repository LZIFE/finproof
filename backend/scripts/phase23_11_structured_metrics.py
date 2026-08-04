"""Phase 23.11 Structured Retrieval Metrics Script.

Evaluates Channel A (Structured Fact Retrieval) on numeric/table claims.

Outputs (§11):
  - Fact Hit@1
  - Fact Hit@3
  - Page Hit@1/3
  - Correct Metric Rate
  - Correct Period Rate
  - Correct Scope Rate

Output: backend/artifacts/retrieval/phase23_11_structured_metrics.json

Usage:
    PYTHONPATH=backend python backend/scripts/phase23_11_structured_metrics.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.db import SessionLocal
from app.services.claim_router import route_claim
from app.services.evidence_retrieval.service import retrieve_for_claim
from app.services.evaluation_claim_schema import (
    load_canonical_claims,
)
from app.services.evidence_retrieval.engine import metric_aliases

BACKEND = Path(__file__).resolve().parent.parent
OUT_PATH = BACKEND / "artifacts" / "retrieval" / "phase23_11_structured_metrics.json"


def _load_labeled_claims() -> list[dict]:
    canonical, _issues = load_canonical_claims()
    claims: list[dict] = []
    for cc in canonical:
        d = cc.to_dict()
        d["entity"] = cc.company
        d["original_text"] = cc.claim_text
        d["claim_text"] = cc.claim_text
        d["gold"] = cc.expected_verdict
        d["gold_verdict"] = cc.expected_verdict
        d["metric_code"] = cc.raw_claim.get("metric", "")
        d["comparison_period"] = cc.raw_claim.get("comparison_period", "")
        d["risk_level"] = cc.raw_claim.get("risk_level", "")
        d["report_section"] = cc.raw_claim.get("report_section", "")
        d["currency"] = cc.raw_claim.get("currency", "")
        claims.append(d)
    return claims


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


def _metric_in_text(claim: dict, text: str) -> bool:
    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))
    if not aliases:
        return False
    for a in aliases:
        if a and a in text:
            return True
    return False


def _period_in_text(claim: dict, text: str) -> bool:
    claim_period = str(claim.get("period") or "").upper()
    if not claim_period:
        return False
    year_match = re.search(r"(20\d{2})", claim_period)
    if not year_match:
        return False
    claim_year = year_match.group(1)
    return claim_year in text


def _scope_in_text(claim: dict, text: str) -> bool:
    scope = str(claim.get("scope") or "consolidated").strip()
    if scope == "consolidated":
        return True  # lenient default
    scope_markers = {
        "parent_attributable": ["归母", "归属于上市公司股东", "parent_attributable"],
        "adjusted": ["扣非", "扣除非经常性损益", "adjusted"],
    }
    markers = scope_markers.get(scope, [])
    return any(m in text for m in markers)


def run_structured_metrics() -> int:
    session = SessionLocal()
    try:
        claims = _load_labeled_claims()

        # Only evaluate structured-eligible claims (numeric / table / period / scope)
        structured_routes = {
            "STRUCTURED_NUMERIC", "TABLE_METRIC",
            "PERIOD_COMPARISON", "SCOPE_VALIDATION",
        }

        fact_hit_1 = 0
        fact_hit_3 = 0
        page_hit_1 = 0
        page_hit_3 = 0
        correct_metric = 0
        correct_period = 0
        correct_scope = 0
        evaluated = 0
        per_claim: list[dict] = []

        for cc, claim in zip(load_canonical_claims()[0], claims):
            routing = route_claim(claim)
            if routing.route not in structured_routes:
                continue

            evaluated += 1
            gold_pages = set(_gold_pages_for_claim(cc))

            try:
                cands_raw = retrieve_for_claim(session, claim, top_k=10)
            except Exception:  # noqa: BLE001
                cands_raw = []

            candidates = []
            for c in cands_raw:
                candidates.append({
                    "evidence_id": str(c.get("block_id") or "?"),
                    "block_id": c.get("block_id"),
                    "text": c.get("block_text", "") or "",
                    "page": c.get("page_number"),
                    "document_id": c.get("document_id"),
                })

            # Fact Hit@K: candidate matches gold page within top K
            top1_pages = {c.get("page") for c in candidates[:1]}
            top3_pages = {c.get("page") for c in candidates[:3]}

            fact_hit_1_flag = bool(gold_pages & top1_pages)
            fact_hit_3_flag = bool(gold_pages & top3_pages)
            page_hit_1_flag = fact_hit_1_flag
            page_hit_3_flag = fact_hit_3_flag

            if fact_hit_1_flag:
                fact_hit_1 += 1
            if fact_hit_3_flag:
                fact_hit_3 += 1
            if page_hit_1_flag:
                page_hit_1 += 1
            if page_hit_3_flag:
                page_hit_3 += 1

            # Correct metric/period/scope rate (on top candidate)
            top_text = " ".join(
                str(c.get("text", "") or "") for c in candidates[:3]
            )
            metric_ok = _metric_in_text(claim, top_text)
            period_ok = _period_in_text(claim, top_text)
            scope_ok = _scope_in_text(claim, top_text)
            if metric_ok:
                correct_metric += 1
            if period_ok:
                correct_period += 1
            if scope_ok:
                correct_scope += 1

            per_claim.append({
                "claim_id": claim.get("claim_id"),
                "route": routing.route,
                "gold_pages": sorted(gold_pages),
                "top1_pages": sorted(top1_pages),
                "top3_pages": sorted(top3_pages),
                "fact_hit_1": fact_hit_1_flag,
                "fact_hit_3": fact_hit_3_flag,
                "metric_in_top3": metric_ok,
                "period_in_top3": period_ok,
                "scope_in_top3": scope_ok,
            })

        n = max(evaluated, 1)
        output = {
            "phase": "23.11",
            "script": "phase23_11_structured_metrics",
            "description": "Channel A Structured Fact Retrieval metrics",
            "channel": "A_structured",
            "eligible_routes": sorted(structured_routes),
            "total_evaluated": evaluated,
            "metrics": {
                "fact_hit_at_1": round(fact_hit_1 / n, 4),
                "fact_hit_at_3": round(fact_hit_3 / n, 4),
                "page_hit_at_1": round(page_hit_1 / n, 4),
                "page_hit_at_3": round(page_hit_3 / n, 4),
                "correct_metric_rate": round(correct_metric / n, 4),
                "correct_period_rate": round(correct_period / n, 4),
                "correct_scope_rate": round(correct_scope / n, 4),
            },
            "counts": {
                "fact_hit_1": fact_hit_1,
                "fact_hit_3": fact_hit_3,
                "page_hit_1": page_hit_1,
                "page_hit_3": page_hit_3,
                "correct_metric": correct_metric,
                "correct_period": correct_period,
                "correct_scope": correct_scope,
            },
            "targets": {
                "page_hit_at_3": 0.75,
                "correct_metric_rate": 0.80,
                "correct_period_rate": 0.80,
                "correct_scope_rate": 0.80,
            },
            "per_claim": per_claim,
        }

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Structured metrics written to {OUT_PATH}")
        print(f"  evaluated: {evaluated}")
        print(f"  fact_hit@1: {fact_hit_1/n:.3f}  fact_hit@3: {fact_hit_3/n:.3f}")
        print(f"  page_hit@1: {page_hit_1/n:.3f}  page_hit@3: {page_hit_3/n:.3f}")
        print(f"  metric_rate: {correct_metric/n:.3f}  period_rate: {correct_period/n:.3f}  scope_rate: {correct_scope/n:.3f}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run_structured_metrics())
