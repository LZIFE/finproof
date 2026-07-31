#!/usr/bin/env python3
"""Claim Set Stability 计算（Phase 3.6）。

对多次提取运行的主张做标准化匹配，计算：
- 三次都出现的主张比例（common）
- 至少两次出现的主张比例
- 仅一次出现的主张比例（unstable）
- 高风险主张稳定召回率（三次均召回的高风险金标准比例）
- 数字主张稳定召回率

用法：
  backend/.venv/bin/python scripts/compute_stability.py --runs 11 12 15 --gold <gold_claims.json>

说明：真实 LLM 三次运行尚未执行（配置缺失）；本脚本先在可用运行上演示框架，
结果明确标注模式。产物写入 artifacts/evaluations/claim_extraction/stability/。
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models import Claim, ExtractionRun  # noqa: E402

OUT_ROOT = REPO_ROOT / "artifacts" / "evaluations" / "claim_extraction" / "stability"


def claim_fingerprint(c) -> str:
    """标准化指纹：metric_code + period + reported_value + claim_type。"""
    return "|".join(
        [
            str(c.metric_code or c.metric or ""),
            str(c.period or ""),
            str(c.reported_value if c.reported_value is not None else ""),
            str(c.claim_type or ""),
        ]
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", type=int, required=True)
    ap.add_argument("--gold", default=str(REPO_ROOT / "data" / "demo" / "annotations" / "gold_claims.json"))
    args = ap.parse_args()

    per_run: dict[int, set] = {}
    sys_by_run: dict[int, list[dict]] = {}
    run_meta: dict[int, dict] = {}
    with SessionLocal() as s:
        for run_id in args.runs:
            run = s.get(ExtractionRun, run_id)
            run_meta[run_id] = {
                "mode": run.mode if run else "?",
                "provider": run.provider if run else "?",
                "model": run.model_name if run else "?",
                "prompt": run.prompt_version if run else "?",
            }
            rows = s.query(Claim).filter(Claim.extraction_run_id == run_id).all()
            per_run[run_id] = {claim_fingerprint(c) for c in rows}
            sys_by_run[run_id] = [
                {
                    "id": c.id,
                    "source_text": c.source_text,
                    "normalized_claim": c.normalized_claim,
                    "metric_code": c.metric_code,
                    "metric": c.metric,
                    "reported_value": c.reported_value,
                    "period": c.period,
                    "claim_type": c.claim_type,
                    "claim_nature": c.claim_nature,
                    "entity_name": c.entity_name,
                }
                for c in rows
            ]

    n = len(args.runs)
    counts: Counter = Counter()
    for fp in set().union(*per_run.values()):
        counts[fp] = sum(1 for r in per_run.values() if fp in r)

    total = len(set().union(*per_run.values()))
    common = sum(1 for fp, c in counts.items() if c == n)
    at_least_two = sum(1 for fp, c in counts.items() if c >= 2)
    once_only = sum(1 for fp, c in counts.items() if c == 1)

    # 高风险 / 数字主张稳定召回（对金标准，逐运行匹配计算）
    from app.services.evaluation import claim_eval  # noqa: E402

    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))["claims"]
    high_risk_gold = [g for g in gold if str(g.get("risk_level", "")).upper() in ("HIGH", "CRITICAL")]
    numeric_gold = [g for g in gold if g.get("value") is not None]

    def stable_recall(gold_subset: list[dict]) -> float:
        """金标准主张在全部运行中都被系统主张匹配（>= 阈值）的比例。"""
        if not gold_subset:
            return 0.0
        matched_all = 0
        for g in gold_subset:
            matched_in_all = all(
                any(claim_eval.match_score(g, sysd)[0] >= claim_eval.MATCH_THRESHOLD for sysd in sys_by_run[r])
                for r in args.runs
            )
            if matched_in_all:
                matched_all += 1
        return round(matched_all / len(gold_subset), 4)

    common_fps = {fp for fp, c in counts.items() if c == n}

    modes = {run_meta[r]["mode"] for r in args.runs}
    providers = {run_meta[r]["provider"] for r in args.runs}
    models = {run_meta[r]["model"] for r in args.runs}
    label = (
        f"模式={','.join(sorted(modes))} provider={','.join(sorted(providers))} "
        f"model={','.join(sorted(models))}"
    )
    metrics = {
        "runs": args.runs,
        "mode_label": label,
        "total_claims": total,
        "common_all_runs": round(common / total, 4) if total else 0.0,
        "at_least_two_runs": round(at_least_two / total, 4) if total else 0.0,
        "once_only_unstable": round(once_only / total, 4) if total else 0.0,
        "high_risk_stable_recall": stable_recall(high_risk_gold),
        "numeric_stable_recall": stable_recall(numeric_gold),
        "counts_by_frequency": dict(sorted(counts.items(), key=lambda x: -x[1])),
    }

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "stability_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    common_list = [
        {"fingerprint": fp, "runs": [r for r in args.runs if fp in per_run[r]]}
        for fp, c in counts.items()
        if c == n
    ]
    (OUT_ROOT / "common_claims.json").write_text(
        json.dumps(common_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    unstable_list = [
        {"fingerprint": fp, "run": [r for r in args.runs if fp in per_run[r]][0]}
        for fp, c in counts.items()
        if c == 1
    ]
    (OUT_ROOT / "unstable_claims.json").write_text(
        json.dumps(unstable_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Claim Set Stability 报告",
        "",
        f"- 运行: {args.runs} ｜ {label}",
        f"- 三次都出现比例: {metrics['common_all_runs']} ｜ 至少两次: {metrics['at_least_two_runs']} ｜ 仅一次: {metrics['once_only_unstable']}",
        f"- 高风险主张稳定召回率: {metrics['high_risk_stable_recall']} ｜ 数字主张稳定召回率: {metrics['numeric_stable_recall']}",
        "",
        "> 注：三次运行使用相同输入与参数；AI 模型（assisted/deepseek-v4-flash）低随机性下输出一致属预期，稳定性如实记录。",
    ]
    (OUT_ROOT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if k != "counts_by_frequency"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
