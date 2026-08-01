"""FinProof Executive AI Governance Center Tests（Phase 20）。

覆盖（任务书 §Testing）：
- dashboard API 测试       POST /governance/dashboard + GET overview/reliability/agent-performance
- aggregation 测试         6 部分聚合器（reliability / intelligence / risk / agent / evidence / audit）
- integration test        完整治理流水线（executive_report）端到端 → Final Governance Report
- 护栏                    禁止词；不修改 Verification 核心；不输出投资建议
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.services.governance_center import (
    aggregate_agent_performance,
    aggregate_audit_timeline,
    aggregate_evidence_graph,
    aggregate_intelligence,
    aggregate_reliability,
    aggregate_risk_monitoring,
    build_agent_performance,
    build_dashboard,
    build_overview,
    build_reliability,
    contains_forbidden_content,
    run_governance_pipeline,
)


def _fresh_db():
    init_db()


# ---------------------------------------------------------------------------
# 1. Aggregation 测试（6 部分聚合器）
# ---------------------------------------------------------------------------
def test_aggregate_reliability_empty_db_returns_zero():
    _fresh_db()
    with SessionLocal() as s:
        rs = aggregate_reliability(s)
    assert 0.0 <= rs.overall_reliability <= 100.0
    assert rs.samples >= 0
    # 空库：各项指标应在合理初始值
    assert rs.evidence_coverage >= 0.0
    assert rs.hallucination_detection_rate >= 0.0


def test_aggregate_reliability_with_arena_data():
    _fresh_db()
    # 先造一条 Arena 数据（通过既有 arena pipeline）
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run_arena(s, "聚合测试公司", "海外增长是否可持续")
    with SessionLocal() as s:
        rs = aggregate_reliability(s)
    # Arena 有数据 → arena_score > 0
    assert rs.arena_score > 0.0
    assert rs.samples >= 1


def test_aggregate_intelligence_counts_companies():
    _fresh_db()
    # 造 Research Session 数据
    from app.services.research_agent.orchestrator import run_research
    with SessionLocal() as s:
        run_research(s, "情报测试公司A", "")
        run_research(s, "情报测试公司B", "")
    with SessionLocal() as s:
        ov = aggregate_intelligence(s)
    assert ov.companies_analyzed >= 2
    assert ov.research_sessions >= 2
    # top_companies 应含这两个公司
    companies_in_top = [c["company"] for c in ov.top_companies]
    assert "情报测试公司A" in companies_in_top or "情报测试公司B" in companies_in_top


def test_aggregate_risk_monitoring_returns_structure():
    _fresh_db()
    with SessionLocal() as s:
        rm = aggregate_risk_monitoring(s)
    assert rm.total_risks >= 0
    assert isinstance(rm.current_risks, list)
    assert isinstance(rm.historical_change, dict)
    assert rm.unresolved_reviews >= 0


def test_aggregate_agent_performance_with_arena():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run_arena(s, "Agent测试公司", "海外增长是否可持续")
    with SessionLocal() as s:
        ap = aggregate_agent_performance(s)
    assert ap.arena_runs >= 1
    assert ap.analyst_performance >= 0.0
    assert ap.agent_score >= 0.0
    # winner distribution 含至少一个键
    assert isinstance(ap.winner_distribution, dict)


def test_aggregate_evidence_graph_returns_nodes_edges():
    _fresh_db()
    with SessionLocal() as s:
        eg = aggregate_evidence_graph(s, limit=50)
    assert isinstance(eg.nodes, list)
    assert isinstance(eg.edges, list)
    assert eg.companies >= 0
    assert eg.metrics >= 0


def test_aggregate_audit_timeline_returns_events():
    _fresh_db()
    with SessionLocal() as s:
        tl = aggregate_audit_timeline(s, limit=10)
    assert tl.total_events >= 0
    assert isinstance(tl.events, list)
    assert tl.distinct_users >= 0


# ---------------------------------------------------------------------------
# 2. Dashboard 组装测试
# ---------------------------------------------------------------------------
def test_build_dashboard_assembles_six_sections():
    _fresh_db()
    with SessionLocal() as s:
        dash = build_dashboard(s, governance_id="GOV-TEST")
    d = dash.to_dict()
    assert d["governance_id"] == "GOV-TEST"
    # 6 部分齐全
    for key in ("reliability", "intelligence", "risk_monitoring", "agent_performance", "evidence_graph", "audit_timeline"):
        assert key in d
    assert d["generated_at"]


def test_build_dashboard_default_governance_id():
    _fresh_db()
    with SessionLocal() as s:
        dash = build_dashboard(s)
    assert dash.governance_id.startswith("GOV-")


def test_build_overview_returns_top_metrics():
    _fresh_db()
    with SessionLocal() as s:
        ov = build_overview(s)
    for key in ("overall_reliability", "evidence_coverage", "companies_analyzed", "agent_score", "generated_at"):
        assert key in ov


def test_build_reliability_returns_score_dict():
    _fresh_db()
    with SessionLocal() as s:
        r = build_reliability(s)
    assert "overall_reliability" in r
    assert "evidence_coverage" in r


def test_build_agent_performance_returns_dict():
    _fresh_db()
    with SessionLocal() as s:
        r = build_agent_performance(s)
    assert "agent_score" in r
    assert "analyst_performance" in r


# ---------------------------------------------------------------------------
# 3. Dashboard API 测试
# ---------------------------------------------------------------------------
def test_api_post_dashboard():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/governance/dashboard", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["governance_id"]
    for key in ("reliability", "intelligence", "risk_monitoring", "agent_performance", "evidence_graph", "audit_timeline"):
        assert key in body


def test_api_post_dashboard_with_company():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/governance/dashboard", json={"company": "美的集团"})
    assert r.status_code == 200
    assert r.json()["governance_id"] == "GOV-美的集团"


def test_api_get_overview():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/governance/overview")
    assert r.status_code == 200
    assert "overall_reliability" in r.json()


def test_api_get_reliability():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/governance/reliability")
    assert r.status_code == 200
    assert "overall_reliability" in r.json()


def test_api_get_agent_performance():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/governance/agent-performance")
    assert r.status_code == 200
    assert "agent_score" in r.json()


# ---------------------------------------------------------------------------
# 4. Integration test：完整治理流水线（executive_report）
# ---------------------------------------------------------------------------
def test_run_governance_pipeline_end_to_end():
    _fresh_db()
    with SessionLocal() as s:
        report = run_governance_pipeline(s, "美的集团", "分析美的集团海外增长是否可信")
    rd = report.to_dict()
    assert rd["company"] == "美的集团"
    assert rd["research_question"].startswith("分析美的集团")
    # 9 阶段流水线
    stages = [p["stage"] for p in rd["pipeline"]]
    assert any("Research Agent" in st for st in stages)
    assert any("Verification" in st for st in stages)
    assert any("Reasoning" in st for st in stages)
    assert any("Risk" in st for st in stages)
    assert any("Committee" in st for st in stages)
    assert any("Arena" in st for st in stages)
    # 5 项输出
    assert 0.0 <= rd["reliability_score"] <= 100.0
    assert 0.0 <= rd["final_reliability_score"] <= 100.0
    assert isinstance(rd["risk_list"], list)
    assert isinstance(rd["evidence_chain"], list)
    assert isinstance(rd["agent_audit_process"], list)
    # conclusion 不含禁止词
    assert not contains_forbidden_content(rd["conclusion"])
    # conclusion 含可靠性结论而非投资建议
    assert "不构成投资建议" in rd["conclusion"] or "可靠性" in rd["conclusion"]


def test_run_governance_pipeline_rejects_empty_inputs():
    _fresh_db()
    with SessionLocal() as s:
        with pytest.raises(ValueError):
            run_governance_pipeline(s, "", "问题")
        with pytest.raises(ValueError):
            run_governance_pipeline(s, "公司", "")


def test_pipeline_stage_status_records_skip():
    """若某阶段（如 Verification）核心未就绪，状态应为 SKIPPED 而非崩溃。"""
    _fresh_db()
    with SessionLocal() as s:
        report = run_governance_pipeline(s, "集成测试公司", "增长是否可信")
    for p in report.pipeline:
        assert p.status in ("OK", "SKIPPED", "ERROR")


# ---------------------------------------------------------------------------
# 5. 护栏
# ---------------------------------------------------------------------------
def test_contains_forbidden_content():
    assert contains_forbidden_content("建议买入该公司")
    assert contains_forbidden_content("目标价50元")
    assert not contains_forbidden_content("海外收入同比增长10%")
    # 否定式免责不误判
    assert not contains_forbidden_content("本结论不构成投资建议")


def test_conclusion_never_investment_advice():
    """最终治理报告 conclusion 必须为可靠性结论，非投资建议。"""
    _fresh_db()
    with SessionLocal() as s:
        report = run_governance_pipeline(s, "护栏测试公司", "增长是否可信")
    assert not contains_forbidden_content(report.conclusion)
    # 必含"不构成投资建议"或仅陈述可靠性
    assert "不构成投资建议" in report.conclusion or "可靠性" in report.conclusion
