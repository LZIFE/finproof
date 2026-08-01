"""FinProof Phase 19 Demo · Financial AI Agent Arena（任务书 §Demo）。

三个案例：
  1. 美的海外增长是否可持续
  2. 宁德时代竞争优势是否被夸大
  3. 五粮液增长质量分析

展示：Analyst 提出观点 → Skeptic 发现漏洞 → Auditor 给出 Evidence-based 结论 → Judge 评分。

禁止：投资建议 / 股票推荐 / 交易 / 修改 Verification 核心。

运行：
    cd backend
    python -m scripts.phase19_demo
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
from app.services.agent_arena import contains_forbidden_content  # noqa: E402


def _print_demo(idx: int, title: str, run_dict: dict) -> None:
    print("\n" + "=" * 78)
    print(f"Demo Case {idx} · {title}")
    print("=" * 78)

    print(f"\n【输入】公司：{run_dict.get('company', '')}")
    print(f"       问题：{run_dict.get('research_question', '')}")
    print(f"       Run：{run_dict.get('run_id', '')}")

    messages = run_dict.get("messages") or []
    print(f"\n【辩论时间线】共 {len(messages)} 条消息")
    for i, m in enumerate(messages, start=1):
        print(f"  [{i}] {m.get('role', '')} · {m.get('phase', '')}")
        print(f"      {m.get('content', '')[:100]}")

    result = run_dict.get("result") or {}
    viewpoints = result.get("analyst_viewpoints") or []
    challenges = result.get("skeptic_challenges") or []
    audit = result.get("auditor_report") or {}
    score = result.get("score") or {}

    print(f"\n【Analyst 观点】共 {len(viewpoints)} 个")
    for v in viewpoints:
        tag = "✓ 证据" if v.get("evidence") and not v.get("unsupported") else "○ 无证据"
        challenged = any(c.get("target_viewpoint_id") == v.get("viewpoint_id") for c in challenges)
        print(f"  · {v.get('viewpoint_id')} [{tag}{'/被挑战' if challenged else ''}] 置信度 {v.get('confidence')}")
        print(f"    {v.get('claim', '')[:80]}")

    print(f"\n【Skeptic 挑战】共 {len(challenges)} 次")
    for c in challenges:
        valid = "✓ 成立" if c.get("valid") else "✗ 不成立"
        print(f"  · {c.get('challenge_id')} [{c.get('challenge_type', '')}] 目标 {c.get('target_viewpoint_id')} → {valid}")
        print(f"    反驳：{c.get('counter_claim', '')[:80]}")
        if c.get("risk"):
            print(f"    风险：{c.get('risk')}（评分 {c.get('risk_score')}）")

    print(f"\n【Auditor 审计】")
    print(f"  证据覆盖：{(audit.get('evidence_coverage') or 0) * 100:.0f}%")
    print(f"  逻辑一致：{(audit.get('logical_consistency') or 0) * 100:.0f}%")
    print(f"  风险完整：{(audit.get('risk_completeness') or 0) * 100:.0f}%")
    print(f"  挑战成立：{len(audit.get('valid_challenges') or [])}/{len(challenges)}")
    print(f"  审计评分：{audit.get('audit_score', 0):.1f}")
    issues = audit.get("issues") or []
    if issues:
        print(f"  Issues（{len(issues)}）：")
        for i in issues:
            print(f"    · [{i.get('issue_type')} · {i.get('affected')}] {i.get('description', '')[:60]}")

    print(f"\n【Judge 评分】")
    print(f"  Final Arena Score：{score.get('final_arena_score', 0):.1f}")
    print(f"  Evidence（30%）：{score.get('evidence_score', {}).get('score', 0):.1f}")
    print(f"  Reasoning（25%）：{score.get('reasoning_score', {}).get('score', 0):.1f}")
    print(f"  Risk Detection（25%）：{score.get('risk_detection_score', {}).get('score', 0):.1f}")
    print(f"  Efficiency（10%）：{score.get('efficiency_score', {}).get('score', 0):.1f}")
    print(f"  Safety（10%）：{score.get('safety_score', {}).get('score', 0):.1f}")
    winner = result.get("winner", "")
    winner_label = {"analyst": "分析师胜", "skeptic": "质疑者胜", "tie": "平局"}.get(winner, winner)
    print(f"  辩论胜负：{winner_label}（仅辩论胜负，非投资建议）")

    # 护栏：检查全文不含禁止词
    texts = [v.get("claim", "") for v in viewpoints] + [c.get("counter_claim", "") for c in challenges] + [c.get("risk", "") for c in challenges]
    forbidden = [t for t in texts if contains_forbidden_content(t)]
    print(f"\n【护栏】输出含禁止词（投资建议/股票推荐/估值预测）：{len(forbidden) == 0}")
    if forbidden:
        for t in forbidden:
            print(f"  违规：{t[:60]}")


def main() -> None:
    print("=" * 78)
    print("FinProof Phase 19 · Financial AI Agent Arena Demo")
    print("=" * 78)
    print("\n3 个案例：Analyst 提出 → Skeptic 挑战 → Auditor 审计 → Judge 评分")
    print("保持 Evidence First；不输出投资建议、股票推荐或交易。\n")

    init_db()
    demos = [
        (1, "美的海外增长是否可持续", "美的集团"),
        (2, "宁德时代竞争优势是否被夸大", "宁德时代"),
        (3, "五粮液增长质量分析", "五粮液"),
    ]

    all_runs: list[dict] = []
    with SessionLocal() as s:
        for idx, question, company in demos:
            print(f"\n▶ 启动 Case {idx}：{company} · {question} …")
            try:
                run = run_arena(s, company, question)
                run_dict = run.to_dict()
                all_runs.append({"case": question, "run": run_dict})
                _print_demo(idx, question, run_dict)
            except Exception as exc:  # noqa: BLE101
                print(f"  ERROR: {exc}")

    # 汇总
    print("\n" + "=" * 78)
    print("Demo 汇总")
    print("=" * 78)
    for i, r in enumerate(all_runs, start=1):
        score = (r["run"].get("result") or {}).get("score") or {}
        winner = (r["run"].get("result") or {}).get("winner", "")
        print(f"  Case {i} · {r['case'][:24]}… → Score {score.get('final_arena_score', 0):.1f} · {winner}")
    print("\nDemo 完成：多 Agent 金融研究竞技系统运行，4 角色对抗提高可靠性。")

    print("\n--- JSON Output (first run summary) ---")
    if all_runs:
        first = all_runs[0]["run"]
        print(json.dumps({
            "run_id": first.get("run_id"),
            "company": first.get("company"),
            "phase": first.get("phase"),
            "final_arena_score": (first.get("result") or {}).get("score", {}).get("final_arena_score"),
            "winner": (first.get("result") or {}).get("winner"),
            "messages_count": len(first.get("messages") or []),
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
