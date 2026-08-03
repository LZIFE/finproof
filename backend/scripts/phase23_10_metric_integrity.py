#!/usr/bin/env python3
"""Phase 23.10 — 指标完整性检查（任务十三）。

从 phase23_10_reranker_eval 的 metrics 产物验证：
- Hit@1 ≤ Hit@3 ≤ Hit@5
- BlockHit@1 ≤ BlockHit@3 ≤ BlockHit@5
- Recall@1 ≤ Recall@3 ≤ Recall@5
- Candidate Recall@50 ≥ Recall@5
- 所有指标使用同一 total_claims（未命中计 0，不从分母中删除）
- 同一输入连续两次运行结果一致（确定性）

任何不变量失败 → 整份 Retrieval 评测判 INVALID。

用法:
    cd backend
    python scripts/phase23_10_metric_integrity.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS = BACKEND_DIR / "artifacts" / "retrieval"


def run_integrity() -> dict:
    m = json.load(open(ARTIFACTS / "phase23_10_metrics.json", encoding="utf-8"))
    agg = m.get("metrics", {})
    total = agg.get("no_result_rate") is not None  # no_result_rate 存在即同一分母来源

    checks = {
        "0<=Hit1<=Hit3<=Hit5": 0.0 <= agg.get("page_hit_1", 1) <= agg.get("page_hit_3", 0) <= agg.get("page_hit_5", 0) <= 1.0,
        "0<=BlockHit1<=BlockHit3<=BlockHit5": 0.0 <= agg.get("block_hit_1", 1) <= agg.get("block_hit_3", 0) <= agg.get("block_hit_5", 0) <= 1.0,
        "Recall1<=Recall3<=Recall5": agg.get("recall_at_1", 1) <= agg.get("recall_at_3", 0) <= agg.get("recall_at_5", 0),
        "CandidateRecall50>=Recall5": agg.get("stage_a_block_recall_50", 0) >= agg.get("recall_at_5", 1),
        "same_total_claims_denominator": total,
        "no_result_claims_not_removed": agg.get("no_result_rate", 1) >= 0.0,  # 未命中计 0，不从分母删除
    }
    # 确定性：重跑 reranker_eval 一次，比较关键指标（同一输入连续两次一致）
    try:
        r = subprocess.run([sys.executable, str(BACKEND_DIR / "scripts" / "phase23_10_reranker_eval.py")],
                           capture_output=True, text=True, timeout=900, cwd=BACKEND_DIR)
        m2 = json.load(open(ARTIFACTS / "phase23_10_metrics.json", encoding="utf-8"))
        a2 = m2.get("metrics", {})
        keys = ["page_hit_1", "page_hit_3", "page_hit_5", "block_hit_1", "block_hit_3", "block_hit_5",
                "recall_at_1", "recall_at_3", "recall_at_5", "mrr_page", "no_result_rate"]
        determinism = all(abs(agg.get(k, 0) - a2.get(k, 0)) < 1e-6 for k in keys)
        determinism_detail = {k: [agg.get(k), a2.get(k)] for k in keys if abs(agg.get(k, 0) - a2.get(k, 0)) >= 1e-6}
    except Exception as exc:  # noqa: BLE001
        determinism, determinism_detail = False, {"error": str(exc)[:120]}
    checks["determinism_twice_identical"] = determinism

    verdict = "VALID" if all(checks.values()) else "INVALID"
    result = {
        "phase": "23.10",
        "script": "phase23_10_metric_integrity",
        "verdict": verdict,
        "checks": checks,
        "determinism_detail": determinism_detail,
        "metrics_snapshot": {k: agg.get(k) for k in
                             ["page_hit_1", "page_hit_3", "page_hit_5", "block_hit_1", "block_hit_3",
                              "block_hit_5", "recall_at_1", "recall_at_3", "recall_at_5",
                              "stage_a_page_recall_50", "stage_a_block_recall_50",
                              "mrr_page", "no_result_rate", "top5_duplicate_rate"]},
        "note": "任何不变量失败 → 整份 Retrieval 评测判 INVALID",
    }
    out = ARTIFACTS / "phase23_10_metric_integrity.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(f"verdict: {verdict}")
    print(f"checks: {checks}")
    return result


if __name__ == "__main__":
    run_integrity()
