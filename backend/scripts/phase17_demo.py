"""FinProof Phase 17 Demo · Autonomous Financial Research Agent（任务书 §8）。

输入：美的集团 000333
Agent 自动完成：
  - 企业画像
  - 财务摘要
  - 海外业务分析
  - 风险发现
展示：完整 Research Memo（Evidence First）。

禁止：投资建议 / 股票推荐 / 估值预测 / 自动交易。

运行：
    cd backend
    python -m scripts.phase17_demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.research_agent.orchestrator import run_research  # noqa: E402
from app.services.research_agent.schemas import contains_forbidden_memo_content  # noqa: E402


def _print_memo(memo_dict: dict) -> None:
    print("\n" + "=" * 78)
    print("Research Memo（Evidence First）")
    print("=" * 78)

    print("\n① Company Overview")
    print(f"  {memo_dict.get('company_overview', '')}")

    def _print_facts(title: str, key: str):
        facts = memo_dict.get(key, [])
        print(f"\n{title}（{len(facts)}）")
        if not facts:
            print("  无事实。")
        for i, f in enumerate(facts, start=1):
            supported = f.get("supported")
            ev_count = len(f.get("evidence", []))
            tag = f"✓ 证据 {ev_count}" if supported and ev_count else "○ 无证据（Open Question）"
            print(f"  [{i}] {f.get('metric', '')} · {tag}")
            print(f"      {f.get('content', '')}")
            if f.get("notes"):
                print(f"      备注：{f.get('notes')}")

    _print_facts("② Key Facts", "key_facts")
    _print_facts("③ Financial Facts", "financial_facts")
    _print_facts("④ Business Facts", "business_facts")

    risks = memo_dict.get("risk_findings", [])
    print(f"\n⑤ Risk Findings（{len(risks)}）")
    if not risks:
        print("  未发现风险。")
    for i, r in enumerate(risks, start=1):
        print(f"  [{i}] {r.get('risk_type', '')} · {r.get('source_tool', '')} · {r.get('risk_level', '')} ({r.get('risk_score', 0)})")
        print(f"      {r.get('content', '')}")
        if r.get("logical_gap"):
            print(f"      逻辑缺口：{r.get('logical_gap')}")

    chain = memo_dict.get("evidence_chain", [])
    print(f"\n⑥ Evidence Chain（{len(chain)} 条）")
    for i, e in enumerate(chain[:8], start=1):
        print(f"  [{i}] {e.get('document_id', '?')} p{e.get('page_number', '?')} · {e.get('evidence_tier', '')}")
        print(f"      {(e.get('text') or '')[:80]}…")

    oq = memo_dict.get("open_questions", [])
    print(f"\n⑦ Open Questions（{len(oq)}）")
    if not oq:
        print("  无待验证事项。")
    for i, q in enumerate(oq, start=1):
        print(f"  [{i}] {q}")

    print("\n评测指标")
    print(f"  Evidence Coverage      : {memo_dict.get('evidence_coverage', 0.0)}")
    print(f"  Unsupported Claim Rate : {memo_dict.get('unsupported_claim_rate', 0.0)}")
    print(f"  Task Completion Rate   : {memo_dict.get('task_completion_rate', 0.0)}")


def main() -> None:
    print("=" * 78)
    print("FinProof Phase 17 · Autonomous Financial Research Agent Demo")
    print("=" * 78)
    print("\n输入：美的集团 000333")
    print("Agent 自动完成：企业画像 → 财务摘要 → 海外业务分析 → 风险发现 → Memo 生成")
    print("输出仅含事实/证据/风险/待验证事项，不构成投资建议、股票推荐或估值预测。\n")

    init_db()
    with SessionLocal() as s:
        rs = run_research(s, "美的集团", "000333")

    print(f"\nSession: {rs.session_id}")
    print(f"Phase  : {rs.phase}")
    print(f"Tasks  : {len(rs.plan.tasks) if rs.plan else 0} 项任务")
    print(f"Tools  : {len(rs.tool_calls)} 次调用")
    for tc in rs.tool_calls[:10]:
        status = "OK" if tc.success else "FAIL"
        print(f"  · [{status}] {tc.tool} → {tc.output_summary[:60]}")

    memo_dict = rs.memo.to_dict() if rs.memo else {}

    # 护栏：检查 Memo 全文不含禁止词
    texts = [memo_dict.get("company_overview", "")]
    for k in ("key_facts", "financial_facts", "business_facts"):
        for f in memo_dict.get(k, []):
            texts.append(f.get("content", ""))
            texts.append(f.get("notes", ""))
    for r in memo_dict.get("risk_findings", []):
        texts.append(r.get("content", ""))
        texts.append(r.get("logical_gap", ""))
    texts.extend(memo_dict.get("open_questions", []))
    forbidden_hits = [t for t in texts if contains_forbidden_memo_content(t)]

    _print_memo(memo_dict)

    print("\n" + "=" * 78)
    print("护栏验收")
    print("=" * 78)
    print(f"Memo 含禁止词（投资建议/股票推荐/估值预测）：{len(forbidden_hits) == 0}")
    if forbidden_hits:
        for t in forbidden_hits:
            print(f"  违规：{t[:80]}")
    print(f"\nDemo 完成：输入公司即可启动研究流程，Agent 自主规划任务，所有事实有 Evidence，输出完整 Research Memo。")

    print("\n--- Memo JSON ---")
    print(json.dumps(memo_dict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
