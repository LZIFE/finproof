"""Phase 23.13 — Recall 评估脚本（Recall@10/20/50）

对 43 条 Development Claims 跑 retrieve_for_claim(top_k=50)，
检查 Gold Evidence block（grounding inventory selected_block_id）是否进入候选集合。

输出：
- data/gold_review/phase23_11_6_2/retrieval_recall_report.json

Run: cd backend && PYTHONPATH=. python scripts/phase23_13_recall_eval.py
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
OUT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "retrieval_recall_report.json"


def load_claims() -> list[dict]:
    """合并 demo + holdout 的 43 条 Development Claims（含 entity/metric/period/value）。"""
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
    # claim_id -> 参照 block 集合
    # 用 candidate_block_ids（grounding 审计给出的相关 block 集合，含正文 block）
    # 而非 selected_block_id（可能误选真空单元格，如 CLM-001 的 169 是空 cell，正文在 189）
    gold_by_claim: dict[str, list[str]] = {}
    for p in gi["per_evidence"]:
        cands = [str(b) for b in (p.get("candidate_block_ids") or []) if b]
        if cands:
            gold_by_claim.setdefault(p["claim_id"], []).extend(cands)
    # 去重
    for cid in gold_by_claim:
        gold_by_claim[cid] = list(dict.fromkeys(gold_by_claim[cid]))

    claims = load_claims()
    session = SessionLocal()

    k_values = (10, 20, 50)
    hit_counts = {k: 0 for k in k_values}
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
        # 命中判定：任一 gold block 在 top-K 内
        for k in k_values:
            if any(g in cand_ids[:k] for g in gold_blocks):
                hit_counts[k] += 1
        hit_at = {}
        for k in k_values:
            hit_at[f"recall@{k}"] = any(g in cand_ids[:k] for g in gold_blocks)
        per_claim.append({
            "claim_id": cid,
            "dataset": c.get("dataset"),
            "gold_blocks": gold_blocks,
            "retrieved_count": len(cands),
            "top10_blocks": cand_ids[:10],
            "recall": hit_at,
        })

    session.close()

    report = {
        "phase": "23.13",
        "step": "3_recall_evaluation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_claims_with_gold_block": total,
        "recall": {
            "recall@10": round(hit_counts[10] / total, 4),
            "recall@20": round(hit_counts[20] / total, 4),
            "recall@50": round(hit_counts[50] / total, 4),
        },
        "hit_counts": {f"recall@{k}": hit_counts[k] for k in k_values},
        "per_claim": per_claim,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"total claims with gold block: {total}")
    for k in k_values:
        print(f"  Recall@{k}: {hit_counts[k]}/{total} = {hit_counts[k]/total:.4f}")
    print(f"wrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
