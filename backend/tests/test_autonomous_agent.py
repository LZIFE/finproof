"""Autonomous Investigation Agent Tests（Phase 13）。

覆盖（任务书 §11）：
- planner 测试（make_plan / classify_claim_type）
- tool 调用测试（build_registry / call_tool）
- execution trace 测试（run_investigation 持久化 steps）
- memory 测试（upsert_memory / get_memory / resolve_issue）
- integration 测试（API + 端到端）
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.services.autonomous_agent import (
    build_registry,
    call_tool,
    classify_claim_type,
    get_investigation,
    get_memory,
    get_investigation as _gi,
    list_investigations,
    list_memories,
    make_plan,
    resolve_issue,
    run_investigation,
    upsert_memory,
)
from app.services.autonomous_agent.schemas import (
    CLAIM_BUSINESS,
    CLAIM_COMPETITIVE,
    CLAIM_FINANCIAL,
    CLAIM_FORECAST,
    CLAIM_GROWTH,
    CLAIM_STRATEGIC,
    ClaimContext,
    TOOL_ASSESS_RISK,
    TOOL_DETECT_CONFLICTS,
    TOOL_GET_BUSINESS_MAP,
    TOOL_GET_COMPANY_PROFILE,
    TOOL_RETRIEVE_EVIDENCE,
    TOOL_VERIFY_CLAIM,
)


def _fresh_db():
    init_db()


# ---------------------------------------------------------------------------
# 1. Planner 测试
# ---------------------------------------------------------------------------
def test_classify_claim_type_strategic():
    assert classify_claim_type("海外业务成为利润增长核心") == CLAIM_STRATEGIC


def test_classify_claim_type_competitive():
    assert classify_claim_type("美的集团是行业龙头，市场份额第一") == CLAIM_COMPETITIVE


def test_classify_claim_type_forecast():
    assert classify_claim_type("预计 2025 年净利润将增长 20%") == CLAIM_FORECAST


def test_classify_claim_type_growth():
    assert classify_claim_type("营收同比增长 15%") == CLAIM_GROWTH


def test_classify_claim_type_financial():
    assert classify_claim_type("2024 年营业收入 3000 亿元") == CLAIM_FINANCIAL


def test_classify_claim_type_default_business():
    assert classify_claim_type("公司业务发展良好") == CLAIM_BUSINESS


def test_make_plan_financial_uses_evidence_verify_risk():
    ctx = ClaimContext(claim_text="营收 3000 亿", claim_type=CLAIM_FINANCIAL)
    plan = make_plan(ctx)
    tools = [s.tool for s in plan.steps]
    assert tools == [TOOL_RETRIEVE_EVIDENCE, TOOL_VERIFY_CLAIM, TOOL_ASSESS_RISK]
    assert plan.claim_type == CLAIM_FINANCIAL
    assert "3000 亿" in plan.objective


def test_make_plan_strategic_includes_business_map_and_conflicts():
    ctx = ClaimContext(
        claim_text="海外业务成为利润增长核心",
        claim_type=CLAIM_STRATEGIC,
    )
    plan = make_plan(ctx)
    tools = [s.tool for s in plan.steps]
    assert TOOL_GET_BUSINESS_MAP in tools
    assert TOOL_DETECT_CONFLICTS in tools
    assert TOOL_VERIFY_CLAIM in tools
    assert TOOL_ASSESS_RISK in tools


def test_make_plan_competitive_includes_company_profile():
    ctx = ClaimContext(
        claim_text="美的集团是行业龙头，市场份额第一",
        claim_type=CLAIM_COMPETITIVE,
    )
    plan = make_plan(ctx)
    tools = [s.tool for s in plan.steps]
    assert TOOL_GET_COMPANY_PROFILE in tools


# ---------------------------------------------------------------------------
# 2. Tool 调用测试
# ---------------------------------------------------------------------------
def test_build_registry_has_all_tools():
    registry = build_registry()
    for t in [
        TOOL_RETRIEVE_EVIDENCE,
        TOOL_VERIFY_CLAIM,
        TOOL_GET_COMPANY_PROFILE,
        TOOL_GET_BUSINESS_MAP,
        TOOL_DETECT_CONFLICTS,
        TOOL_ASSESS_RISK,
    ]:
        assert t in registry, f"缺少工具 {t}"


def test_call_tool_unknown_returns_error():
    _fresh_db()
    registry = build_registry()
    with SessionLocal() as s:
        out = call_tool(registry, s, "nonexistent_tool", claim={})
    assert "error" in out


def test_call_tool_assess_risk_returns_assessment():
    _fresh_db()
    registry = build_registry()
    with SessionLocal() as s:
        out = call_tool(
            registry,
            s,
            TOOL_ASSESS_RISK,
            claim={"claim_id": "C1", "original_text": "营收增长 20%"},
            verification_result={"verification_status": "SUPPORTED", "confidence": 0.8},
        )
    assert "risk_assessment" in out
    assert out["risk_assessment"]["risk_score"] >= 0


def test_call_tool_detect_conflicts_finds_direction_conflict():
    _fresh_db()
    registry = build_registry()
    claim = {"original_text": "海外业务成为利润增长核心", "claim_id": "C1"}
    evidence = [
        {"text": "海外营收同比下滑 5%", "block_id": 1},
    ]
    with SessionLocal() as s:
        out = call_tool(
            registry,
            s,
            TOOL_DETECT_CONFLICTS,
            claim=claim,
            evidence=evidence,
        )
    assert out["conflicts_found"] >= 1


# ---------------------------------------------------------------------------
# 3. Execution Trace 测试
# ---------------------------------------------------------------------------
def test_run_investigation_persists_steps_and_evidence():
    _fresh_db()
    ctx = ClaimContext(
        claim_text="海外业务成为利润增长核心",
        claim_type=CLAIM_STRATEGIC,
        company="测试公司A",
        stock_code="000001",
        claim={"claim_id": "C1", "original_text": "海外业务成为利润增长核心"},
    )
    with SessionLocal() as s:
        run = run_investigation(s, ctx, use_memory=False)

    # 计划非空
    assert len(run.plan.steps) > 0
    # 步骤执行完毕，全部 DONE
    assert all(st.status == "DONE" for st in run.steps)
    # 至少调用了 retrieve_evidence
    tools_used = [st.tool for st in run.steps]
    assert TOOL_RETRIEVE_EVIDENCE in tools_used
    # 有 trace_id
    assert run.trace_id.startswith("TRACE-")
    # conclusion 非空
    assert "verification_status" in run.conclusion


def test_get_investigation_round_trip():
    _fresh_db()
    ctx = ClaimContext(
        claim_text="营收增长 20%",
        claim_type=CLAIM_GROWTH,
        company="测试公司B",
        claim={"claim_id": "C2", "original_text": "营收增长 20%"},
    )
    with SessionLocal() as s:
        run = run_investigation(s, ctx, use_memory=False)
        # run_id 形如 "INV-7"，取数字部分
        run_id_num = int(run.run_id.split("-")[1])
        fetched = get_investigation(s, run_id_num)
    assert fetched.trace_id == run.trace_id


def test_list_investigations():
    _fresh_db()
    ctx = ClaimContext(
        claim_text="净利润 500 亿",
        claim_type=CLAIM_FINANCIAL,
        company="测试公司C",
        claim={"claim_id": "C3", "original_text": "净利润 500 亿"},
    )
    with SessionLocal() as s:
        run_investigation(s, ctx, use_memory=False)
        lst = list_investigations(s)
    assert len(lst) >= 1


# ---------------------------------------------------------------------------
# 4. Memory 测试
# ---------------------------------------------------------------------------
def test_upsert_and_get_memory():
    _fresh_db()
    with SessionLocal() as s:
        mem = upsert_memory(
            s,
            company="测试公司D",
            stock_code="000002",
            historical_risk={"risk_score": 55.0, "risk_level": "MEDIUM"},
            previous_findings=[{"trace_id": "T1", "claim": "营收增长"}],
        )
        assert mem.company == "测试公司D"
        assert mem.historical_risk["risk_level"] == "MEDIUM"

        fetched = get_memory(s, "测试公司D")
        assert fetched is not None
        assert len(fetched.previous_findings) == 1


def test_resolve_issue_moves_to_resolved():
    _fresh_db()
    with SessionLocal() as s:
        upsert_memory(
            s,
            company="测试公司E",
            previous_findings=[{"trace_id": "T2", "claim": "毛利率稳定"}],
        )
        mem = resolve_issue(s, "测试公司E", {"trace_id": "T2", "claim": "毛利率稳定"})
        assert mem is not None
        assert len(mem.resolved_issues) == 1
        assert len(mem.previous_findings) == 0


def test_list_memories():
    _fresh_db()
    with SessionLocal() as s:
        upsert_memory(s, company="测试公司F", previous_findings=[])
        lst = list_memories(s)
    assert any(m.company == "测试公司F" for m in lst)


# ---------------------------------------------------------------------------
# 5. Integration 测试（API 端到端）
# ---------------------------------------------------------------------------
def test_investigation_api_start_and_get():
    _fresh_db()
    client = TestClient(app)

    r = client.post(
        "/api/v1/investigations",
        json={
            "claim_text": "海外业务成为利润增长核心",
            "claim_type": "STRATEGIC",
            "risk_type": "",
            "company": "美的集团",
            "stock_code": "000333",
            "claim": {"claim_id": "C-API", "original_text": "海外业务成为利润增长核心"},
            "use_memory": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["trace_id"].startswith("TRACE-")
    assert len(body["plan"]["steps"]) > 0
    assert "conclusion" in body

    # GET by run_id（INV-{id}）
    run_id_num = body["run_id"].split("-")[1]
    r = client.get(f"/api/v1/investigations/{run_id_num}")
    assert r.status_code == 200
    assert r.json()["trace_id"] == body["trace_id"]


def test_investigation_api_list():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/investigations")
    assert r.status_code == 200
    assert "count" in r.json()


def test_investigation_api_memory_lookup():
    _fresh_db()
    with SessionLocal() as s:
        upsert_memory(s, company="美的集团", stock_code="000333", previous_findings=[])
    client = TestClient(app)
    r = client.get("/api/v1/investigations/memory/美的集团")
    assert r.status_code == 200
    assert r.json()["company"] == "美的集团"
