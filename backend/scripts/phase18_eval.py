"""FinProof FinSim Evaluation Dataset（Phase 18，任务书 §8）。

至少 30 个 Simulation Cases，输出：
- scenario success rate
- evidence coverage
- risk detection
- reasoning accuracy

评测集独立，不参与推理（仅构造场景，不喂答案给 Agent）。

运行：
    cd backend
    python -m scripts.phase18_eval
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.financial_simulation import (  # noqa: E402
    aggregate_metrics,
    make_scenario,
    run_simulation,
    SCENARIO_BUSINESS_OVERSTATEMENT,
    SCENARIO_COMPETITIVE_CLAIM_VERIFICATION,
    SCENARIO_FINANCIAL_MISSTATEMENT,
    SCENARIO_GROWTH_QUALITY_PROBLEM,
    SCENARIO_RISK_MONITORING,
)
from app.services.financial_simulation.schemas import (  # noqa: E402
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_MEDIUM,
)


# ---------------------------------------------------------------------------
# 30 个评测用例：5 类型 × 3 难度 × 2 公司 = 30
# ---------------------------------------------------------------------------
def _build_test_cases() -> list[dict]:
    cases: list[dict] = []
    companies = [
        ("美的集团", "家电"),
        ("格力电器", "家电"),
        ("海尔智家", "家电"),
        ("贵州茅台", "白酒"),
        ("五粮液", "白酒"),
        ("宁德时代", "新能源"),
    ]
    scenario_types = [
        SCENARIO_FINANCIAL_MISSTATEMENT,
        SCENARIO_BUSINESS_OVERSTATEMENT,
        SCENARIO_GROWTH_QUALITY_PROBLEM,
        SCENARIO_COMPETITIVE_CLAIM_VERIFICATION,
        SCENARIO_RISK_MONITORING,
    ]
    difficulties = [DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD]

    sid_counter = 0
    for st in scenario_types:
        for diff in difficulties:
            for company, industry in companies[:2]:  # 每类型×难度×2公司 = 30
                sid_counter += 1
                sid = f"SCEN-EVAL-{sid_counter:03d}"
                cases.append({
                    "scenario_id": sid,
                    "scenario_type": st,
                    "company": company,
                    "industry": industry,
                    "difficulty": diff,
                })
    return cases


def run_eval() -> dict:
    """对 30 个评测用例执行模拟，汇总指标。"""
    init_db()
    cases = _build_test_cases()
    print(f"准备 {len(cases)} 个评测用例…")

    results_summary: list[dict] = []
    fin_scores: list[float] = []
    final_scores: list[float] = []
    evidence_scores: list[float] = []
    reasoning_scores: list[float] = []
    risk_scores: list[float] = []
    success_count = 0

    with SessionLocal() as s:
        for i, case in enumerate(cases, start=1):
            print(f"  [{i}/{len(cases)}] {case['scenario_type'][:20]} · {case['company']} · {case['difficulty']} …", end="", flush=True)
            try:
                sim = run_simulation(
                    s,
                    case["scenario_type"],
                    case["company"],
                    case["industry"],
                    case["difficulty"],
                    case["scenario_id"],
                )
                r = sim.result
                if r:
                    fin_scores.append(r.score.fin_agent_score)
                    final_scores.append(r.score.final_score)
                    evidence_scores.append(r.score.evidence_score.score)
                    reasoning_scores.append(r.score.reasoning_score.score)
                    risk_scores.append(r.score.risk_detection_score.score)
                    if r.success:
                        success_count += 1
                    results_summary.append({
                        "scenario_id": case["scenario_id"],
                        "scenario_type": case["scenario_type"],
                        "company": case["company"],
                        "difficulty": case["difficulty"],
                        "fin_agent_score": round(r.score.fin_agent_score, 2),
                        "final_score": round(r.score.final_score, 2),
                        "evidence": round(r.score.evidence_score.score, 2),
                        "reasoning": round(r.score.reasoning_score.score, 2),
                        "risk_detection": round(r.score.risk_detection_score.score, 2),
                        "hallucination": round(r.score.hallucination_score.score, 2),
                        "success": r.success,
                        "detected": len(r.detected_findings),
                        "missed": len(r.missed_findings),
                    })
                    print(f" → score={r.score.final_score:.1f} success={r.success}")
                else:
                    print(" → 无结果")
            except Exception as exc:  # noqa: BLE001
                print(f" → ERROR: {exc}")
                results_summary.append({
                    "scenario_id": case["scenario_id"],
                    "scenario_type": case["scenario_type"],
                    "company": case["company"],
                    "difficulty": case["difficulty"],
                    "error": str(exc)[:100],
                })

    n = len(cases)
    n_ok = len(fin_scores)
    metrics = {
        "total_cases": n,
        "successful_runs": n_ok,
        "failed_runs": n - n_ok,
        "scenario_success_rate": round(success_count / n_ok, 3) if n_ok else 0.0,
        "evidence_coverage_mean": round(sum(evidence_scores) / n_ok, 2) if n_ok else 0.0,
        "risk_detection_mean": round(sum(risk_scores) / n_ok, 2) if n_ok else 0.0,
        "reasoning_accuracy_mean": round(sum(reasoning_scores) / n_ok, 2) if n_ok else 0.0,
        "fin_agent_score_mean": round(sum(fin_scores) / n_ok, 2) if n_ok else 0.0,
        "final_score_mean": round(sum(final_scores) / n_ok, 2) if n_ok else 0.0,
        "success_count": success_count,
        "cases": results_summary,
    }
    return metrics


def _print_metrics(m: dict) -> None:
    print("\n" + "=" * 78)
    print("FinProof Phase 18 · FinSim Evaluation Metrics（30 Cases）")
    print("=" * 78)
    print(f"\nTotal cases            : {m['total_cases']}")
    print(f"Successful runs        : {m['successful_runs']}")
    print(f"Failed runs            : {m['failed_runs']}")
    print(f"Scenario success rate  : {m['scenario_success_rate']} ({m['success_count']} success)")
    print(f"Evidence coverage mean : {m['evidence_coverage_mean']}")
    print(f"Risk detection mean    : {m['risk_detection_mean']}")
    print(f"Reasoning accuracy mean: {m['reasoning_accuracy_mean']}")
    print(f"FinAgent score mean    : {m['fin_agent_score_mean']}")
    print(f"Final score mean       : {m['final_score_mean']}")

    # 分类型汇总
    by_type: dict[str, list[float]] = {}
    for c in m["cases"]:
        if "final_score" not in c:
            continue
        by_type.setdefault(c["scenario_type"], []).append(c["final_score"])
    print("\nBy scenario type:")
    for st, scores in by_type.items():
        print(f"  · {st:<35} n={len(scores)} mean={round(sum(scores)/len(scores), 2)}")

    # 分难度汇总
    by_diff: dict[str, list[float]] = {}
    for c in m["cases"]:
        if "final_score" not in c:
            continue
        by_diff.setdefault(c["difficulty"], []).append(c["final_score"])
    print("\nBy difficulty:")
    for d, scores in by_diff.items():
        print(f"  · {d:<8} n={len(scores)} mean={round(sum(scores)/len(scores), 2)}")

    print("\n" + "=" * 78)


if __name__ == "__main__":
    _m = run_eval()
    _print_metrics(_m)
    print("\n--- JSON Output (summary) ---")
    summary = {k: v for k, v in _m.items() if k != "cases"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
