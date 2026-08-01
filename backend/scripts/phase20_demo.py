"""FinProof Phase 20 Demo · Executive AI Governance Center（任务书 §Demo）。

最终比赛 Demo：用户输入「分析美的集团海外增长是否可信」→ 完整流水线 →
Final Governance Report（5 项输出）。

完整流程：
    Research Agent → Knowledge Graph → Evidence Retrieval → Verification
    → Reasoning → Risk → Committee → Arena Debate → Final Governance Report

最终输出：
    1. 可信度评分
    2. 风险列表
    3. 证据链
    4. Agent 审计过程
    5. Reliability Score

禁止：投资建议 / 交易 / 股票推荐 / 修改 Verification 核心。
不做新业务：仅串联既有模块入口。

运行：
    cd backend
    python -m scripts.phase20_demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.governance_center import (  # noqa: E402
    contains_forbidden_content,
    run_governance_pipeline,
)


def _print_demo(report_dict: dict) -> None:
    print("\n" + "=" * 78)
    print("FinProof Phase 20 Demo · Executive AI Governance Center")
    print("=" * 78)

    print(f"\n【用户输入】公司：{report_dict.get('company', '')}")
    print(f"       研究问题：{report_dict.get('research_question', '')}")
    print(f"       Report：{report_dict.get('report_id', '')}")

    # 完整流水线
    pipeline = report_dict.get("pipeline") or []
    print(f"\n【完整流水线】共 {len(pipeline)} 阶段")
    for i, p in enumerate(pipeline, start=1):
        status_tag = {"OK": "✓", "SKIPPED": "○", "ERROR": "✗"}.get(p.get("status", ""), "?")
        dur = p.get("duration_ms", 0)
        print(f"  [{i}] {status_tag} {p.get('stage', '')} ({p.get('status', '')}, {dur}ms)")
        print(f"      {p.get('summary', '')[:100]}")

    # 5 项最终输出
    print("\n" + "-" * 78)
    print("【最终输出：Final Governance Report】")
    print("-" * 78)

    print(f"\n① 可信度评分        : {report_dict.get('reliability_score', 0):.1f}/100")
    print(f"   (证据覆盖×40 + Arena×30 + Reasoning×20 + 风险调节×10)")

    risk_list = report_dict.get("risk_list") or []
    print(f"\n② 风险列表          : {len(risk_list)} 项")
    for r in risk_list:
        print(f"   · [{r.get('level')}] {r.get('company')} · {r.get('risk_type')} · {r.get('status')}")
        print(f"     {r.get('description', '')[:80]}")

    chain = report_dict.get("evidence_chain") or []
    print(f"\n③ 证据链            : {len(chain)} 条")
    for e in chain[:5]:
        print(f"   · {e.get('company')} ← doc {e.get('document_id')} p{e.get('page')} score={e.get('score')}")
        print(f"     {(e.get('text') or '')[:80]}")
    if len(chain) > 5:
        print(f"   … 其余 {len(chain) - 5} 条略")

    audit = report_dict.get("agent_audit_process") or []
    print(f"\n④ Agent 审计过程    : {len(audit)} 步")
    for a in audit:
        print(f"   · [{a.get('role')}] {a.get('phase')} — 观点 {a.get('viewpoints')} · 挑战 {a.get('challenges')}")
        print(f"     {(a.get('content') or '')[:80]}")

    final = report_dict.get("final_reliability_score", 0)
    print(f"\n⑤ Reliability Score : {final:.1f}/100")
    level = "高" if final >= 70 else "中" if final >= 40 else "低"
    print(f"   综合可靠性等级：{level}")

    # 最终结论（仅基于证据，非投资建议）
    conclusion = report_dict.get("conclusion", "")
    print(f"\n【最终结论】")
    print(f"   {conclusion}")

    # 护栏验证：仅扫描最终输出层（风险描述 + 结论），不扫描证据原文（财务原文可能含"卖出"等合规字样）
    output_texts = [conclusion] + [r.get("description", "") for r in risk_list]
    forbidden_count = sum(1 for t in output_texts if contains_forbidden_content(t))
    print(f"\n【护栏】最终输出含禁止词（投资建议/股票推荐/估值预测）：{forbidden_count == 0}（{forbidden_count} 命中）")
    if forbidden_count:
        for t in output_texts:
            if contains_forbidden_content(t):
                print(f"   违规：{t[:60]}")


def main() -> None:
    print("=" * 78)
    print("FinProof Phase 20 · Executive AI Governance Center Demo")
    print("=" * 78)
    print("\n最终比赛 Demo：用户输入「分析美的集团海外增长是否可信」")
    print("完整流程：Research → KG → Evidence → Verification → Reasoning")
    print("         → Risk → Committee → Arena → Final Governance Report")
    print("保持 Evidence First；不输出投资建议、股票推荐或交易。\n")

    init_db()
    company = "美的集团"
    question = "分析美的集团海外增长是否可信"

    print(f"▶ 启动治理流水线：{company} · {question} …\n")
    with SessionLocal() as s:
        try:
            report = run_governance_pipeline(s, company, question)
            report_dict = report.to_dict()
            _print_demo(report_dict)
        except Exception as exc:  # noqa: BLE101
            print(f"ERROR: {exc}")
            return

    # JSON 输出
    print("\n" + "=" * 78)
    print("JSON Output (summary)")
    print("=" * 78)
    summary = {
        "report_id": report_dict.get("report_id"),
        "company": report_dict.get("company"),
        "research_question": report_dict.get("research_question"),
        "pipeline_stages": len(report_dict.get("pipeline") or []),
        "reliability_score": report_dict.get("reliability_score"),
        "final_reliability_score": report_dict.get("final_reliability_score"),
        "risk_count": len(report_dict.get("risk_list") or []),
        "evidence_chain_count": len(report_dict.get("evidence_chain") or []),
        "agent_audit_steps": len(report_dict.get("agent_audit_process") or []),
        "forbidden_hits": sum(1 for t in ([r.get("description", "") for r in report_dict.get("risk_list") or []] + [report_dict.get("conclusion", "")]) if contains_forbidden_content(t)),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
