"""Phase 23.15 Step 5 — 三级检索 Recall 评估脚本

对 43 条 Development Claims 跑 retrieve_for_claim(top_k=50)，评估：

1. Candidate Recall@50：Gold Evidence block（grounding candidate_block_ids）是否进入候选池
2. Section Recall：Gold Evidence 所在页是否属于 claim 路由的目标章节页集合
3. Table Recall：Gold Evidence 所在页是否被识别为表格页（且属于目标 table_type）

目标：Candidate Recall@50 >= 0.8

输出：
- data/gold_review/phase23_11_6_2/retrieval_recall_report_v3.json

Run: cd backend && PYTHONPATH=. python scripts/phase23_15_recall_eval.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

GROUNDING_INVENTORY = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_grounding_inventory.json"
OUT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "retrieval_recall_report_v3.json"


def load_claims() -> list[dict]:
    claims = []
    for ds in ("demo", "holdout"):
        p = REPO_ROOT / "data" / ds / "annotations" / "gold_claims.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        for c in data.get("claims", []):
            c["dataset"] = ds
            claims.append(c)
    return claims


def main() -> int:
    from app.db import SessionLocal
    from app.services.evidence_retrieval.claim_routing import route_sections_for_claim
    from app.services.evidence_retrieval.service import retrieve_for_claim
    from app.services.evidence_retrieval.section_index import (
        page_section_types,
        table_pages_for_types,
        target_pages_for_claim,
    )

    gi = json.loads(GROUNDING_INVENTORY.read_text(encoding="utf-8"))
    # claim_id -> gold 参照 block 集合（candidate_block_ids 含正文 block）
    gold_by_claim: dict[str, list[str]] = {}
    # claim_id -> gold evidence 所在物理页
    page_by_claim: dict[str, list[int]] = {}
    for p in gi["per_evidence"]:
        cands = [str(b) for b in (p.get("candidate_block_ids") or []) if b]
        if cands:
            gold_by_claim.setdefault(p["claim_id"], []).extend(cands)
        pg = p.get("existing_page")
        if pg:
            page_by_claim.setdefault(p["claim_id"], []).append(pg)
    for cid in gold_by_claim:
        gold_by_claim[cid] = list(dict.fromkeys(gold_by_claim[cid]))

    claims = load_claims()
    session = SessionLocal()

    hit_cand = 0
    hit_section = 0
    hit_table = 0
    total = 0
    per_claim = []

    for c in claims:
        cid = c.get("claim_id") or ""
        gold_blocks = gold_by_claim.get(cid, [])
        gold_pages = page_by_claim.get(cid, [])
        if not gold_blocks:
            continue
        total += 1
        # 路由目标章节
        routing = route_sections_for_claim(c)
        target_secs = routing["sections"]
        # claim 关联文档（demo 美的集团 doc=1，holdout 五粮液 doc=3 或 1——按 entity 反查取首个）
        from app.db import SessionLocal as _SL
        from app.services.evidence_retrieval.service import filter_documents

        docs = filter_documents(session, c)
        cands = retrieve_for_claim(session, c, top_k=50)
        cand_ids = [str(x["block_id"]) for x in cands]

        # 1) Candidate Recall@50
        in_50 = any(g in cand_ids for g in gold_blocks)

        # 2) Section Recall：gold 页 ∈ 目标章节页集合（任意关联文档）
        section_hit = False
        for d in docs:
            tpages = target_pages_for_claim(d.id, target_secs)
            if any(pg in tpages for pg in gold_pages):
                section_hit = True
                break

        # 3) Table Recall：gold 页 ∈ 目标章节表格页集合
        table_hit = False
        for d in docs:
            tpages = table_pages_for_types(d.id, target_secs)
            if any(pg in tpages for pg in gold_pages):
                table_hit = True
                break

        if in_50:
            hit_cand += 1
        if section_hit:
            hit_section += 1
        if table_hit:
            hit_table += 1

        per_claim.append({
            "claim_id": cid,
            "dataset": c.get("dataset"),
            "gold_blocks": gold_blocks,
            "gold_pages": gold_pages,
            "target_sections": target_secs,
            "routing_rule": routing["rule"],
            "candidate_recall@50": in_50,
            "section_recall": section_hit,
            "table_recall": table_hit,
        })

    session.close()

    report = {
        "phase": "23.15",
        "step": "5_recall_evaluation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_claims_with_gold_block": total,
        "candidate_recall": {
            "recall@50": round(hit_cand / total, 4),
            "hit_count": hit_cand,
        },
        "section_recall": {
            "recall": round(hit_section / total, 4),
            "hit_count": hit_section,
        },
        "table_recall": {
            "recall": round(hit_table / total, 4),
            "hit_count": hit_table,
        },
        "target": {"candidate_recall@50": 0.8},
        "target_met": {"candidate_recall@50": hit_cand / total >= 0.8},
        "per_claim": per_claim,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"total claims with gold block: {total}")
    print(f"  Candidate Recall@50: {hit_cand}/{total} = {hit_cand/total:.4f} (target >= 0.8)")
    print(f"  Section Recall:      {hit_section}/{total} = {hit_section/total:.4f}")
    print(f"  Table Recall:        {hit_table}/{total} = {hit_table/total:.4f}")
    print(f"wrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
