"""Phase 23.21 Task 1 — Gold-to-Evidence 对齐审计

对每条 gold evidence（grounding per_evidence），对比：
- gold source blocks（candidate_block_ids + selected_block_id）
与
- financial evidence object source_blocks（evidence_index_v1.json）

输出状态：
- MATCHED       : gold 非空 block 与某 evidence 对象 source_blocks 有交集（block 级命中）
- PARTIAL_MATCH : 无 block 交集，但同页（gold existing_page == evidence page_number）
- NOT_FOUND     : 既无 block 交集也不同页

保存：backend/artifacts/gold_contract/phase23_21_gold_evidence_alignment_report.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
GI_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_grounding_inventory.json"
IDX_PATH = BACKEND / "artifacts" / "financial_evidence_index" / "evidence_index_v1.json"
OUT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_21_gold_evidence_alignment_report.json"


def main() -> int:
    gi = json.loads(GI_PATH.read_text(encoding="utf-8"))
    idx = json.loads(IDX_PATH.read_text(encoding="utf-8")).get("evidence", [])
    # evidence 索引：block 集合 + 页号
    ev_by_block: dict[str, list[dict]] = {}
    ev_by_page: dict[int, list[dict]] = {}
    for ev in idx:
        for b in ev.get("source_blocks", []):
            ev_by_block.setdefault(str(b), []).append(ev)
        pg = ev.get("page_number")
        if pg:
            ev_by_page.setdefault(pg, []).append(ev)

    report_items = []
    status_counts = {"MATCHED": 0, "PARTIAL_MATCH": 0, "NOT_FOUND": 0}
    for p in gi["per_evidence"]:
        eid = p["gold_evidence_id"]
        gold_blocks = [str(b) for b in (p.get("candidate_block_ids") or []) if b]
        selected = str(p.get("selected_block_id") or "")
        page = p.get("existing_page")

        matched_evs = []
        for gb in gold_blocks:
            for ev in ev_by_block.get(gb, []):
                matched_evs.append(ev)
        # 去重
        seen = set()
        uniq_matched = []
        for ev in matched_evs:
            if ev["id"] not in seen:
                seen.add(ev["id"])
                uniq_matched.append(ev)

        if uniq_matched:
            status = "MATCHED"
        elif page and page in ev_by_page:
            status = "PARTIAL_MATCH"
        else:
            status = "NOT_FOUND"
        status_counts[status] += 1

        report_items.append({
            "gold_evidence_id": eid,
            "claim_id": p.get("claim_id"),
            "gold_source_blocks": gold_blocks,
            "selected_block_id": selected,
            "gold_page": page,
            "alignment_status": status,
            "matched_evidence_objects": [
                {"id": ev["id"], "metric": ev.get("metric"), "page": ev.get("page_number"),
                 "source_blocks": ev.get("source_blocks")}
                for ev in uniq_matched[:5]
            ],
            "matched_object_count": len(uniq_matched),
        })

    out = {
        "phase": "23.21",
        "step": "1_gold_evidence_alignment",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_gold_evidence": len(report_items),
        "status_counts": status_counts,
        "report": report_items,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"total gold evidence: {len(report_items)}")
    print(f"status_counts: {status_counts}")
    print(f"wrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
