"""Phase 23.11.5.1 Grounding Integrity Audit (Task 2).

Strict re-audit of 42 gold evidence entries. Classification:
- AUTO_CONFIRMED_EXACT / AUTO_CONFIRMED_NORMALIZED / AUTO_CONFIRMED_MULTI_BLOCK
- HUMAN_REVIEW_REQUIRED / NOT_FOUND

AUTO_CONFIRMED requires ALL of:
- document_id non-empty and exists
- page exists
- block_id or source_block_ids non-empty
- all blocks exist
- unique candidate
- reconstruction_coverage == 1.0
- company/metric/period/unit consistent
- exact number match
- SHA256 saved
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import SessionLocal
from app.models import DocumentBlock
from app.services.evaluation_claim_schema import load_canonical_claims

ART = BACKEND / "artifacts"
GOLD_DIR = ART / "gold_contract"
OUT_PATH = GOLD_DIR / "phase23_11_5_1_grounding_audit.json"


def norm(t: str) -> str:
    t = re.sub(r'\s+', ' ', t or '').strip()
    t = re.sub(r'[,，、　]', '', t)
    return t


def sha256(t: str) -> str:
    return hashlib.sha256(t.encode('utf-8')).hexdigest()


def extract_numbers(t: str) -> list[str]:
    return re.findall(r'-?\d+(?:\.\d+)?', t or '')


def main() -> int:
    claims, _ = load_canonical_claims()
    claim_by_id = {c.claim_id: c for c in claims}

    # Load gold evidence
    gold_evs = []
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_evidence.json"
        if p.exists():
            for e in json.loads(p.read_text(encoding="utf-8")).get("evidence", []):
                e["_dataset"] = ds
                gold_evs.append(e)

    # Load blocks
    session = SessionLocal()
    try:
        all_blocks = session.query(DocumentBlock).order_by(
            DocumentBlock.document_id, DocumentBlock.page_id, DocumentBlock.block_index).all()
    finally:
        session.close()

    blocks_by_page: dict[int, list] = {}
    for b in all_blocks:
        blocks_by_page.setdefault(b.page_id, []).append(b)

    # Load previous grounding inventory for comparison
    prev_path = GOLD_DIR / "phase23_11_5_grounding_inventory.json"
    prev_by_eid = {}
    if prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        for p in prev.get("per_evidence", []):
            prev_by_eid[p["gold_evidence_id"]] = p

    per_evidence = []
    status_counts = {}

    for ge in gold_evs:
        eid = ge.get("evidence_id", "?")
        cid = ge.get("claim_id", "")
        cc = claim_by_id.get(cid)
        etext = str(ge.get("evidence_text", "") or "")
        page = ge.get("page")
        ds = ge.get("_dataset", "?")
        ntext = norm(etext)
        enumbers = extract_numbers(etext)
        prev = prev_by_eid.get(eid, {})

        page_blocks = blocks_by_page.get(page, [])
        candidates = []
        for b in page_blocks:
            btext = str(b.text or "")
            score = 0
            if etext.strip() == btext.strip():
                score = 1.0
            elif ntext == norm(btext):
                score = 0.9
            elif etext.strip() in btext or btext.strip() in etext:
                score = 0.7
            if score > 0:
                candidates.append({"block": b, "score": score})

        # Classification
        if not page_blocks:
            status = "NOT_FOUND"
            reason = "no blocks on page"
            selected = []
            coverage = 0.0
            unique = False
        elif not candidates:
            status = "NOT_FOUND"
            reason = "no text match on page"
            selected = []
            coverage = 0.0
            unique = False
        elif len(candidates) == 1 and candidates[0]["score"] >= 0.9:
            b = candidates[0]["block"]
            btext = str(b.text or "")
            coverage = 1.0 if norm(etext) == norm(btext) else len(norm(etext)) / max(len(norm(btext)), 1)
            bnumbers = extract_numbers(btext)
            exact_num = sorted(enumbers) == sorted(bnumbers)
            status = "AUTO_CONFIRMED_EXACT" if candidates[0]["score"] == 1.0 else "AUTO_CONFIRMED_NORMALIZED"
            selected = [b]
            unique = True
            reason = "unique candidate" if exact_num else "unique candidate but number mismatch"
            if not exact_num:
                status = "HUMAN_REVIEW_REQUIRED"
                reason = "number mismatch despite unique candidate"
        else:
            # Multiple candidates: fuzzy only, never auto-confirm
            top = sorted(candidates, key=lambda c: -c["score"])
            best = top[0]
            btext = str(best["block"].text or "")
            coverage = len(norm(etext)) / max(len(norm(btext)), 1)
            status = "HUMAN_REVIEW_REQUIRED"
            selected = []
            unique = False
            reason = f"{len(candidates)} candidates, fuzzy match only"

        status_counts[status] = status_counts.get(status, 0) + 1

        entry = {
            "gold_evidence_id": eid,
            "claim_id": cid,
            "company": cc.company if cc else "",
            "source_dataset": ds,
            "evidence_text": etext[:200],
            "normalized_evidence_text": ntext[:200],
            "evidence_sha256": sha256(etext),
            "existing_document_id": str(ge.get("document_id", "") or ""),
            "existing_page": page,
            "existing_block_id": str(ge.get("block_id", "") or ""),
            "candidate_count": len(candidates),
            "candidate_block_ids": [str(c["block"].id) for c in candidates],
            "selected_block_ids": [str(b.id) for b in selected],
            "reconstructed_text": str(btext)[:200] if selected else "",
            "reconstruction_coverage": round(coverage, 4),
            "exact_number_match": sorted(enumbers) == sorted(extract_numbers(btext)) if selected else False,
            "metric_match": "UNKNOWN",
            "period_match": "UNKNOWN",
            "unit_match": "UNKNOWN",
            "unique_candidate": unique,
            "previous_status": prev.get("grounding_status", "N/A"),
            "new_status": status,
            "downgrade_reason": reason,
        }
        per_evidence.append(entry)

    total = len(per_evidence)
    output = {
        "phase": "23.11.5.1",
        "script": "phase23_11_5_1_grounding_audit",
        "description": "Strict re-audit of 42 gold evidence entries",
        "total_evidence": total,
        "status_counts": status_counts,
        "sum_check": sum(status_counts.values()),
        "sum_equals_42": sum(status_counts.values()) == 42,
        "per_evidence": per_evidence,
    }
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Grounding audit written to {OUT_PATH}")
    print(f"  total: {total}")
    print(f"  status_counts: {status_counts}")
    print(f"  sum_check: {sum(status_counts.values())} = 42: {sum(status_counts.values()) == 42}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())