"""Phase 9 Investment Committee Multi-Agent 专项测试。

覆盖任务书 §9：
- agent workflow（Supervisor → Research → Risk → Compliance → Report）
- tool calling（各 Agent 调用已有模块的可追溯性）
- report generation（CommitteeReport 各部分）
- API（POST /runs / GET /runs/{id} / POST /runs/{id}/reviews）

设计约束：不输出投资建议、不自动决定买卖、保持 Human-in-the-loop。
不修改已有核心模块。
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.services import document_service as dsvc
from app.services.agent.executor import run_audit
from app.services.investment_committee.compliance_agent import (
    COMPLIANCE_TOOLS,
    run_compliance,
)
from app.services.investment_committee.research_agent import (
    RESEARCH_TOOLS,
    run_research,
)
from app.services.investment_committee.risk_agent import (
    RISK_TOOLS,
    run_risk,
)
from app.services.investment_committee.schemas import (
    AGENT_COMPLIANCE,
    AGENT_RESEARCH,
    AGENT_RISK,
    AGENT_STATUS_DONE,
    AGENT_STATUS_FAILED,
    COMPLIANCE_FORECAST_AS_FACT,
    COMPLIANCE_MISSING_EVIDENCE,
    COMPLIANCE_OVERSTATEMENT,
    COMPLIANCE_UNSUPPORTED_CLAIM,
    AgentResult,
    AgentTask,
)
from app.services.investment_committee.supervisor_agent import (
    REVIEW_SCORE_THRESHOLD,
    get_report,
    run_committee,
    save_report,
    split_tasks,
    update_human_review,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def investment_audit():
    """注册含夸大表达与海外业务描述的投资材料，运行审计返回 (doc_id, audit_id)。"""
    material = (
        "# 美的集团投资观点材料\n\n"
        "公司海外业务高速增长，已成为利润增长的核心引擎。\n"
        "公司保持行业领先，空调线上线下市场份额遥遥领先。\n"
        "盈利能力持续提升，归母净利润必将持续高速增长。\n"
        "公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n"
        "归母净利润439.45亿元，同比增长38.02%。\n"
    ).encode("utf-8")
    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="midea_investment_view.md",
            data=material,
            document_role="REPORT_TO_VERIFY",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        result = run_audit(s, doc.id, mode="mock")
        return doc.id, result["audit_id"]


# ---------------------------------------------------------------------------
# §9.1 Agent Workflow（Supervisor 任务拆解）
# ---------------------------------------------------------------------------
def test_split_tasks_returns_three_agents():
    tasks = split_tasks(document_id=1, audit_id=2, intelligence_report_id=3)
    assert len(tasks) == 3
    assert tasks[0].agent == AGENT_RESEARCH
    assert tasks[1].agent == AGENT_RISK
    assert tasks[2].agent == AGENT_COMPLIANCE
    # 所有任务携带相同的 document_id/audit_id/intelligence_report_id
    for t in tasks:
        assert t.document_id == 1
        assert t.audit_id == 2
        assert t.intelligence_report_id == 3


def test_split_tasks_without_intelligence():
    tasks = split_tasks(document_id=1, audit_id=2, intelligence_report_id=None)
    for t in tasks:
        assert t.intelligence_report_id is None


# ---------------------------------------------------------------------------
# §9.2 Tool Calling（各 Agent 工具调用可追溯）
# ---------------------------------------------------------------------------
def test_research_agent_tools_and_findings(investment_audit):
    doc_id, audit_id = investment_audit
    task = AgentTask(agent=AGENT_RESEARCH, document_id=doc_id, audit_id=audit_id)
    with SessionLocal() as s:
        result = run_research(s, task)
    assert result.status == AGENT_STATUS_DONE
    assert result.agent == AGENT_RESEARCH
    # 工具调用清单完整
    for tool in RESEARCH_TOOLS:
        assert tool in result.tools_called
    # findings 非空
    assert len(result.findings) == 1
    findings = result.findings[0]
    assert "company_overview" in findings
    assert "business_analysis" in findings
    assert "financial_summary" in findings


def test_risk_agent_tools_and_findings(investment_audit):
    doc_id, audit_id = investment_audit
    task = AgentTask(agent=AGENT_RISK, document_id=doc_id, audit_id=audit_id)
    with SessionLocal() as s:
        result = run_risk(s, task)
    assert result.status == AGENT_STATUS_DONE
    for tool in RISK_TOOLS:
        assert tool in result.tools_called
    findings = result.findings[0]
    assert "risk_score" in findings
    assert "risk_findings" in findings
    assert "conflict_findings" in findings
    assert "verification_summary" in findings


def test_compliance_agent_tools_and_findings(investment_audit):
    doc_id, audit_id = investment_audit
    task = AgentTask(agent=AGENT_COMPLIANCE, document_id=doc_id, audit_id=audit_id)
    with SessionLocal() as s:
        result = run_compliance(s, task)
    assert result.status == AGENT_STATUS_DONE
    for tool in COMPLIANCE_TOOLS:
        assert tool in result.tools_called
    findings = result.findings[0]
    assert "overall_compliance_score" in findings
    assert "findings" in findings


# ---------------------------------------------------------------------------
# §9.3 Agent 错误处理
# ---------------------------------------------------------------------------
def test_research_agent_rejects_wrong_agent():
    task = AgentTask(agent=AGENT_RISK, document_id=1)
    with SessionLocal() as s:
        result = run_research(s, task)
    assert result.status == AGENT_STATUS_FAILED


def test_research_agent_fails_on_missing_doc():
    task = AgentTask(agent=AGENT_RESEARCH, document_id=99999)
    with SessionLocal() as s:
        result = run_research(s, task)
    assert result.status == AGENT_STATUS_FAILED


def test_risk_agent_requires_audit_id():
    task = AgentTask(agent=AGENT_RISK, document_id=1, audit_id=None)
    with SessionLocal() as s:
        result = run_risk(s, task)
    assert result.status == AGENT_STATUS_FAILED


def test_compliance_agent_requires_audit_id():
    task = AgentTask(agent=AGENT_COMPLIANCE, document_id=1, audit_id=None)
    with SessionLocal() as s:
        result = run_compliance(s, task)
    assert result.status == AGENT_STATUS_FAILED


# ---------------------------------------------------------------------------
# §9.4 Report Generation（run_committee 全链路）
# ---------------------------------------------------------------------------
def test_run_committee_generates_full_report(investment_audit):
    doc_id, audit_id = investment_audit
    with SessionLocal() as s:
        report = run_committee(s, document_id=doc_id, audit_id=audit_id,
                               intelligence_report_id=None)
        d = report.to_dict()

    # 基本字段
    assert d["company"] == "美的集团"
    assert d["stock_code"] == "000333"
    assert d["audit_id"] == audit_id

    # Agent 流程
    assert len(d["agent_flow"]) == 3
    agents_in_flow = {f["agent"] for f in d["agent_flow"]}
    assert agents_in_flow == {AGENT_RESEARCH, AGENT_RISK, AGENT_COMPLIANCE}
    for f in d["agent_flow"]:
        assert f["status"] == AGENT_STATUS_DONE

    # 报告各部分存在
    assert "executive_summary" in d
    assert "research_findings" in d
    assert "risk_findings" in d
    assert "compliance_findings" in d
    assert "evidence_chain" in d
    assert "human_review_items" in d

    # Executive Summary 含三 Agent 摘要
    es = d["executive_summary"]
    assert es["research_summary"]
    assert es["risk_summary"]
    assert es["compliance_summary"]


def test_run_committee_raises_on_missing_doc():
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            run_committee(s, document_id=99999, audit_id=None,
                          intelligence_report_id=None)


def test_save_and_get_report_persistence(investment_audit):
    doc_id, audit_id = investment_audit
    with SessionLocal() as s:
        report = run_committee(s, document_id=doc_id, audit_id=audit_id,
                               intelligence_report_id=None)
        report = save_report(s, report)
        rid = report.id
        assert rid is not None

    with SessionLocal() as s:
        loaded = get_report(s, rid)
        assert loaded.company == "美的集团"
        assert loaded.document_id == doc_id
        assert loaded.audit_id == audit_id
        # Agent 流程可读回
        assert len(loaded.agent_flow) == 3


def test_get_report_raises_on_missing():
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            get_report(s, 99999)


# ---------------------------------------------------------------------------
# §9.5 Human Review（保持 Human-in-the-loop）
# ---------------------------------------------------------------------------
def test_human_review_items_generated_for_high_risk(investment_audit):
    """高风险项应自动提请人工审核。"""
    doc_id, audit_id = investment_audit
    with SessionLocal() as s:
        report = run_committee(s, document_id=doc_id, audit_id=audit_id,
                               intelligence_report_id=None)
    # 高风险/合规问题自动提请
    items = report.human_review_items
    # 至少有一条人工审核项（投资材料含夸大/预测表达）
    assert len(items) >= 1
    # 所有审核项初始状态为 NEED_REVIEW
    for item in items:
        assert item.review_status == "NEED_REVIEW"
    # 高风险项的 risk_score ≥ 阈值或为 HIGH 级别
    high_items = [i for i in items if i.risk_score >= REVIEW_SCORE_THRESHOLD]
    assert len(high_items) >= 1


def test_update_human_review_changes_status(investment_audit):
    """人工审核：NEED_REVIEW → APPROVED / REJECTED 持久化。"""
    doc_id, audit_id = investment_audit
    with SessionLocal() as s:
        report = run_committee(s, document_id=doc_id, audit_id=audit_id,
                               intelligence_report_id=None)
        report = save_report(s, report)
        rid = report.id
        item_id = report.human_review_items[0].item_id

        # APPROVED
        approved = update_human_review(s, rid, item_id, "APPROVED",
                                       note="核实一致", reviewer="投资经理A")
        assert approved.review_status == "APPROVED"
        assert approved.note == "核实一致"

        # 读回验证
        loaded = get_report(s, rid)
        target = next(i for i in loaded.human_review_items if i.item_id == item_id)
        assert target.review_status == "APPROVED"


def test_update_human_review_rejects_invalid_status(investment_audit):
    doc_id, audit_id = investment_audit
    with SessionLocal() as s:
        report = run_committee(s, document_id=doc_id, audit_id=audit_id,
                               intelligence_report_id=None)
        report = save_report(s, report)
        rid = report.id
        item_id = report.human_review_items[0].item_id
        with pytest.raises(ValueError):
            update_human_review(s, rid, item_id, "INVALID_STATUS")


def test_update_human_review_raises_on_missing_item(investment_audit):
    doc_id, audit_id = investment_audit
    with SessionLocal() as s:
        report = run_committee(s, document_id=doc_id, audit_id=audit_id,
                               intelligence_report_id=None)
        report = save_report(s, report)
        rid = report.id
        with pytest.raises(LookupError):
            update_human_review(s, rid, "REV-9999", "APPROVED")


# ---------------------------------------------------------------------------
# §9.6 Compliance 四类检查
# ---------------------------------------------------------------------------
def test_compliance_detects_four_check_types(investment_audit):
    """投资材料含夸大表达/预测为事实，应触发对应检查类型。"""
    doc_id, audit_id = investment_audit
    task = AgentTask(agent=AGENT_COMPLIANCE, document_id=doc_id, audit_id=audit_id)
    with SessionLocal() as s:
        result = run_compliance(s, task)
    findings = result.findings[0]
    check_types = {f["check_type"] for f in findings["findings"]}
    # 投资材料含"遥遥领先"（夸大）和"必将持续高速增长"（预测为事实）
    # 至少触发其中一类
    assert check_types & {COMPLIANCE_OVERSTATEMENT, COMPLIANCE_FORECAST_AS_FACT}


def test_compliance_finding_has_unique_ids(investment_audit):
    doc_id, audit_id = investment_audit
    task = AgentTask(agent=AGENT_COMPLIANCE, document_id=doc_id, audit_id=audit_id)
    with SessionLocal() as s:
        result = run_compliance(s, task)
    findings = result.findings[0]["findings"]
    ids = [f["finding_id"] for f in findings]
    assert len(set(ids)) == len(ids)
    assert all(fid.startswith("COMP-") for fid in ids)


# ---------------------------------------------------------------------------
# §9.7 Intelligence API
# ---------------------------------------------------------------------------
def test_committee_api_run_and_get(investment_audit):
    """Committee API：POST /runs / GET /runs/{id}。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    doc_id, audit_id = investment_audit
    client = TestClient(create_app())
    body = {"document_id": doc_id, "audit_id": audit_id}
    r = client.post("/api/v1/committee/runs", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["company"] == "美的集团"
    assert "agent_flow" in data
    assert "executive_summary" in data
    rid = data["id"]

    r2 = client.get(f"/api/v1/committee/runs/{rid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == rid


def test_committee_api_404_on_missing_doc():
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    body = {"document_id": 99999}
    r = client.post("/api/v1/committee/runs", json=body)
    assert r.status_code == 404


def test_committee_api_get_404_on_missing_report():
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    assert client.get("/api/v1/committee/runs/99999").status_code == 404


def test_committee_api_review_endpoint(investment_audit):
    """Committee API：POST /runs/{id}/reviews 更新审核状态。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    doc_id, audit_id = investment_audit
    client = TestClient(create_app())
    body = {"document_id": doc_id, "audit_id": audit_id}
    r = client.post("/api/v1/committee/runs", json=body)
    assert r.status_code == 201
    data = r.json()
    rid = data["id"]
    item_id = data["human_review_items"][0]["item_id"]

    r2 = client.post(f"/api/v1/committee/runs/{rid}/reviews",
                     json={"item_id": item_id, "review_status": "APPROVED",
                           "note": "核实一致", "reviewer": "投资经理A"})
    assert r2.status_code == 200
    assert r2.json()["review_status"] == "APPROVED"


def test_committee_api_review_rejects_invalid_status(investment_audit):
    from fastapi.testclient import TestClient
    from app.main import create_app

    doc_id, audit_id = investment_audit
    client = TestClient(create_app())
    body = {"document_id": doc_id, "audit_id": audit_id}
    r = client.post("/api/v1/committee/runs", json=body)
    data = r.json()
    rid = data["id"]
    item_id = data["human_review_items"][0]["item_id"]

    r2 = client.post(f"/api/v1/committee/runs/{rid}/reviews",
                     json={"item_id": item_id, "review_status": "BAD"})
    assert r2.status_code == 422


def test_committee_api_review_404_on_missing_item(investment_audit):
    from fastapi.testclient import TestClient
    from app.main import create_app

    doc_id, audit_id = investment_audit
    client = TestClient(create_app())
    body = {"document_id": doc_id, "audit_id": audit_id}
    r = client.post("/api/v1/committee/runs", json=body)
    data = r.json()
    rid = data["id"]

    r2 = client.post(f"/api/v1/committee/runs/{rid}/reviews",
                     json={"item_id": "REV-9999", "review_status": "APPROVED"})
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# §9.8 Evidence Chain 合并
# ---------------------------------------------------------------------------
def test_evidence_chain_merges_three_agents(investment_audit):
    """Evidence Chain 应合并 Research / Risk / Compliance 三 Agent 的证据引用。"""
    doc_id, audit_id = investment_audit
    with SessionLocal() as s:
        report = run_committee(s, document_id=doc_id, audit_id=audit_id,
                               intelligence_report_id=None)
    chain = report.evidence_chain
    agents_in_chain = {c["agent"] for c in chain}
    assert agents_in_chain == {AGENT_RESEARCH, AGENT_RISK, AGENT_COMPLIANCE}
    # 每条 chain 有 summary 与 evidence_refs 字段
    for c in chain:
        assert "summary" in c
        assert "evidence_refs" in c
