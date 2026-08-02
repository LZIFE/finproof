"""Phase 11 · Demo — 金融 AI 可信度评测基准（Financial AIBenchmark System）。

任务书 §7 Demo 要求：
- 至少 50 条金融测试案例
- 展示 FinProof 发现 AI 幻觉

流程：
  Dataset（50 条预置案例）
    ↓ Evaluator
  FinProof vs Baseline LLM
    ↓ Metrics
  Accuracy/Precision/Recall/F1/Coverage/RiskDetectionRate
    ↓ Compare
  FinProof 增益

设计约束（任务书）：
- 不修改已有核心模块；Benchmark 作为新增层。

运行：
    cd backend
    python -m scripts.phase11_demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保可以 import app.*
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.benchmark.dataset import (  # noqa: E402
    get_error_distribution,
    get_seed_cases,
)
from app.services.benchmark.evaluator import (  # noqa: E402
    MODEL_BASELINE_LLM,
    MODEL_FINPROOF,
    run_benchmark,
    save_report,
)


def run_demo() -> dict:
    init_db()
    with SessionLocal() as s:
        # Step 1: Dataset 概况
        cases = get_seed_cases()
        error_dist = get_error_distribution(cases)

        # Step 2: 运行评测
        report = run_benchmark(
            s,
            dataset_name=None,
            models=[MODEL_FINPROOF, MODEL_BASELINE_LLM],
            use_seed=True,
        )
        report = save_report(s, report)
        return {
            "dataset": {
                "name": report.dataset_name,
                "count": report.total_cases,
                "error_distribution": error_dist,
            },
            "report": report.to_dict(),
        }


def _print_report(result: dict) -> None:
    print("=" * 78)
    print("FinProof Phase 11 · Financial AIBenchmark System")
    print("=" * 78)

    dataset = result["dataset"]
    print(f"\n--- Dataset ---")
    print(f"  Name      : {dataset['name']}")
    print(f"  Count     : {dataset['count']}")
    print(f"  Error Distribution:")
    for cat, n in dataset["error_distribution"].items():
        print(f"    - {cat}: {n} 条")

    report = result["report"]
    print(f"\n--- Run ---")
    print(f"  Run ID    : {report['run_id']}")
    print(f"  Models    : {', '.join(report['models'])}")

    finproof = next(m for m in report["model_results"] if m["model"] == MODEL_FINPROOF)
    baseline = next(m for m in report["model_results"] if m["model"] == MODEL_BASELINE_LLM)

    print(f"\n--- Evaluation Metrics（FinProof vs Baseline LLM）---")
    fm = finproof["metrics"]
    bm = baseline["metrics"]
    print(f"  {'指标':<30} {'FinProof':>12} {'Baseline':>12} {'增益':>10}")
    print(f"  {'-'*30} {'-'*12} {'-'*12} {'-'*10}")
    for k in ["accuracy", "precision", "recall", "f1", "evidence_coverage", "risk_detection_rate"]:
        fv = fm[k]
        bv = bm[k]
        gain = report["comparison"].get(f"{k}_gain", 0.0)
        gain_str = f"+{gain:.3f}" if gain >= 0 else f"{gain:.3f}"
        print(f"  {k:<30} {fv:>12.3f} {bv:>12.3f} {gain_str:>10}")

    print(f"\n--- Recall by Category（分错误类别召回率）---")
    for cat, fr in fm["recall_by_category"].items():
        br = bm["recall_by_category"].get(cat, 0.0)
        print(f"  {cat:<30} FinProof {fr:.3f} vs Baseline {br:.3f}")

    print(f"\n--- Model Comparison ---")
    comp = report["comparison"]
    print(f"  Accuracy 增益            : {comp['accuracy_gain']:+.3f}")
    print(f"  Precision 增益           : {comp['precision_gain']:+.3f}")
    print(f"  Recall 增益              : {comp['recall_gain']:+.3f}")
    print(f"  F1 增益                  : {comp['f1_gain']:+.3f}")
    print(f"  Evidence Coverage 增益   : {comp['evidence_coverage_gain']:+.3f}")
    print(f"  Risk Detection Rate 增益 : {comp['risk_detection_rate_gain']:+.3f}")

    print(f"\n--- FinProof 检测到的 AI 幻觉（逐案例摘录，前 10 条）---")
    detected = [c for c in finproof["case_results"] if c["detected_error"]]
    print(f"  共检测到 {len(detected)} 条错误（FinProof）")
    for c in detected[:10]:
        print(f"  · [{c['case_id']}] {c['predicted_risk_type']} {c['predicted_risk_score']}")
        print(f"      预测: {c['predicted_result']} | 证据覆盖: {(c['evidence_coverage'] * 100):.0f}%")
        print(f"      {c['response_text']}")

    print(f"\n--- JSON Output (excerpt) ---")
    excerpt = {
        "run_id": report["run_id"],
        "total_cases": report["total_cases"],
        "finproof": {
            "accuracy": fm["accuracy"],
            "precision": fm["precision"],
            "recall": fm["recall"],
            "f1": fm["f1"],
            "evidence_coverage": fm["evidence_coverage"],
            "risk_detection_rate": fm["risk_detection_rate"],
        },
        "baseline": {
            "accuracy": bm["accuracy"],
            "precision": bm["precision"],
            "recall": bm["recall"],
            "f1": bm["f1"],
            "evidence_coverage": bm["evidence_coverage"],
            "risk_detection_rate": bm["risk_detection_rate"],
        },
        "f1_gain": comp["f1_gain"],
        "recall_gain": comp["recall_gain"],
        "detected_count": len(detected),
    }
    print(json.dumps(excerpt, ensure_ascii=False, indent=2))
    print("=" * 78)


if __name__ == "__main__":
    _result = run_demo()
    _print_report(_result)
