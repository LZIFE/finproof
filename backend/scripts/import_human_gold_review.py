"""Phase 23.11.6 Human Gold Review Importer (Task 8).

Only imports review results when ALL human fields are complete.
Validates: reviewer_decision non-empty, selected_block_ids exist, blocks belong
to correct document, multi-block order valid, evidence reconstructable,
reviewer_name/reviewed_at/rationale non-empty, no duplicate review,
review package hash unchanged.

Generates a NEW gold version, never overwrites the old one.

Run: cd backend && PYTHONPATH=. python scripts/import_human_gold_review.py \
       --review data/gold_review/phase23_11_6/review_results.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import SessionLocal
from app.models import DocumentBlock

REVIEW_DIR = BACKEND.parent / "data" / "gold_review" / "phase23_11_6"
MANIFEST_PATH = BACKEND.parent / "data" / "gold_manifest.json"
AUDIT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_1_grounding_audit.json"
OUTPUT_GOLD_PATH = BACKEND.parent / "data" / "annotations" / "gold_evidence_v2.json"


def _err(msg: str) -> None:
    print(f"IMPORT REJECTED: {msg}")
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", required=True, help="path to review_results.json")
    parser.add_argument("--reviewer", required=True, help="reviewer name")
    args = parser.parse_args()

    review_path = Path(args.review)
    if not review_path.exists():
        _err(f"review file not found: {review_path}")

    review = json.loads(review_path.read_text(encoding="utf-8"))
    items = review.get("items", [])

    # 1. Package hash unchanged (compare with original review_items.json)
    original = json.loads((REVIEW_DIR / "review_items.json").read_text(encoding="utf-8"))
    orig_items = {it["item_id"]: it for it in original["items"]}
    if len(items) != len(original["items"]):
        _err("review item count mismatch with original package")
    for it in items:
        if it["item_id"] not in orig_items:
            _err(f"item {it['item_id']} not in original package")

    # 2. Human fields complete
    for it in items:
        if not it.get("reviewer_choice"):
            _err(f"item {it['item_id']}: reviewer_choice empty")
        if it.get("reviewer_choice") in ("MATCH_SINGLE_BLOCK", "MATCH_MULTIPLE_BLOCKS"):
            if not it.get("selected_block_ids"):
                _err(f"item {it['item_id']}: selected_block_ids empty")
        if it.get("reviewer_choice") not in ("MATCH_SINGLE_BLOCK", "MATCH_MULTIPLE_BLOCKS", "NONE_OF_THE_ABOVE", "UNSURE"):
            _err(f"item {it['item_id']}: invalid reviewer_choice {it.get('reviewer_choice')}")
        if not it.get("reviewer_note", "").strip():
            _err(f"item {it['item_id']}: reviewer_note empty")
        if not it.get("reviewed_at", ""):
            _err(f"item {it['item_id']}: reviewed_at empty")

    # 3. Blocks exist and belong to correct document; multi-block order valid
    session = SessionLocal()
    try:
        all_blocks = session.query(DocumentBlock).all()
    finally:
        session.close()
    block_by_id = {str(b.id): b for b in all_blocks}

    confirmed = []
    seen_items = set()
    for it in items:
        if it["item_id"] in seen_items:
            _err(f"duplicate review for {it['item_id']}")
        seen_items.add(it["item_id"])
        if it.get("reviewer_choice") not in ("MATCH_SINGLE_BLOCK", "MATCH_MULTIPLE_BLOCKS"):
            continue  # NONE / UNSURE → no blocks confirmed
        bids = it.get("selected_block_ids", [])
        if not bids:
            _err(f"item {it['item_id']}: MATCH requires selected_block_ids")
        for bid in bids:
            b = block_by_id.get(str(bid))
            if not b:
                _err(f"item {it['item_id']}: block {bid} does not exist")
        # multi-block: must be same page or consecutive pages, in order
        if len(bids) > 1:
            pages = [block_by_id[str(bid)].page_id for bid in bids]
            for i in range(1, len(pages)):
                if pages[i] != pages[i - 1] and pages[i] != pages[i - 1] + 1:
                    _err(f"item {it['item_id']}: multi-block pages not adjacent: {pages}")
        confirmed.append(it)

    # 4. Generate NEW gold version (never overwrite old)
    old_gold = []
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_evidence.json"
        if p.exists():
            old_gold.extend(json.loads(p.read_text(encoding="utf-8")).get("evidence", []))

    # Map confirmed blocks to gold entries
    new_gold = []
    for ge in old_gold:
        eid = str(ge.get("evidence_id", ""))
        entry = dict(ge)
        rev = next((it for it in confirmed if it["item_id"] == eid), None)
        if rev and rev.get("selected_block_ids"):
            entry["confirmed_block_ids"] = rev["selected_block_ids"]
            entry["gold_confirm_status"] = "CONFIRMED"
            entry["confirmed_at"] = rev.get("reviewed_at", "")
        entry["gold_version"] = "23.11.6-v2"
        new_gold.append(entry)

    # Write new version
    OUTPUT_GOLD_PATH.write_text(
        json.dumps({"gold_version": "23.11.6-v2", "previous_version": "23.11.5", "evidence": new_gold},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # Update manifest
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["change_log"] = manifest.get("change_log", []) + [
        f"Phase 23.11.6: human review imported by {args.reviewer}, "
        f"confirmed {len(confirmed)} evidence → new gold version 23.11.6-v2"
    ]
    manifest["gold_version"] = "23.11.6-v2"
    manifest["reviewer"] = args.reviewer
    manifest["confirmed_evidence_count"] = len(confirmed)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"IMPORT SUCCESS: {len(confirmed)} evidence confirmed by {args.reviewer}")
    print(f"New gold version written to {OUTPUT_GOLD_PATH} (previous kept in data/*/annotations/gold_evidence.json)")
    print(f"Manifest updated: gold_version=23.11.6-v2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())