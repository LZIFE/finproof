"""FinProof Agent Arena Evaluation（Phase 19，任务书 §Evaluation）。

30 Arena Cases，指标：
- Debate Quality          辩论质量（消息数 + 双方产出 + Auditor issues 反向）
- Evidence Coverage       证据覆盖率
- Risk Discovery Rate     风险发现率（Skeptic 命中 / 可挑战）
- Reasoning Accuracy      逻辑准确率（Auditor logical_consistency + Reasoning 命中）
- Final Arena Score       终评

评测集独立，不参与推理（仅构造 company + question，不喂答案给 Agent）。

运行：
    cd backend
    python -m scripts.phase19_eval
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.agent_arena.arena import run_arena  # noqa: E402


# ---------------------------------------------------------------------------
# 30 个评测用例：6 公司 × 5 研究问题
# ---------------------------------------------------------------------------
def _build_test_cases() -> list[dict]:
    companies = [
        ("美的集团", "家电"),
        ("格力电器", "家电"),
        ("海尔智家", "家电"),
        ("贵州茅台", "白酒"),
        ("五粮液", "白酒"),
        ("宁德时代", "新能源"),
    ]
    questions = [
        "海外增长是否可持续",
        "竞争优势是否被夸大",
        "增长质量分析",
        "市场份额领先是否可推出长期优势",
        "海外业务利润贡献是否同步增长",
    ]
    cases: list[dict] = []
    idx = 0
    for company, industry in companies:
        for q in questions:
            idx += 1
            cases.append({
                "case_id": f"ARENA-EVAL-{idx:03d}",
                "company": company,
                "industry": industry,
                "research_question": f"{company}{q}",
            })
    return cases


def run_eval() -> dict:
    init_db()
    cases = _build_test_cases()
    print(f"准备 {len(cases)} 个评测用例…")

    summaries: list[dict] = []
    final_scores: list[float] = []
    evidence_coverages: list[float] = []
    risk_discovery_rates: list[float] = []
    reasoning_accuracies: list[float] = []
    debate_qualities: list[float] = []
    forbidden_hits = 0

    with SessionLocal() as s:
        for i, case in enumerate(cases, start=1):
            print(f"  [{i}/{len(cases)}] {case['company']} · {case['research_question'][:20]}…", end="", flush=True)
            try:
                run = run_arena(s, case["company"], case["research_question"])
                r = run.result
                if not r:
                    print(" → 无结果")
                    continue
                score = r.score
                auditor = r.auditor_report
                final_scores.append(score.final_arena_score)
                if auditor:
                    evidence_coverages.append(auditor.evidence_coverage)
                    reasoning_accuracies.append(auditor.logical_consistency)
                    # Risk Discovery Rate = valid_challenges / challengeable
                    challengeable = sum(1 for v in r.analyst_viewpoints if v.unsupported or any(kw in v.claim for kw in ("核心", "增长", "领先", "利润", "海外")))
                    rdr = len(auditor.valid_challenges) / challengeable if challengeable else 0.0
                    risk_discovery_rates.append(rdr)
                    # Debate Quality = min(messages, 4)/4 * 60 + (1 - issues/10) * 40
                    dq = min(len(run.messages), 4) / 4 * 60.0 + max(0.0, 1.0 - len(auditor.issues) / 10.0) * 40.0
                    debate_qualities.append(dq)
                # 禁止词命中
                from app.services.agent_arena import contains_forbidden_content
                texts = [v.claim for v in r.analyst_viewpoints] + [c.counter_claim for c in r.skeptic_challenges]
                if any(contains_forbidden_content(t) for t in texts):
                    forbidden_hits += 1
                summaries.append({
                    "case_id": case["case_id"],
                    "company": case["company"],
                    "research_question": case["research_question"],
                    "final_arena_score": round(score.final_arena_score, 2),
                    "winner": r.winner,
                    "viewpoints": len(r.analyst_viewpoints),
                    "challenges": len(r.skeptic_challenges),
                    "valid_challenges": len(auditor.valid_challenges) if auditor else 0,
                    "evidence_coverage": round(auditor.evidence_coverage, 3) if auditor else 0.0,
                    "debate_messages": len(run.messages),
                    "forbidden": any(contains_forbidden_content(t) for t in texts),
                })
                print(f" → score={score.final_arena_score:.1f} winner={r.winner}")
            except Exception as exc:  # noqa: BLE001
                print(f" → ERROR: {exc}")
                summaries.append({"case_id": case["case_id"], "company": case["company"], "error": str(exc)[:100]})

    n = len(cases)
    n_ok = len(final_scores)
    metrics = {
        "total_cases": n,
        "successful_runs": n_ok,
        "failed_runs": n - n_ok,
        "debate_quality_mean": round(sum(debate_qualities) / n_ok, 2) if n_ok else 0.0,
        "evidence_coverage_mean": round(sum(evidence_coverages) / n_ok, 3) if n_ok else 0.0,
        "risk_discovery_rate_mean": round(sum(risk_discovery_rates) / n_ok, 3) if n_ok else 0.0,
        "reasoning_accuracy_mean": round(sum(reasoning_accuracies) / n_ok, 3) if n_ok else 0.0,
        "final_arena_score_mean": round(sum(final_scores) / n_ok, 2) if n_ok else 0.0,
        "forbidden_hits": forbidden_hits,  # 应为 0
        "winner_distribution": {
            "analyst": sum(1 for s in summaries if s.get("winner") == "analyst"),
            "skeptic": sum(1 for s in summaries if s.get("winner") == "skeptic"),
            "tie": sum(1 for s in summaries if s.get("winner") == "tie"),
        },
        "cases": summaries,
    }
    return metrics


def _print_metrics(m: dict) -> None:
    print("\n" + "=" * 78)
    print("FinProof Phase 19 · Agent Arena Evaluation Metrics（30 Cases）")
    print("=" * 78)
    print(f"\nTotal cases            : {m['total_cases']}")
    print(f"Successful runs        : {m['successful_runs']}")
    print(f"Failed runs            : {m['failed_runs']}")
    print(f"Debate quality mean    : {m['debate_quality_mean']}")
    print(f"Evidence coverage mean : {m['evidence_coverage_mean']}")
    print(f"Risk discovery rate    : {m['risk_discovery_rate_mean']}")
    print(f"Reasoning accuracy mean: {m['reasoning_accuracy_mean']}")
    print(f"Final arena score mean : {m['final_arena_score_mean']}")
    print(f"Forbidden word hits    : {m['forbidden_hits']}  (should be 0)")
    print(f"Winner distribution    : analyst={m['winner_distribution']['analyst']} "
          f"skeptic={m['winner_distribution']['skeptic']} tie={m['winner_distribution']['tie']}")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    _m = run_eval()
    _print_metrics(_m)
    print("\n--- JSON Output (summary) ---")
    summary = {k: v for k, v in _m.items() if k != "cases"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
