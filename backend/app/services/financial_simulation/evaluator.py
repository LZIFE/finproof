"""FinProof FinSim Evaluator（Phase 18，任务书 §3 §4）。

比对 Agent 输出与场景埋点（expected_findings / hidden_risks），调用 scoring 合成
SimulationScore，判定 success（必须埋点全检出且无幻觉）。

约束：不输出投资建议；不交易；不修改 Verification 核心。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.financial_simulation.schemas import (
    AgentRunRecord,
    ExpectedFinding,
    SimulationResult,
    SimulationScenario,
    SimulationStep,
    _now_iso,
)
from app.services.financial_simulation.scoring import (
    compute_fin_agent_score,
    _agent_finding_hits,
    _has_evidence_for,
)


def evaluate_run(
    session: Session,
    sim_id: str,
    scenario: SimulationScenario,
    agent_record: AgentRunRecord,
    steps: list[SimulationStep],
) -> SimulationResult:
    """评估单次模拟：比对 expected → 评分 → 判定 success。"""
    detected: list[str] = []
    missed: list[str] = []
    hallucination: list[str] = []

    # 比对 expected_findings
    for expected in scenario.expected_findings:
        if _agent_finding_hits(agent_record, expected):
            detected.append(expected.finding_id)
        else:
            if expected.must_find:
                missed.append(expected.finding_id)

    # 无依据输出（finding.supported=False 或 evidence 为空）
    for f in agent_record.findings + agent_record.risk_findings:
        if not f.get("evidence") and not f.get("supported", True):
            hallucination.append(f.get("content", "")[:80])

    # 评分
    score = compute_fin_agent_score(agent_record, scenario)

    # success：必须埋点全检出 + 无幻觉 + 无禁止词命中
    must_find_ids = [e.finding_id for e in scenario.expected_findings if e.must_find]
    must_missed = [mid for mid in must_find_ids if mid not in detected]
    success = (
        not must_missed
        and not hallucination
        and not score.hallucination_score.false_positives
    )

    result_id = f"SIMRES-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:16]}"
    return SimulationResult(
        result_id=result_id,
        run_id=sim_id,
        agent_run=agent_record,
        detected_findings=detected,
        missed_findings=missed,
        hallucination_findings=hallucination,
        score=score,
        success=success,
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 评测聚合（任务书 §8）
# ---------------------------------------------------------------------------
def aggregate_metrics(results: list[SimulationResult]) -> dict:
    """聚合多场景结果为评测指标。

    输出（任务书 §8）：
    - scenario success rate
    - evidence coverage
    - risk detection
    - reasoning accuracy
    """
    n = len(results)
    if n == 0:
        return {
            "total_cases": 0,
            "success_rate": 0.0,
            "evidence_coverage_mean": 0.0,
            "risk_detection_mean": 0.0,
            "reasoning_accuracy_mean": 0.0,
            "fin_agent_score_mean": 0.0,
            "final_score_mean": 0.0,
            "hallucination_rate_mean": 0.0,
        }

    success_count = sum(1 for r in results if r.success)
    evidence_mean = sum(r.score.evidence_score.score for r in results) / n
    risk_mean = sum(r.score.risk_detection_score.score for r in results) / n
    reasoning_mean = sum(r.score.reasoning_score.score for r in results) / n
    fin_mean = sum(r.score.fin_agent_score for r in results) / n
    final_mean = sum(r.score.final_score for r in results) / n
    # hallucination：false_positives 命中数 / 场景数（越低越好）
    halluc_mean = sum(len(r.score.hallucination_score.false_positives) for r in results) / n

    return {
        "total_cases": n,
        "success_rate": round(success_count / n, 3),
        "evidence_coverage_mean": round(evidence_mean, 2),
        "risk_detection_mean": round(risk_mean, 2),
        "reasoning_accuracy_mean": round(reasoning_mean, 2),
        "fin_agent_score_mean": round(fin_mean, 2),
        "final_score_mean": round(final_mean, 2),
        "hallucination_rate_mean": round(halluc_mean, 3),
        "success_count": success_count,
    }


def print_aggregate(m: dict) -> None:
    print("=" * 78)
    print("FinProof Phase 18 · FinSim Evaluation Metrics")
    print("=" * 78)
    print(f"\nTotal cases            : {m['total_cases']}")
    print(f"Success rate           : {m['success_rate']} ({m.get('success_count', 0)} success)")
    print(f"Evidence coverage mean : {m['evidence_coverage_mean']}")
    print(f"Risk detection mean   : {m['risk_detection_mean']}")
    print(f"Reasoning accuracy mean: {m['reasoning_accuracy_mean']}")
    print(f"FinAgent score mean    : {m['fin_agent_score_mean']}")
    print(f"Final score mean       : {m['final_score_mean']}")
    print(f"Hallucination rate mean: {m['hallucination_rate_mean']}  (越低越好)")
    print("\n" + "=" * 78)


__all__ = ["evaluate_run", "aggregate_metrics", "print_aggregate"]
