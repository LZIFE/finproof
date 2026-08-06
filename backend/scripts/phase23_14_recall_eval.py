"""Phase 23.14 — Recall 评估脚本（Recall@50 + Evidence Window Recall）

对 43 条 Development Claims 跑 retrieve_for_claim(top_k=50)，
检查 Gold Evidence block（grounding inventory candidate_block_ids）是否进入候选集合。

新增 Evidence Window Recall：gold block 是否被某个候选块的 Evidence Window 覆盖
（同页 ±3 块 / 同表 y-range 扩展，即候选块与 gold block 相邻）。

输出：
- data/gold_review/phase23_11_6_2/retrieval_recall_report_v2.json

Run: cd backend && PYTHONPATH=. python scripts/phase23_14_recall_eval.py
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
OUT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "retrieval_recall_report_v2.json"


def load_claims() -> list[dict]:
    """合并 demo + holdout 的 43 条 Development Claims。"""
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
    from app.services.evidence_retrieval.service import retrieve_for_claim

    gi = json.loads(GROUNDING_INVENTORY.read_text(encoding="utf-8"))
    # claim_id -> 参照 block 集合（candidate_block_ids，含正文 block，避免 selected 误指真空格）
    gold_by_claim: dict[str, list[str]] = {}
    for p in gi["per_evidence"]:
        cands = [str(b) for b in (p.get("candidate_block_ids") or []) if b]
        if cands:
            gold_by_claim.setdefault(p["claim_id"], []).extend(cands)
    for cid in gold_by_claim:
        gold_by_claim[cid] = list(dict.fromkeys(gold_by_claim[cid]))

    claims = load_claims()
    session = SessionLocal()

    hit_50 = 0
    hit_window = 0
    total = 0
    per_claim = []

    for c in claims:
        cid = c.get("claim_id") or ""
        gold_blocks = gold_by_claim.get(cid, [])
        if not gold_blocks:
            continue
        total += 1
        cands = retrieve_for_claim(session, c, top_k=50)
        cand_ids = [str(x["block_id"]) for x in cands]
        # Recall@50：任一 gold block 在候选池
        in_50 = any(g in cand_ids for g in gold_blocks)
        # Evidence Window Recall：gold block 与某个候选块同页且 block_index 差 <= 3（或同 y-range）
        in_window = False
        if not in_50:
            # 候选块 → (page_id, block_index, y0)
            for x in cands:
                if in_window:
                    break
                pid = x.get("page_id")
                for g in gold_blocks:
                    row = _block_info(session, g)
                    if row and row[0] == pid and abs(row[1] - (x.get("_block_index") or -999)) <= 3:
                        in_window = True
                        break
        if in_50:
            hit_50 += 1
        if in_50 or in_window:
            hit_window += 1
        per_claim.append({
            "claim_id": cid,
            "dataset": c.get("dataset"),
            "gold_blocks": gold_blocks,
            "retrieved_count": len(cands),
            "recall@50": in_50,
            "evidence_window_recall": in_50 or in_window,
        })

    session.close()

    report = {
        "phase": "23.14",
        "step": "5_recall_evaluation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_claims_with_gold_block": total,
        "candidate_recall": {
            "recall@50": round(hit_50 / total, 4),
            "hit_count": hit_50,
        },
        "evidence_window_recall": {
            "recall": round(hit_window / total, 4),
            "hit_count": hit_window,
        },
        "target": {"recall@50": 0.8, "evidence_window_recall": 0.8},
        "target_met": {
            "recall@50": hit_50 / total >= 0.8,
            "evidence_window_recall": hit_window / total >= 0.8,
        },
        "per_claim": per_claim,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"total claims with gold block: {total}")
    print(f"  Recall@50: {hit_50}/{total} = {hit_50/total:.4f} (target >= 0.8)")
    print(f"  Evidence Window Recall: {hit_window}/{total} = {hit_window/total:.4f} (target >= 0.8)")
    print(f"wrote: {OUT_PATH}")
    return 0


def _block_info(session, block_id: str):
    """返回 (page_id, block_index, y0) 或 None。"""
    from app.models import DocumentBlock

    try:
        bid = int(block_id)
    except (TypeError, ValueError):
        return None
    b = session.query(DocumentBlock).filter(DocumentBlock.id == bid).first()
    if b is None:
        return None
    return (b.page_id, b.block_index or 0, b.y0 or 0.0)


if __name__ == "__main__":
    sys.exit(main())
