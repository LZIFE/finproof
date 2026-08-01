"""FinProof Phase 18 Demo · FinSim Financial Agent Simulation（任务书 §7）。

3 个 Scenario：
  1. 美的海外增长逻辑测试（Financial Misstatement Hard）
  2. 宁德时代竞争优势验证（Competitive Claim Verification Medium）
  3. 五粮液增长质量分析（Growth Quality Problem Hard）

展示：Agent 自动完成任务并评分（FinAgent Score + 5 项子分）。

禁止：投资建议 / 交易 / 修改 Verification 核心。

运行：
    cd backend
    python -m scripts.phase18_demo
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
    make_demo_scenarios,
    run_simulation,
)
from app.services.financial_simulation.simulator import run_simulation_by_id  # noqa: E402


def _print_demo(idx: int, title: str, sim_dict: dict) -> None:
    print("\n" + "=" * 78)
    print(f"Demo Scenario {idx} · {title}")
    print("=" * 78)

    scenario = sim_dict.get("scenario") or {}
    print(f"\n【场景】{scenario.get('company', '')} · {scenario.get('industry', '')} · {scenario.get('difficulty', '')}")
    print(f"  类型：{scenario.get('scenario_type', '')}")
    print(f"  目标：{scenario.get('objective', '')}")
    if scenario.get("hidden_risks"):
        print(f"  隐藏风险：{'; '.join(scenario['hidden_risks'])}")

    expected = scenario.get("expected_findings", [])
    print(f"\n【埋点】共 {len(expected)} 条")
    for ef in expected:
        tag = "必须检出" if ef.get("must_find") else "可选"
        print(f"  · [{ef['category']}] {ef['finding_id']} ({tag})：{ef['text'][:60]}")

    steps = sim_dict.get("steps", [])
    print(f"\n【Agent Actions】共 {len(steps)} 步")
    for st in steps:
        status = "OK" if st.get("success") else "FAIL"
        print(f"  · [{status}] {st.get('step_id')} {st.get('tool')} → {st.get('output_summary', '')[:60]}")

    result = sim_dict.get("result") or {}
    score = result.get("score") or {}
    print("\n【评分】")
    print(f"  FinAgent Score（原始）：{score.get('fin_agent_score', 0)}")
    print(f"  难度权重：{score.get('difficulty_weight', 1.0)}")
    print(f"  Final Score：{score.get('final_score', 0)}")
    print(f"  结果：{'✓ Success' if result.get('success') else '○ Partial'}")
    for key, label in [
        ("evidence_score", "Evidence Score"),
        ("reasoning_score", "Reasoning Score"),
        ("risk_detection_score", "Risk Detection Score"),
        ("efficiency_score", "Efficiency Score"),
        ("hallucination_score", "Hallucination Score"),
    ]:
        bd = score.get(key) or {}
        print(f"    · {label}：{bd.get('score', 0)}（检出 {bd.get('detected_count', 0)}/{bd.get('expected_count', 0)}）")

    detected = result.get("detected_findings", [])
    missed = result.get("missed_findings", [])
    halluc = result.get("hallucination_findings", [])
    print(f"\n【命中】检出 {len(detected)} · 未检出 {len(missed)} · 无依据输出 {len(halluc)}")
    if missed:
        print(f"  未检出：{', '.join(missed)}")
    if halluc:
        print(f"  无依据：{'; '.join(h[:40] for h in halluc[:3])}")

    # 护栏：Agent 输出不含禁止词
    agent_run = result.get("agent_run") or {}
    texts = []
    for f in agent_run.get("findings", []):
        texts.append(f.get("content", ""))
        texts.append(f.get("notes", ""))
    for r in agent_run.get("risk_findings", []):
        texts.append(r.get("content", ""))
        texts.append(r.get("logical_gap", ""))
    memo = agent_run.get("memo") or {}
    texts.append(memo.get("company_overview", ""))
    from app.services.financial_simulation import contains_forbidden_content
    forbidden_hits = [t for t in texts if contains_forbidden_content(t)]
    print(f"\n【护栏】Agent 输出含禁止词（投资建议/股票推荐/估值预测）：{len(forbidden_hits) == 0}")
    if forbidden_hits:
        for t in forbidden_hits:
            print(f"  违规：{t[:60]}")


def main() -> None:
    print("=" * 78)
    print("FinProof Phase 18 · FinSim — Financial Agent Simulation Environment Demo")
    print("=" * 78)
    print("\n3 个 Scenario：美的海外增长逻辑 / 宁德时代竞争优势 / 五粮液增长质量")
    print("Agent 自动完成调查 → 评分（FinAgent Score + 5 项子分）。不输出投资建议。\n")

    init_db()
    demos = make_demo_scenarios()

    titles = [
        "美的海外增长逻辑测试（Financial Misstatement Hard）",
        "宁德时代竞争优势验证（Competitive Claim Verification Medium）",
        "五粮液增长质量分析（Growth Quality Problem Hard）",
    ]

    all_runs: list[dict] = []
    with SessionLocal() as s:
        for i, scenario in enumerate(demos, start=1):
            print(f"\n▶ 启动 Scenario {i}：{scenario.scenario_id} ({scenario.company}) …")
            try:
                sim = run_simulation_by_id(s, scenario.scenario_id, scenario.company, scenario.industry)
                sim_dict = sim.to_dict()
                all_runs.append({"title": titles[i - 1], "run": sim_dict})
                _print_demo(i, titles[i - 1], sim_dict)
            except Exception as exc:  # noqa: BLE101
                print(f"  ERROR: {exc}")

    # 汇总
    print("\n" + "=" * 78)
    print("Demo 汇总")
    print("=" * 78)
    for i, r in enumerate(all_runs, start=1):
        score = (r["run"].get("result") or {}).get("score") or {}
        print(f"  Scenario {i} · {r['title'][:30]}… → Final Score {score.get('final_score', 0)}")
    print("\nDemo 完成：金融 Agent 模拟环境运行，支持多类型任务，Agent 自主完成调查，自动评分，前端展示。")

    print("\n--- JSON Output (first run summary) ---")
    if all_runs:
        first = all_runs[0]["run"]
        print(json.dumps({
            "run_id": first.get("run_id"),
            "scenario_id": first.get("scenario_id"),
            "phase": first.get("phase"),
            "fin_agent_score": (first.get("result") or {}).get("score", {}).get("fin_agent_score"),
            "final_score": (first.get("result") or {}).get("score", {}).get("final_score"),
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
