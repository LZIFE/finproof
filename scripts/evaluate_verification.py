#!/usr/bin/env python3
"""Phase 4B.1 核验评测：Verification Accuracy（分组指标）。

对数据集（demo/holdout）全部金标准主张执行核验，
**核验完成后**读取 gold_verifications 计算：
- 分组 Accuracy：Numeric / Growth / Period / Multi Evidence / Semantic
- SUPPORTED precision、REFUTED precision、Overall accuracy、Unknown rate

安全：gold_verifications 仅用于评测对比，不参与核验推理。

用法：
  backend/.venv/bin/python scripts/evaluate_verification.py [--dataset demo|holdout]
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.verification.verification_service import run_verification  # noqa: E402

ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "evaluations" / "verification"

GOLD_VERIFICATION_PATHS = {
    "demo": REPO_ROOT / "data" / "demo" / "annotations" / "gold_verifications.json",
    "holdout": REPO_ROOT / "data" / "holdout" / "annotations" / "gold_verifications.json",
}
GOLD_CLAIM_PATHS = {
    "demo": REPO_ROOT / "data" / "demo" / "annotations" / "gold_claims.json",
    "holdout": REPO_ROOT / "data" / "holdout" / "annotations" / "gold_claims.json",
}

# 主张类型 → 核验类型分组
TYPE_GROUPS = {
    "EXACT_VALUE_CHECK": "numeric",
    "GROWTH_RATE_CHECK": "growth",
    "PERIOD_CHECK": "period",
    "MULTI_EVIDENCE_CHECK": "multi",
    "SEMANTIC_CHECK": "semantic",
}


def evaluate_dataset(dataset: str) -> dict:
    gold_claims = json.loads(GOLD_CLAIM_PATHS[dataset].read_text(encoding="utf-8"))["claims"]
    gold_verifications = {
        v["claim_id"]: v
        for v in json.loads(GOLD_VERIFICATION_PATHS[dataset].read_text(encoding="utf-8"))["verifications"]
    }
    claim_ids = [c["claim_id"] for c in gold_claims]

    with SessionLocal() as s:
        results = run_verification(s, claim_ids)

    group_stats: dict[str, dict] = {}
    total = correct = 0
    n_supported = n_refuted = n_unknown = 0
    supported_correct = refuted_correct = 0
    for r in results:
        d = r.to_dict()
        expected = gold_verifications.get(d["claim_id"], {}).get("expected_verdict")
        if expected is None:
            continue
        total += 1
        ok = d["verification_status"] == expected
        if ok:
            correct += 1
        grp = TYPE_GROUPS.get(d["verification_type"], "other")
        gs = group_stats.setdefault(grp, {"total": 0, "correct": 0})
        gs["total"] += 1
        gs["correct"] += int(ok)
        if d["verification_status"] == "SUPPORTED":
            n_supported += 1
            supported_correct += int(ok)
        elif d["verification_status"] == "REFUTED":
            n_refuted += 1
            refuted_correct += int(ok)
        elif d["verification_status"] in ("UNABLE_TO_DETERMINE", "INSUFFICIENT_EVIDENCE"):
            n_unknown += 1

    group_acc = {
        g: (round(v["correct"] / v["total"], 4) if v["total"] else 0.0)
        for g, v in group_stats.items()
    }
    metrics = {
        "dataset": dataset,
        "claim_count": total,
        "overall_accuracy": round(correct / total, 4) if total else 0.0,
        "supported_precision": round(supported_correct / n_supported, 4) if n_supported else 0.0,
        "refuted_precision": round(refuted_correct / n_refuted, 4) if n_refuted else 0.0,
        "unknown_rate": round(n_unknown / total, 4) if total else 0.0,
        "group_accuracy": group_acc,
        "group_counts": {g: v["total"] for g, v in group_stats.items()},
    }

    out_dir = ARTIFACT_ROOT / dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 核验评测：{dataset}",
        "",
        f"- 主张数: {total} ｜ Overall Accuracy: {metrics['overall_accuracy']}",
        f"- SUPPORTED precision: {metrics['supported_precision']} ｜ REFUTED precision: {metrics['refuted_precision']} ｜ Unknown rate: {metrics['unknown_rate']}",
        f"- 分组 Accuracy: {metrics['group_accuracy']}",
        "",
        "> gold_verifications 仅用于评测对比（核验完成后读取），不参与核验推理。",
    ]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return metrics


def demo_case() -> str:
    """Demo 闭环演示：AI 报告错误句 → 拆解 claim → 财报证据 → 自动计算 → 指出错误原因。"""
    from app.db import SessionLocal

    with SessionLocal() as s:
        results = run_verification(s, ["CLM-004"])
        r = results[0].to_dict()
    cd = r.get("calculation_detail") or {}
    lines = [
        "## Demo 闭环演示（AI 报告错误句）",
        "",
        f"1. **AI 报告错误句**：「归母净利润439.45亿元，同比增长38.02%」",
        f"2. **FinProof 拆解 claim**：CLM-004（yoy_growth_net_profit，期间 2025FY，主张增长率 38.02%）",
        f"3. **找到财报证据**：年报主要会计数据（归母净利润行，当前期 {cd.get('current_value')} 亿元 / 上年同期 {cd.get('previous_value')} 亿元）",
        f"4. **自动计算**：({cd.get('current_value')} − {cd.get('previous_value')}) / {cd.get('previous_value')} = {cd.get('calculated_growth_pp')}%",
        f"5. **指出错误原因**：{r['reason']}",
        f"6. **核验结论**：{r['verification_status']}（置信度 {r['confidence']}）",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["demo", "holdout"], default="demo")
    args = ap.parse_args()

    init_db()
    m = evaluate_dataset(args.dataset)
    print(json.dumps(m, ensure_ascii=False, indent=2))
    print()
    print(demo_case())
    return 0


if __name__ == "__main__":
    sys.exit(main())
