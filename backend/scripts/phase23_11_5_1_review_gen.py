"""Phase 23.11.5.1 Human Review File Generator (Task 6)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import load_canonical_claims
from app.db import SessionLocal
from app.models import DocumentBlock

REVIEW_OUT = BACKEND.parent / "data" / "gold_review" / "phase23_11_5_1_review.json"
AUDIT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_1_grounding_audit.json"


def main() -> int:
    claims, _ = load_canonical_claims()
    claim_by_id = {c.claim_id: c for c in claims}
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    session = SessionLocal()
    try:
        all_blocks = session.query(DocumentBlock).order_by(
            DocumentBlock.document_id, DocumentBlock.page_id, DocumentBlock.block_index).all()
    finally:
        session.close()
    block_by_id = {str(b.id): b for b in all_blocks}
    blocks_by_page: dict = {}
    for b in all_blocks:
        blocks_by_page.setdefault(b.page_id, []).append(b)

    review_items = []
    for p in audit["per_evidence"]:
        st = p["new_status"]
        if st.startswith("AUTO_CONFIRMED"):
            continue  # no review needed
        cid = p["claim_id"]
        cc = claim_by_id.get(cid)
        cand_ids = p.get("candidate_block_ids", []) or []
        cand_texts, contexts = [], []
        for bid in cand_ids:
            b = block_by_id.get(bid)
            cand_texts.append(str(b.text or "")[:150] if b else "")
            if b:
                page_blocks = blocks_by_page.get(b.page_id, [])
                idx = next((i for i, x in enumerate(page_blocks) if str(x.id) == bid), None)
                before = str(page_blocks[idx - 1].text or "")[:80] if (idx is not None and idx > 0) else ""
                after = str(page_blocks[idx + 1].text or "")[:80] if (idx is not None and idx < len(page_blocks) - 1) else ""
                contexts.append({"before": before, "after": after})
        review_items.append({
            "gold_evidence_id": p["gold_evidence_id"],
            "claim_id": cid,
            "claim_text": str(cc.claim_text if cc else "")[:200],
            "expected_verdict": str(cc.expected_verdict if cc else ""),
            "original_gold_evidence": p.get("evidence_text", "")[:200],
            "candidate_document_id": str(p.get("selected_document_id", "") or ""),
            "candidate_page": p.get("existing_page"),
            "candidate_block_ids": cand_ids,
            "candidate_texts": cand_texts,
            "context_before": [c["before"] for c in contexts],
            "context_after": [c["after"] for c in contexts],
            "candidate_scores": [],
            "ambiguity_reason": p.get("downgrade_reason", ""),
            "new_status": st,
            "reviewer_selected_block_ids": [],
            "reviewer_decision": "",
            "reviewer_rationale": "",
            "reviewer_name": "",
            "reviewed_at": "",
            "review_status": "PENDING_REVIEW",
        })

    out = {
        "phase": "23.11.5.1",
        "description": "待人工审核Gold Evidence（Agent不得填写reviewer字段）",
        "total": len(review_items),
        "items": review_items,
    }
    REVIEW_OUT.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    empty_ok = all(
        it["reviewer_name"] == "" and it["reviewer_decision"] == ""
        and it["reviewed_at"] == "" and it["reviewer_selected_block_ids"] == []
        for it in review_items
    )
    print(f"Review file: {REVIEW_OUT} ({len(review_items)} items)")
    print(f"Reviewer fields all empty: {empty_ok}")
    print("By status:", dict(Counter(it["new_status"] for it in review_items)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())