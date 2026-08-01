"""FinProof FinSim — Financial Agent Simulation Tests（Phase 18）。

覆盖（任务书 §9）：
- scenario test       场景生成（5 类型 × 3 难度）
- simulator test      模拟器端到端
- scoring test        5 项评分 + FinAgent Score
- API test            POST /simulation/runs + GET /simulation/runs/{id} + scenarios
- frontend guard      禁止词护栏
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.services.financial_simulation import (
    aggregate_metrics,
    build_scenario_catalog,
    compute_fin_agent_score,
    contains_forbidden_content,
    list_scenario_types,
    make_demo_scenarios,
    make_scenario,
    run_simulation,
    score_efficiency,
    score_evidence,
    score_hallucination,
    score_reasoning,
    score_risk_detection,
)
from app.services.financial_simulation.schemas import (
    AgentRunRecord,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_MEDIUM,
    ExpectedFinding,
    PHASE_COMPARE_AND_SCORE,
    PHASE_ORDER,
    PHASE_SCENARIO,
    SCENARIO_BUSINESS_OVERSTATEMENT,
    SCENARIO_COMPETITIVE_CLAIM_VERIFICATION,
    SCENARIO_FINANCIAL_MISSTATEMENT,
    SCENARIO_GROWTH_QUALITY_PROBLEM,
    SCENARIO_RISK_MONITORING,
    SCENARIO_TYPES,
    SimulationScenario,
)


def _fresh_db():
    init_db()


# ---------------------------------------------------------------------------
# 1. Scenario test
# ---------------------------------------------------------------------------
def test_scenario_generator_supports_all_5_types():
    assert SCENARIO_TYPES == {
        SCENARIO_FINANCIAL_MISSTATEMENT,
        SCENARIO_BUSINESS_OVERSTATEMENT,
        SCENARIO_GROWTH_QUALITY_PROBLEM,
        SCENARIO_COMPETITIVE_CLAIM_VERIFICATION,
        SCENARIO_RISK_MONITORING,
    }
    assert set(list_scenario_types()) == SCENARIO_TYPES


def test_scenario_generator_each_type_builds():
    for st in SCENARIO_TYPES:
        s = make_scenario(f"SCEN-{st[0]}-E", st, "测试公司", "综合", DIFFICULTY_EASY)
        assert s.scenario_type == st
        assert s.company
        assert s.objective
        assert s.task_query
        assert s.expected_findings  # 至少一条埋点


def test_scenario_hard_difficulty_hides_risks():
    s_easy = make_scenario("SCEN-G-E", SCENARIO_GROWTH_QUALITY_PROBLEM, "X", "白酒", DIFFICULTY_EASY)
    s_hard = make_scenario("SCEN-G-H", SCENARIO_GROWTH_QUALITY_PROBLEM, "X", "白酒", DIFFICULTY_HARD)
    # Hard 难度埋点更多 + hidden_risks 非空
    assert len(s_hard.expected_findings) >= len(s_easy.expected_findings)
    assert s_hard.hidden_risks
    # Hard 增长质量埋点含现金流/应收/存货恶化（任务书 §5 Hard 范例）
    risk_texts = " ".join(e.text for e in s_hard.expected_findings if e.category == "risk")
    assert "现金流" in risk_texts or "应收" in risk_texts
    assert "存货" in risk_texts or "毛利率" in risk_texts


def test_scenario_catalog_15_cases():
    catalog = build_scenario_catalog("测试公司", "综合")
    assert len(catalog) == 15  # 5 types × 3 difficulties
    types = {s.scenario_type for s in catalog}
    assert types == SCENARIO_TYPES
    diffs = {s.difficulty for s in catalog}
    assert diffs == {DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD}


def test_demo_scenarios_3():
    demos = make_demo_scenarios()
    assert len(demos) == 3
    assert demos[0].company == "美的集团"
    assert demos[1].company == "宁德时代"
    assert demos[2].company == "五粮液"
    # Demo 1 = Financial Misstatement Hard（美的海外增长逻辑）
    assert demos[0].scenario_type == SCENARIO_FINANCIAL_MISSTATEMENT
    assert demos[0].difficulty == DIFFICULTY_HARD
    # Demo 3 = Growth Quality Hard（五粮液增长质量）
    assert demos[2].scenario_type == SCENARIO_GROWTH_QUALITY_PROBLEM


def test_scenario_rejects_unknown_type():
    with pytest.raises(ValueError):
        make_scenario("X", "Unknown Type", "X", "X", DIFFICULTY_EASY)


# ---------------------------------------------------------------------------
# 2. Scoring test（5 项子分 + FinAgent Score）
# ---------------------------------------------------------------------------
def _build_agent_with_findings(findings: list[dict], evidence: list[dict] | None = None, risks: list[dict] | None = None, tool_calls: list[dict] | None = None, memo: dict | None = None) -> AgentRunRecord:
    return AgentRunRecord(
        session_id="RESEARCH-TEST",
        tool_calls=tool_calls or [{"tool": "evidence_retrieval", "success": True, "evidence_count": 3}],
        findings=findings,
        risk_findings=risks or [],
        evidence=evidence or [{"text": "海外收入同比增长10% 海外利润同比下滑5%", "document_id": "d1", "page_number": 8}],
        memo=memo or {"company_overview": "本 Memo 不构成投资建议。", "evidence_coverage": 0.9},
    )


def test_score_evidence_full_coverage():
    scenario = make_scenario("S", SCENARIO_FINANCIAL_MISSTATEMENT, "X", "X", DIFFICULTY_EASY)
    agent = _build_agent_with_findings(
        findings=[{"content": "海外收入增长 海外利润下滑", "supported": True, "evidence": [{"block_id": 1}]}],
        evidence=[{"text": "海外收入 海外利润 营业收入 净利润"}] * len(scenario.expected_findings),
    )
    s = score_evidence(agent, scenario)
    assert s.score >= 80.0


def test_score_evidence_zero_when_no_evidence():
    scenario = make_scenario("S", SCENARIO_FINANCIAL_MISSTATEMENT, "X", "X", DIFFICULTY_EASY)
    agent = AgentRunRecord()  # 无证据
    s = score_evidence(agent, scenario)
    assert s.score < 30.0


def test_score_reasoning_detects_logic_gap():
    scenario = make_scenario("S", SCENARIO_FINANCIAL_MISSTATEMENT, "X", "X", DIFFICULTY_EASY)
    # Agent 命中 logic 埋点：收入增长不等于利润贡献增长
    agent = _build_agent_with_findings(
        findings=[{"content": "收入增长不等于利润贡献增长 结论过度跳跃", "supported": True, "evidence": [{"block_id": 1}], "notes": "逻辑缺口"}],
    )
    s = score_reasoning(agent, scenario)
    assert s.score >= 50.0


def test_score_risk_detection():
    scenario = make_scenario("S", SCENARIO_RISK_MONITORING, "X", "X", DIFFICULTY_EASY)
    agent = _build_agent_with_findings(
        findings=[],
        risks=[{"content": "海外业务利润同比下滑 风险信号", "logical_gap": "claim 与事实冲突 海外利润增长 vs 滑下"}],
        evidence=[{"text": "海外业务 利润 同比下滑"}],
    )
    s = score_risk_detection(agent, scenario)
    assert s.score >= 50.0


def test_score_efficiency_penalizes_redundant_calls():
    scenario = make_scenario("S", SCENARIO_FINANCIAL_MISSTATEMENT, "X", "X", DIFFICULTY_EASY)
    # 过多冗余调用（50 次但仅 2 次产出）
    calls = [{"tool": "evidence_retrieval", "success": True, "evidence_count": 0}] * 48
    calls += [{"tool": "evidence_retrieval", "success": True, "evidence_count": 3}] * 2
    agent = _build_agent_with_findings(findings=[], tool_calls=calls)
    s = score_efficiency(agent, scenario)
    assert s.score < 50.0  # 冗余调用被惩罚


def test_score_hallucination_zero_when_all_grounded():
    scenario = make_scenario("S", SCENARIO_FINANCIAL_MISSTATEMENT, "X", "X", DIFFICULTY_EASY)
    agent = _build_agent_with_findings(
        findings=[{"content": "海外收入增长", "supported": True, "evidence": [{"block_id": 1}]}],
    )
    s = score_hallucination(agent, scenario)
    assert s.score == 100.0
    assert not s.false_positives


def test_score_hallucination_deducts_forbidden_words():
    scenario = make_scenario("S", SCENARIO_FINANCIAL_MISSTATEMENT, "X", "X", DIFFICULTY_EASY)
    agent = _build_agent_with_findings(
        findings=[{"content": "建议买入该公司 目标价50元", "supported": True, "evidence": [{"block_id": 1}]}],
        memo={"company_overview": "建议买入", "evidence_coverage": 0.9},
    )
    s = score_hallucination(agent, scenario)
    assert s.score < 60.0  # 禁止词扣 50 分
    assert s.false_positives  # 命中禁止词


def test_compute_fin_agent_score_combines_5_subscores():
    scenario = make_scenario("S", SCENARIO_FINANCIAL_MISSTATEMENT, "X", "X", DIFFICULTY_HARD)
    agent = _build_agent_with_findings(
        findings=[{"content": "海外收入增长 海外利润下滑 收入不等于利润贡献增长", "supported": True, "evidence": [{"block_id": 1}], "notes": "逻辑缺口"}],
        risks=[{"content": "海外利润同比下滑", "logical_gap": "收入增长→利润贡献"}],
        evidence=[{"text": "海外收入 海外利润 营业收入 净利润 现金流"}] * 4,
    )
    score = compute_fin_agent_score(agent, scenario)
    assert 0.0 <= score.fin_agent_score <= 100.0
    # Hard 难度加成后 final >= fin_agent
    assert score.final_score >= score.fin_agent_score
    assert score.difficulty_weight == 1.5


# ---------------------------------------------------------------------------
# 3. Simulator test（端到端）
# ---------------------------------------------------------------------------
def test_run_simulation_end_to_end_easy():
    _fresh_db()
    with SessionLocal() as s:
        sim = run_simulation(s, SCENARIO_FINANCIAL_MISSTATEMENT, "测试公司SIM", "综合", DIFFICULTY_EASY)
    assert sim.run_id.startswith("SIM-RUN-")
    assert sim.scenario is not None
    assert sim.phase == PHASE_COMPARE_AND_SCORE
    assert sim.result is not None
    assert sim.result.score.fin_agent_score >= 0.0
    # 步骤记录完整
    phases_seen = {st.phase for st in sim.steps}
    assert PHASE_SCENARIO in phases_seen
    assert PHASE_COMPARE_AND_SCORE in phases_seen


def test_run_simulation_hard_has_hidden_risks_in_scenario():
    _fresh_db()
    with SessionLocal() as s:
        sim = run_simulation(s, SCENARIO_GROWTH_QUALITY_PROBLEM, "测试公司G", "白酒", DIFFICULTY_HARD)
    assert sim.scenario.hidden_risks
    # Hard 增长质量埋点含现金流/应收/存货
    risk_texts = " ".join(e.text for e in sim.scenario.expected_findings if e.category == "risk")
    assert "现金流" in risk_texts or "应收" in risk_texts


def test_run_simulation_persists():
    _fresh_db()
    with SessionLocal() as s:
        sim = run_simulation(s, SCENARIO_BUSINESS_OVERSTATEMENT, "测试公司B", "家电", DIFFICULTY_MEDIUM)
        # 查库
        from app.models.financial_simulation import SimulationRunRow
        row = s.query(SimulationRunRow).filter(SimulationRunRow.run_id == sim.run_id).first()
        assert row is not None
        assert row.scenario_id == sim.scenario_id


def test_run_simulation_by_id_demo():
    _fresh_db()
    with SessionLocal() as s:
        from app.services.financial_simulation.simulator import run_simulation_by_id
        sim = run_simulation_by_id(s, "SCEN-F-H", "测试公司F", "家电")
    assert sim.scenario.scenario_type == SCENARIO_FINANCIAL_MISSTATEMENT
    assert sim.scenario.difficulty == DIFFICULTY_HARD


# ---------------------------------------------------------------------------
# 4. Aggregate metrics
# ---------------------------------------------------------------------------
def test_aggregate_metrics():
    from app.services.financial_simulation.schemas import SimulationResult, SimulationScore
    r1 = SimulationResult(success=True, score=SimulationScore(fin_agent_score=80.0, final_score=85.0))
    r2 = SimulationResult(success=False, score=SimulationScore(fin_agent_score=60.0, final_score=60.0))
    m = aggregate_metrics([r1, r2])
    assert m["total_cases"] == 2
    assert m["success_rate"] == 0.5
    assert m["fin_agent_score_mean"] == 70.0


# ---------------------------------------------------------------------------
# 5. API test
# ---------------------------------------------------------------------------
def test_api_list_scenarios():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/simulation/scenarios")
    assert r.status_code == 200
    body = r.json()
    assert len(body["scenario_types"]) == 5
    assert set(body["difficulties"]) == {DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD}


def test_api_create_run_and_get():
    _fresh_db()
    client = TestClient(app)
    r = client.post(
        "/api/v1/simulation/runs",
        json={
            "scenario_type": SCENARIO_FINANCIAL_MISSTATEMENT,
            "company": "API测试公司",
            "industry": "家电",
            "difficulty": DIFFICULTY_EASY,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["run_id"].startswith("SIM-RUN-")
    assert body["result"] is not None
    assert "fin_agent_score" in body["result"]["score"]

    # 查 db id
    from app.models.financial_simulation import SimulationRunRow
    with SessionLocal() as s:
        row = s.query(SimulationRunRow).filter(SimulationRunRow.run_id == body["run_id"]).first()
        db_id = row.id

    # GET /runs/{id}
    r = client.get(f"/api/v1/simulation/runs/{db_id}")
    assert r.status_code == 200
    body2 = r.json()
    assert body2["run_id"] == body["run_id"]
    assert body2["scenario"]["scenario_type"] == SCENARIO_FINANCIAL_MISSTATEMENT
    assert len(body2["steps"]) >= 1
    assert body2["result"]["success"] in (True, False)


def test_api_list_runs():
    _fresh_db()
    client = TestClient(app)
    client.post("/api/v1/simulation/runs", json={"scenario_type": SCENARIO_BUSINESS_OVERSTATEMENT, "company": "列表公司A", "difficulty": DIFFICULTY_EASY})
    r = client.get("/api/v1/simulation/runs")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_api_create_rejects_unknown_type():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/simulation/runs", json={"scenario_type": "Unknown", "company": "X", "difficulty": DIFFICULTY_EASY})
    assert r.status_code in (400, 422)


def test_api_get_not_found():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/simulation/runs/999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. Frontend guard
# ---------------------------------------------------------------------------
def test_contains_forbidden_content():
    assert contains_forbidden_content("建议买入该公司")
    assert contains_forbidden_content("目标价50元")
    assert contains_forbidden_content("卖出信号")
    assert not contains_forbidden_content("海外收入同比增长10%")


# ---------------------------------------------------------------------------
# 7. Phase order
# ---------------------------------------------------------------------------
def test_phase_order():
    assert PHASE_ORDER[0] == PHASE_SCENARIO
    assert PHASE_ORDER[-1] == PHASE_COMPARE_AND_SCORE
    assert len(PHASE_ORDER) == 5
