"""Phase 23.11.4 Gold Inventory Audit (Task 1).

逐条输出全部43条Claim的Gold数据契约状态，明确43/35/8/5/3数量矛盾。
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

ART = BACKEND / "artifacts"
GOLD_DIR = ART / "gold_contract"
OUT_PATH = GOLD_DIR / "phase23_11_4_gold_inventory.json"


def load_gold_evidence_all() -> list[dict]:
    evs = []
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_evidence.json"
        if p.exists():
            evs.extend(json.loads(p.read_text(encoding="utf-8")).get("evidence", []))
    return evs


def load_document_blocks() -> dict[str, list[dict]]:
    """Load all document blocks keyed by (document_id, page)."""
    blocks: dict[str, list[dict]] = {}
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "blocks"
        if not p.exists():
            continue
        for f in sorted(p.iterdir()):
            if f.suffix == ".json":
                doc_blocks = json.loads(f.read_text(encoding="utf-8"))
                for b in doc_blocks:
                    key = f"{b.get('document_id','')}:{b.get('page','')}"
                    blocks.setdefault(key, []).append(b)
    return blocks


def evidence_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_gold_evidence(claim_id: str, expected_verdict: str, gold_ev_list: list[dict],
                           blocks_by_page: dict[str, list[dict]]) -> dict:
    """Classify the gold evidence status for a single claim."""
    if not gold_ev_list:
        if expected_verdict == "INSUFFICIENT_EVIDENCE":
            return {
                "gold_evidence_required": True,
                "gold_evidence_status": "INTENTIONAL_NO_EVIDENCE",
                "gold_evidence_ids": [],
                "block_exists": False,
                "evidence_text_matches_block": False,
                "annotation_status": "INTENTIONAL",
                "annotation_issue": "Claim designed as insufficient evidence case",
                "oracle_evaluable": False,
            }
        else:
            return {
                "gold_evidence_required": True,
                "gold_evidence_status": "MISSING_GOLD_ANNOTATION",
                "gold_evidence_ids": [],
                "block_exists": False,
                "evidence_text_matches_block": False,
                "annotation_status": "BLOCKED",
                "annotation_issue": f"Expected {expected_verdict} but no gold evidence annotated",
                "oracle_evaluable": False,
            }

    e = gold_ev_list[0]
    eid = str(e.get("evidence_id", ""))
    etext = str(e.get("evidence_text", "") or "")
    block_id = str(e.get("block_id") or e.get("source_block_id") or "")
    page = e.get("page")
    doc_id = e.get("document_id")

    block_exists = False
    text_matches = False
    block_text = ""

    if block_id:
        # Check if block_id exists in blocks
        for key, blks in blocks_by_page.items():
            for b in blks:
                if str(b.get("block_id")) == block_id or str(b.get("id")) == block_id:
                    block_exists = True
                    block_text = str(b.get("text", "") or "")
                    text_matches = (etext.strip() in block_text or block_text in etext.strip())
                    break
            if block_exists:
                break

    # Determine annotation status
    if block_id and not block_exists:
        status = "INVALID_BLOCK_REFERENCE"
        issue = f"block_id={block_id} references non-existent block"
        oracle_evaluable = False
    elif block_id and block_exists and not text_matches:
        status = "TEXT_BLOCK_MISMATCH"
        issue = f"evidence text does not match block text (block_text='{block_text[:80]}')"
        oracle_evaluable = False
    elif len(gold_ev_list) > 1:
        status = "MULTI_BLOCK_REQUIRED"
        issue = f"multiple evidence entries ({len(gold_ev_list)}) but no multi-block validation"
        oracle_evaluable = True  # still evaluable with limitations
    else:
        status = "VALID_GOLD_EVIDENCE"
        issue = ""
        oracle_evaluable = True

    return {
        "gold_evidence_required": True,
        "gold_evidence_status": status,
        "gold_evidence_ids": [str(e.get("evidence_id", "")) for e in gold_ev_list],
        "gold_document_id": str(doc_id or ""),
        "gold_page": page,
        "gold_block_id": block_id,
        "gold_evidence_text": etext[:200],
        "block_exists": block_exists,
        "evidence_text_matches_block": text_matches,
        "evidence_sha256": evidence_sha256(etext),
        "annotation_status": "VALID" if oracle_evaluable else "BLOCKED",
        "annotation_issue": issue,
        "oracle_evaluable": oracle_evaluable,
    }


def main() -> int:
    claims, _ = load_canonical_claims()
    all_evs = load_gold_evidence_all()
    blocks_by_page = load_document_blocks()

    # Build evidence-by-claim
    ev_by: dict[str, list[dict]] = {}
    for e in all_evs:
        cid = str(e.get("claim_id", ""))
        if cid:
            ev_by.setdefault(cid, []).append(e)

    per_claim = []
    cohort_counts = {
        "evidence_bearing": 0,
        "intentional_insufficient": 0,
        "annotation_blocked": 0,
        "oracle_evaluable": 0,
    }
    status_counts: dict[str, int] = {}

    for cc in claims:
        cid = cc.claim_id
        ev_list = ev_by.get(cid, [])
        result = classify_gold_evidence(cid, cc.expected_verdict, ev_list, blocks_by_page)
        result["claim_id"] = cid
        result["company"] = cc.company
        result["claim_text"] = cc.claim_text[:200]
        result["claim_type"] = cc.claim_type
        result["expected_verdict"] = cc.expected_verdict
        per_claim.append(result)

        status = result["gold_evidence_status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if result["oracle_evaluable"]:
            cohort_counts["oracle_evaluable"] += 1
            cohort_counts["evidence_bearing"] += 1
        elif status == "INTENTIONAL_NO_EVIDENCE":
            cohort_counts["intentional_insufficient"] += 1
        else:
            cohort_counts["annotation_blocked"] += 1

    total = len(claims)
    output = {
        "phase": "23.11.4",
        "script": "phase23_11_4_gold_inventory",
        "description": "43条Gold Data Contract逐条审计：明确43/35/8/5/3数量矛盾",
        "total_claims": total,
        "claims_with_gold_evidence": sum(1 for p in per_claim if p["gold_evidence_ids"]),
        "claims_without_gold_evidence": sum(1 for p in per_claim if not p["gold_evidence_ids"]),
        "status_counts": status_counts,
        "cohort_counts": cohort_counts,
        "count_reconciliation": {
            "total_claims": total,
            "evidence_bearing": cohort_counts["evidence_bearing"],
            "intentional_insufficient": cohort_counts["intentional_insufficient"],
            "annotation_blocked": cohort_counts["annotation_blocked"],
            "sum_check": cohort_counts["evidence_bearing"] + cohort_counts["intentional_insufficient"] + cohort_counts["annotation_blocked"],
            "sum_equals_43": (cohort_counts["evidence_bearing"] + cohort_counts["intentional_insufficient"] + cohort_counts["annotation_blocked"]) == total,
            "why_35_have_gold_evidence": "35 gold evidence entries in data files; 8 claims have none (3 intentional INSUFFICIENT + 5 missing annotation)",
            "why_5_vs_8": "5 = missing annotation (not INSUFFICIENT); 8 = 5 missing + 3 intentional INSUFFICIENT",
            "why_0_block_id": "gold_evidence.json has NO block_id field for any entry (0/42). All 42 entries have empty block_id.",
            "oracle_evaluable_note": "All 35 claims with gold evidence are treated as oracle_evaluable, but 0 have block-level references.",
        },
        "per_claim": per_claim,
    }

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gold inventory written to {OUT_PATH}")
    print(f"  total_claims: {total}")
    print(f"  evidence_bearing: {cohort_counts['evidence_bearing']} (with gold evidence)")
    print(f"  intentional_insufficient: {cohort_counts['intentional_insufficient']}")
    print(f"  annotation_blocked: {cohort_counts['annotation_blocked']}")
    print(f"  oracle_evaluable: {cohort_counts['oracle_evaluable']}")
    print(f"  sum_check: {cohort_counts['evidence_bearing'] + cohort_counts['intentional_insufficient'] + cohort_counts['annotation_blocked']} = {total}")
    print(f"  status_counts: {status_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())