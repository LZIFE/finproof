"""Phase 13 · Demo — Autonomous Investigation Agent。

任务书 §10 Demo：
- 案例：AI 报告主张「海外业务成为利润增长核心」
- Agent 自主执行：
  1. 识别 Strategic Claim
  2. 调用 Knowledge Graph（业务图谱）
  3. 发现需要利润贡献证据
  4. 调用 Evidence Retrieval
  5. 验证
  6. 输出：PARTIALLY_SUPPORTED · Risk: BUSINESS_RISK

任务书 §11 测试要求：planner / tool / execution trace / memory / integration。

设计约束（任务书）：
- 不输出投资建议；不自动交易；不替代投资经理。
- 不修改已有 Verification 核心逻辑；保持 Evidence First。
- Agent 根据计划选择调用工具；禁止直接生成事实。

运行：
    cd backend
    python -m scripts.phase13_demo
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
from app.models.autonomous_agent import (  # noqa: E402
    InvestigationMemoryRow,
    InvestigationRunRow,
    InvestigationStepRow,
)
from app.services.autonomous_agent import (  # noqa: E402
    build_registry,
    call_tool,
    classify_claim_type,
    get_investigation,
    get_memory,
    list_investigations,
    list_memories,
    make_plan,
    run_investigation,
    upsert_memory,
)
from app.services.autonomous_agent.schemas import (  # noqa: E402
    CLAIM_STRATEGIC,
    ClaimContext,
    TOOL_ASSESS_RISK,
    TOOL_DETECT_CONFLICTS,
    TOOL_GET_BUSINESS_MAP,
    TOOL_RETRIEVE_EVIDENCE,
    TOOL_VERIFY_CLAIM,
)


# ---------------------------------------------------------------------------
# Demo 案例：AI 报告主张（任务书 §10）
# ---------------------------------------------------------------------------
DEMO_CLAIM_TEXT = "海外业务成为利润增长核心"
DEMO_COMPANY = "美的集团"
DEMO_STOCK_CODE = "000333"

TOOL_LABEL = {
    TOOL_RETRIEVE_EVIDENCE: "检索证据",
    TOOL_VERIFY_CLAIM: "核验主张",
    TOOL_GET_BUSINESS_MAP: "获取业务图谱",
    TOOL_DETECT_CONFLICTS: "检测冲突",
    TOOL_ASSESS_RISK: "评估风险",
}


def _clean(session) -> None:
    """清理旧 demo 数据。"""
    for Row in (InvestigationStepRow, InvestigationRunRow, InvestigationMemoryRow):
        session.query(Row).delete()
    session.commit()


def run_demo() -> dict:
    init_db()
    result: dict = {}

    with SessionLocal() as s:
        _clean(s)

        # =======================================================
        # ① Planner 测试：根据主张文本分类
        # =======================================================
        print("\n[1/5] Planner：根据主张文本分类 claim_type…")
        claim_type = classify_claim_type(DEMO_CLAIM_TEXT)
        assert claim_type == CLAIM_STRATEGIC, f"预期 STRATEGIC，实际 {claim_type}"
        print(f"  主张「{DEMO_CLAIM_TEXT}」")
        print(f"  分类结果：{claim_type}（战略主张）")

        # 生成 Investigation Plan
        ctx = ClaimContext(
            claim_text=DEMO_CLAIM_TEXT,
            claim_type=CLAIM_STRATEGIC,
            risk_type="BUSINESS_RISK",
            company=DEMO_COMPANY,
            stock_code=DEMO_STOCK_CODE,
            claim={
                "claim_id": "C-DEMO-001",
                "original_text": DEMO_CLAIM_TEXT,
                "metric": "海外业务",
            },
        )
        plan = make_plan(ctx)
        print(f"\n  调查目标：{plan.objective}")
        print("  调查计划（steps）：")
        for st in plan.steps:
            print(f"    Step {st.step}: {TOOL_LABEL.get(st.tool, st.tool)} — {st.purpose}")

        result["planner"] = {
            "claim_text": DEMO_CLAIM_TEXT,
            "claim_type": claim_type,
            "plan_steps": [
                {"step": st.step, "tool": st.tool, "purpose": st.purpose}
                for st in plan.steps
            ],
        }

        # =======================================================
        # ② Tool 调用测试：验证 registry 可调用
        # =======================================================
        print("\n[2/5] Tool Registry：验证工具可调用…")
        registry = build_registry()
        tools_ok = all(t in registry for t in [
            TOOL_RETRIEVE_EVIDENCE, TOOL_VERIFY_CLAIM, TOOL_GET_BUSINESS_MAP,
            TOOL_DETECT_CONFLICTS, TOOL_ASSESS_RISK,
        ])
        assert tools_ok, "工具注册不完整"
        print(f"  已注册工具：{', '.join(registry.keys())}")

        # =======================================================
        # ③ 执行自主调查（Execution Trace 测试）
        # =======================================================
        print("\n[3/5] Executor：执行自主调查（Plan → Tool Calls → Evidence → Verification → Risk）…")
        run = run_investigation(s, ctx, use_memory=True)

        # 验证 execution_trace
        assert run.trace_id.startswith("TRACE-"), "trace_id 缺失"
        assert len(run.steps) > 0, "无执行步骤"
        assert all(st.status == "DONE" for st in run.steps), "步骤未完成"
        assert "verification_status" in run.conclusion, "conclusion 缺失核验结论"

        print(f"\n  Trace ID : {run.trace_id}")
        print(f"  Run ID   : {run.run_id}")
        print(f"  步骤数   : {len(run.steps)}")
        print(f"  证据数   : {len(run.evidence)}")
        print(f"  Memory   : {'已调用' if run.memory_used else '未调用'}")

        print("\n  Execution Trace（调查轨迹）：")
        for st in run.steps:
            ev_n = len(st.evidence_source)
            print(
                f"    Step {st.step} | {TOOL_LABEL.get(st.tool, st.tool)} | "
                f"{st.status} | 证据来源 {ev_n} | {st.timestamp}"
            )

        result["executor"] = {
            "trace_id": run.trace_id,
            "run_id": run.run_id,
            "steps_count": len(run.steps),
            "evidence_count": len(run.evidence),
            "memory_used": run.memory_used,
            "conclusion": run.conclusion,
            "steps": [st.to_dict() for st in run.steps],
        }

        # =======================================================
        # ④ Memory 测试：验证 Agent Memory 已写入
        # =======================================================
        print("\n[4/5] Agent Memory：验证记忆已写入…")
        mem = get_memory(s, DEMO_COMPANY)
        assert mem is not None, "Memory 未写入"
        assert mem.company == DEMO_COMPANY
        assert len(mem.previous_findings) > 0, "无历史发现"
        print(f"  公司           : {mem.company}")
        print(f"  历史风险       : {mem.historical_risk}")
        print(f"  前序发现数     : {len(mem.previous_findings)}")
        print(f"  最近一次调查 ID: {mem.last_investigation_id}")

        result["memory"] = mem.to_dict()

        # =======================================================
        # ⑤ 结论输出 + Integration 验证
        # =======================================================
        print("\n[5/5] 结论输出 + Integration 验证…")
        concl = run.conclusion
        print(f"\n  核验结论 : {concl.get('verification_status', '?')}")
        print(f"  风险分   : {concl.get('risk_score', 0)}")
        print(f"  风险等级 : {concl.get('risk_level', '?')}")
        print(f"  风险类型 : {concl.get('risk_type', '-')}")
        print(f"  证据数   : {concl.get('evidence_count', 0)}")
        print(f"  摘要     : {concl.get('summary', '')}")

        # Integration：通过 get_investigation 回读
        run_id_num = int(run.run_id.split("-")[1])
        fetched = get_investigation(s, run_id_num)
        assert fetched.trace_id == run.trace_id, "Integration 回读失败"

        # Integration：list_investigations
        listed = list_investigations(s, limit=5)
        assert len(listed) >= 1, "Integration 列表查询失败"

        # Integration：list_memories
        mems = list_memories(s, limit=5)
        assert any(m.company == DEMO_COMPANY for m in mems), "Integration 记忆列表查询失败"

        result["integration"] = {
            "fetched_trace_id": fetched.trace_id,
            "listed_count": len(listed),
            "memories_count": len(mems),
        }

    return result


def _print_summary(result: dict) -> None:
    print("\n" + "=" * 78)
    print("FinProof Phase 13 · Autonomous Investigation Agent — Demo Summary")
    print("=" * 78)

    pl = result["planner"]
    print(f"\n[Planner] 主张「{pl['claim_text']}」→ 类型 {pl['claim_type']}")
    print(f"  调查计划 {len(pl['plan_steps'])} 步")

    ex = result["executor"]
    print(f"\n[Executor] {ex['trace_id']}（{ex['run_id']}）")
    print(f"  步骤 {ex['steps_count']} · 证据 {ex['evidence_count']} · Memory {'✓' if ex['memory_used'] else '✗'}")
    c = ex["conclusion"]
    print(f"  核验结论: {c.get('verification_status', '?')} · 风险 {c.get('risk_score', 0)}（{c.get('risk_level', '?')}）")

    me = result["memory"]
    print(f"\n[Memory] {me['company']}")
    print(f"  历史发现数: {len(me['previous_findings'])} · 最近调查 ID: {me['last_investigation_id']}")

    it = result["integration"]
    print(f"\n[Integration] 回读 {it['fetched_trace_id']} ✓ · 列表 {it['listed_count']} 条 · 记忆 {it['memories_count']} 条")

    print("\n" + "=" * 78)
    print("Demo 完成：Supervisor 动态调查规划 + 工具调用 + 完整调查轨迹 + Memory。")
    print("约束遵守：不输出投资建议；不自动交易；不替代投资经理。")
    print("=" * 78)


if __name__ == "__main__":
    _result = run_demo()
    _print_summary(_result)
    print("\n--- JSON Output (excerpt) ---")
    excerpt = {
        "trace_id": _result["executor"]["trace_id"],
        "claim_type": _result["planner"]["claim_type"],
        "steps_count": _result["executor"]["steps_count"],
        "evidence_count": _result["executor"]["evidence_count"],
        "memory_used": _result["executor"]["memory_used"],
        "conclusion": _result["executor"]["conclusion"],
        "memory_company": _result["memory"]["company"],
        "memory_findings_count": len(_result["memory"]["previous_findings"]),
    }
    print(json.dumps(excerpt, ensure_ascii=False, indent=2))
