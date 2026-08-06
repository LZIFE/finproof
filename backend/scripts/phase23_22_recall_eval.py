"""Phase 23.22 Task 3/4 — Recall 评估（Block Recall + Financial Fact Recall@10/@50）

对 30 条有 gold block 参照的 claim：
1. Block Recall：gold grounding blocks 是否进入 retrieve_for_claim top-K
2. Financial Fact Recall：retrieve_financial_evidence 返回的 evidence 对象中，
   是否有对象的事实（current/previous/growth + metric 家族）与 gold evidence 事实匹配

输出：data/gold_review/phase23_11_6_2/retrieval_recall_report_v10.json
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
GI_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_grounding_inventory.json"
OUT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "retrieval_recall_report_v10.json"


def _gold_numbers(text: str):
    out = []
    for m in re.finditer(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", text or ""):
        try:
            v = float(m.group(0).replace(",", ""))
        except ValueError:
            continue
        if not (1900 <= v <= 2100):
            out.append(v)
    return out


def _fact_hit(ev: dict, gold_nums: list[float]) -> bool:
    """evidence 对象的 current/previous 与 gold 数值（前两个非年份数）匹配。"""
    if not gold_nums:
        return False
    ev_cur = ev.get("current_value")
    ev_prev = ev.get("previous_value")
    g_cur = gold_nums[0]
    g_prev = gold_nums[1] if len(gold_nums) >= 2 else None
    cur_ok = ev_cur is not None and abs(ev_cur - g_cur) / max(1, abs(g_cur)) < 0.005
    if g_prev is None:
        return cur_ok
    prev_ok = ev_prev is not None and abs(ev_prev - g_prev) / max(1, abs(g_prev)) < 0.005
    return cur_ok and prev_ok


def main() -> int:
    from app.db import SessionLocal
    from app.services.evidence_retrieval.claim_routing import route_sections_for_claim
    from app.services.evidence_retrieval.evidence_retriever import retrieve_financial_evidence
    from app.services.evidence_retrieval.service import retrieve_for_claim

    gi = json.loads(GI_PATH.read_text(encoding="utf-8"))
    # claim_id -> gold blocks + gold numbers（fact 参照）
    gold_by_claim: dict[str, dict] = {}
    for p in gi["per_evidence"]:
        cid = p["claim_id"]
        d = gold_by_claim.setdefault(cid, {"blocks": [], "numbers": [], "text": ""})
        d["blocks"].extend(str(b) for b in (p.get("candidate_block_ids") or []) if b)
        d["numbers"].extend(_gold_numbers(p.get("evidence_text") or ""))
        d["text"] = p.get("evidence_text") or ""
    for cid in gold_by_claim:
        gold_by_claim[cid]["blocks"] = list(dict.fromkeys(gold_by_claim[cid]["blocks"]))
        gold_by_claim[cid]["numbers"] = list(dict.fromkeys(gold_by_claim[cid]["numbers"]))

    claims = []
    for ds in ("demo", "holdout"):
        data = json.load(open(REPO_ROOT / "data" / ds / "annotations" / "gold_claims.json"))
        for c in data.get("claims", []):
            claims.append(c)

    session = SessionLocal()
    ks = (10, 50)
    block_hits = {k: 0 for k in ks}
    fact_hits = {k: 0 for k in ks}
    total = 0
    for c in claims:
        cid = c.get("claim_id") or ""
        g = gold_by_claim.get(cid)
        if not g or not g["blocks"]:
            continue
        total += 1
        # Block Recall
        cands = retrieve_for_claim(session, c, top_k=50)
        ids = [str(x["block_id"]) for x in cands]
        for k in ks:
            if any(b in ids[:k] for b in g["blocks"]):
                block_hits[k] += 1
        # Financial Fact Recall（fact-level）
        r = route_sections_for_claim(c)
        evs = retrieve_financial_evidence(c, target_sections=r["sections"], top_k=50,
                                          grounding_blocks=set(g["blocks"]))
        for k in ks:
            if any(_fact_hit(e, g["numbers"]) for e in evs[:k]):
                fact_hits[k] += 1
    session.close()

    out = {
        "phase": "23.22",
        "step": "3_4_recall_eval",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "block_recall": {f"block_recall@{k}": round(block_hits[k] / total, 4) for k in ks},
        "financial_fact_recall": {f"fact_recall@{k}": round(fact_hits[k] / total, 4) for k in ks},
        "before_23_21": {"block_recall@50": 0.30, "block_recall@10": 0.1333,
                         "evidence_recall@50": 0.10, "evidence_recall@10": 0.10},
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"total={total}")
    for k in ks:
        print(f"  Block Recall@{k}: {block_hits[k]}/{total} = {block_hits[k]/total:.4f}")
        print(f"  Financial Fact Recall@{k}: {fact_hits[k]}/{total} = {fact_hits[k]/total:.4f}")
    print(f"wrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
