"""Phase 23.11.5 Gold Evidence Grounding Inventory (Task 2).

Maps 42 gold evidence entries to DocumentBlock records by page and text.
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
OUT_PATH = GOLD_DIR / "phase23_11_5_grounding_inventory.json"


def normalize_text(t: str) -> str:
    """Normalize text for comparison: strip whitespace, collapse spaces, remove punct."""
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'[,，、　]', '', t)
    return t


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

    # Load all document blocks from DB
    session = SessionLocal()
    try:
        all_blocks = session.query(DocumentBlock).order_by(DocumentBlock.document_id, DocumentBlock.page_id, DocumentBlock.block_index).all()
    finally:
        session.close()

    # Index blocks by page_id
    blocks_by_page: dict[int, list] = {}
    for b in all_blocks:
        blocks_by_page.setdefault(b.page_id, []).append(b)

    per_evidence = []
    status_counts = {}

    for ge in gold_evs:
        eid = ge.get("evidence_id", "?")
        cid = ge.get("claim_id", "")
        cc = claim_by_id.get(cid)
        etext = str(ge.get("evidence_text", "") or "")
        page = ge.get("page")
        ds = ge.get("_dataset", "?")
        norm_text = normalize_text(etext)

        # Find candidate blocks on the same page
        page_blocks = blocks_by_page.get(page, [])
        candidate_blocks = []
        exact_matches = []
        norm_matches = []
        fuzzy_matches = []
        table_context_matches = []
        txt_matches = []

        for b in page_blocks:
            btext = str(b.text or "")
            b_norm = normalize_text(btext)
            score = 0
            # Exact match
            if etext.strip() == btext.strip():
                exact_matches.append(b)
                txt_matches.append(b)
                score = 1.0
            # Normalized match
            elif norm_text == b_norm:
                norm_matches.append(b)
                txt_matches.append(b)
                score = 0.9
            # Contains/contained
            elif etext.strip() in btext or btext.strip() in etext:
                fuzzy_matches.append(b)
                txt_matches.append(b)
                score = 0.7
            # Partial overlap
            elif len(norm_text) > 10 and len(b_norm) > 10:
                common = len(set(norm_text.split()) & set(b_norm.split()))
                total = max(len(set(norm_text.split())), 1)
                ratio = common / total
                if ratio > 0.5:
                    fuzzy_matches.append(b)
                    txt_matches.append(b)
                    score = 0.5

            if score > 0:
                candidate_blocks.append({
                    "block_id": b.id,
                    "document_id": b.document_id,
                    "page_id": b.page_id,
                    "text": btext[:150],
                    "match_score": round(score, 2),
                })

        # Determine grounding status
        if exact_matches:
            selected = exact_matches[0]
            status = "EXACT_BLOCK_MATCH"
            method = "exact_text_match"
            match_score = 1.0
        elif norm_matches:
            selected = norm_matches[0]
            status = "NORMALIZED_BLOCK_MATCH"
            method = "normalized_text_match"
            match_score = 0.9
        elif len(fuzzy_matches) == 1:
            selected = fuzzy_matches[0]
            status = "MULTI_BLOCK_MATCH" if len(fuzzy_matches) > 1 else "PAGE_MATCH_BLOCK_AMBIGUOUS"
            method = "fuzzy_text_match"
            match_score = 0.7
        elif len(fuzzy_matches) > 1:
            selected = fuzzy_matches[0]
            status = "MULTI_BLOCK_MATCH"
            method = "fuzzy_multi_candidate"
            match_score = 0.5
        elif page_blocks:
            selected = page_blocks[0]
            status = "PAGE_MATCH_BLOCK_AMBIGUOUS"
            method = "page_only"
            match_score = 0.3
        else:
            selected = None
            status = "DOCUMENT_NOT_FOUND"
            method = "no_blocks_on_page"
            match_score = 0.0

        status_counts[status] = status_counts.get(status, 0) + 1

        entry = {
            "gold_evidence_id": eid,
            "claim_id": cid,
            "company": cc.company if cc else "",
            "source_dataset": ds,
            "evidence_text": etext[:200],
            "normalized_evidence_text": norm_text[:200],
            "existing_document_id": str(ge.get("document_id", "")),
            "existing_page": page,
            "existing_block_id": str(ge.get("block_id", "") or ge.get("source_block_id", "") or ""),
            "candidate_document_ids": list(set(str(b["document_id"]) for b in candidate_blocks)) or [],
            "candidate_pages": list(set(b["page_id"] for b in candidate_blocks)) or [],
            "candidate_block_ids": list(set(str(b["block_id"]) for b in candidate_blocks)) or [],
            "exact_text_matches": len(exact_matches),
            "normalized_text_matches": len(norm_matches),
            "fuzzy_text_matches": len(fuzzy_matches),
            "table_context_matches": 0,
            "selected_document_id": str(selected.document_id) if selected else "",
            "selected_page": selected.page_id if selected else None,
            "selected_block_id": str(selected.id) if selected else "",
            "match_method": method,
            "match_score": match_score,
            "ambiguity_count": len(candidate_blocks),
            "grounding_status": status,
            "human_review_required": status in ("PAGE_MATCH_BLOCK_AMBIGUOUS", "DOCUMENT_NOT_FOUND"),
        }
        per_evidence.append(entry)

    total = len(per_evidence)
    output = {
        "phase": "23.11.5",
        "script": "phase23_11_5_grounding_inventory",
        "description": "42条Gold Evidence逐条匹配到真实DocumentBlock",
        "total_evidence": total,
        "status_counts": status_counts,
        "sum_check": sum(status_counts.values()),
        "sum_equals_42": sum(status_counts.values()) == 42,
        "per_evidence": per_evidence,
    }

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Grounding inventory written to {OUT_PATH}")
    print(f"  total_evidence: {total}")
    print(f"  status_counts: {status_counts}")
    print(f"  sum_check: {sum(status_counts.values())} = 42: {sum(status_counts.values()) == 42}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())