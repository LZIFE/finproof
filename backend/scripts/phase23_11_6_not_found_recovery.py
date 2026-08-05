"""Phase 23.11.6 NOT_FOUND Recovery Diagnostics (Task 3).

For each of the 10 NOT_FOUND gold evidence entries, diagnose the source:
- PDF exists? SHA256?
- page exists? scan image?
- DocumentBlock coverage?
- parser failure?
- paraphrased gold?
- adjacent page / cross-page / table image / other report version?
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import load_canonical_claims
from app.db import SessionLocal
from app.models import DocumentBlock

ART = BACKEND / "artifacts"
OUT_PATH = ART / "gold_contract" / "phase23_11_6_not_found_recovery.json"
AUDIT_PATH = ART / "gold_contract" / "phase23_11_5_1_grounding_audit.json"


def sha256_file(p: Path) -> str:
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    claims, _ = load_canonical_claims()
    claim_by_id = {c.claim_id: c for c in claims}
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    not_found = [p for p in audit["per_evidence"] if p["new_status"] == "NOT_FOUND"]

    # Gather PDF sources
    data_root = BACKEND.parent / "data"
    pdfs = {}
    for ds in ("demo", "holdout"):
        for d in ("source", "tmp", "reports"):
            dd = data_root / ds / d
            if dd.is_dir():
                for f in dd.glob("*.pdf"):
                    pdfs.setdefault(ds, []).append(f)

    session = SessionLocal()
    try:
        all_blocks = session.query(DocumentBlock).order_by(
            DocumentBlock.document_id, DocumentBlock.page_id, DocumentBlock.block_index).all()
    finally:
        session.close()
    blocks_by_page: dict = {}
    for b in all_blocks:
        blocks_by_page.setdefault(b.page_id, []).append(b)
    all_pages = set(blocks_by_page.keys())

    rows = []
    status_counts = {}
    for p in not_found:
        cid = p["claim_id"]
        cc = claim_by_id.get(cid)
        ds = p.get("source_dataset", "demo")
        page = p.get("existing_page")

        # Check PDF sources for this dataset
        ds_pdfs = pdfs.get(ds, [])
        pdf_info = []
        for f in ds_pdfs:
            pdf_info.append({"name": f.name, "sha256": sha256_file(f)[:16], "size": f.stat().st_size})

        page_in_blocks = page in all_pages
        page_blocks = blocks_by_page.get(page, [])
        page_text = " ".join(str(b.text or "") for b in page_blocks)[:300]
        adj_pages = []
        for ap in (page - 1, page + 1):
            if ap in all_pages:
                adj_text = " ".join(str(b.text or "") for b in blocks_by_page.get(ap, []))[:150]
                adj_pages.append({"page": ap, "text": adj_text})

        # Diagnose
        if not ds_pdfs:
            status = "SOURCE_DOCUMENT_MISSING"
            reason = f"no PDF found for dataset {ds}"
        elif not page_in_blocks:
            status = "PARSER_MISSED_CONTENT"
            reason = f"page {page} not covered by DocumentBlocks (parser likely missed)"
        elif not page_blocks:
            status = "PDF_PAGE_REQUIRES_VISUAL_REVIEW"
            reason = f"page {page} exists in blocks index but has no text blocks (likely scan image)"
        else:
            # page has text but gold text not found on it
            gold_txt = p["evidence_text"][:80]
            found_adj = any(gold_txt[:20] in a["text"] for a in adj_pages)
            if found_adj:
                status = "RECOVERED_CANDIDATES_FOUND"
                reason = "gold text found on adjacent page"
            else:
                status = "POSSIBLE_PARAPHRASED_GOLD"
                reason = "page has text but gold text not found (possibly paraphrased or table-only)"

        status_counts[status] = status_counts.get(status, 0) + 1
        rows.append({
            "gold_evidence_id": p["gold_evidence_id"],
            "claim_id": cid,
            "company": cc.company if cc else "",
            "evidence_text": p["evidence_text"][:200],
            "dataset": ds,
            "annotated_page": page,
            "source_pdfs": pdf_info,
            "page_in_blocks_index": page_in_blocks,
            "page_block_count": len(page_blocks),
            "page_parsed_text": page_text,
            "adjacent_pages": adj_pages,
            "recovery_status": status,
            "recovery_reason": reason,
            "recovered_candidates": [],
            "reviewer_decision": "",
            "reviewer_note": "",
            "review_status": "PENDING",
        })

    output = {
        "phase": "23.11.6",
        "script": "phase23_11_6_not_found_recovery",
        "description": "10条NOT_FOUND来源恢复诊断",
        "total": len(rows),
        "status_counts": status_counts,
        "per_item": rows,
    }
    ART.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"NOT_FOUND recovery written to {OUT_PATH}")
    print(f"  total: {len(rows)}")
    print(f"  status_counts: {status_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())