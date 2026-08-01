"""FinProof Autonomous Financial Research Agent Tests（Phase 17）。

覆盖（任务书 §10）：
- planner test           研究规划器
- collector test          证据收集器
- evidence grounding test 事实证据绑定（无证据不凭空生成）
- memo generation test    Memo 生成 + 禁止词护栏
- API test                POST /api/v1/research/run + GET /api/v1/research/{id}
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.services.research_agent import (
    analyze_findings,
    collect_evidence,
    generate_memo,
    make_plan,
)
from app.services.research_agent.schemas import (
    EvidenceRef,
    PHASE_MEMO_GENERATED,
    PHASE_ORDER,
    PHASE_PLANNING,
    ResearchFinding,
    ResearchPlan,
    ResearchTaskSpec,
    RiskFinding,
    TASK_BUSINESS_ANALYSIS,
    TASK_COMPANY_PROFILE,
    TASK_COMPETITION_FACTS,
    TASK_DONE,
    TASK_FINANCIAL_OVERVIEW,
    TASK_PENDING,
    TASK_RISK_DISCOVERY,
    TASK_SKIPPED,
    ToolCall,
    contains_forbidden_memo_content,
)


def _fresh_db():
    init_db()


# ---------------------------------------------------------------------------
# 1. Planner test
# ---------------------------------------------------------------------------
def test_planner_generates_full_plan():
    plan = make_plan("美的集团", "000333")
    assert plan.company == "美的集团"
    assert plan.stock_code == "000333"
    # 四类任务覆盖
    types = {t.task_type for t in plan.tasks}
    assert TASK_COMPANY_PROFILE in types
    assert TASK_FINANCIAL_OVERVIEW in types
    assert TASK_BUSINESS_ANALYSIS in types
    assert TASK_RISK_DISCOVERY in types
    assert TASK_COMPETITION_FACTS in types
    # Financial 含 revenue/profit/margin/cash_flow
    fin_metrics = {t.metric for t in plan.tasks if t.category == "Financial"}
    assert {"revenue", "profit", "margin", "cash_flow"} <= fin_metrics
    # 风险任务需 reasoning + monitoring
    risk_task = next(t for t in plan.tasks if t.task_type == TASK_RISK_DISCOVERY)
    assert risk_task.need_reasoning
    assert risk_task.need_monitoring
    # 业务分析需 KG
    biz_task = next(t for t in plan.tasks if t.task_type == TASK_BUSINESS_ANALYSIS)
    assert biz_task.need_knowledge_graph


def test_planner_requires_company():
    import pytest
    with pytest.raises(ValueError):
        make_plan("")


def test_planner_claim_query_nonempty():
    plan = make_plan("格力电器")
    for spec in plan.tasks:
        assert spec.claim_query, f"{spec.task_type} claim_query 为空"
        assert spec.objective


# ---------------------------------------------------------------------------
# 2. Collector test（无证据 → SKIPPED，不凭空生成）
# ---------------------------------------------------------------------------
def test_collector_no_evidence_marks_skipped():
    _fresh_db()
    plan = make_plan("测试公司XYZ")  # 无文档的公司
    tasks_status: dict[str, str] = {}
    tool_calls: list[ToolCall] = []
    with SessionLocal() as s:
        evidence_by_task = collect_evidence(s, plan, tasks_status, tool_calls)
    # 无证据 → SKIPPED
    for task_type, evs in evidence_by_task.items():
        if not evs:
            assert tasks_status[task_type] == TASK_SKIPPED
    # tool_calls 记录了每次 retrieval
    assert len(tool_calls) >= len(plan.tasks)
    # 无证据任务的 retrieval success=False
    skipped_calls = [t for t in tool_calls if not t.success]
    assert any(skipped_calls)


def test_collector_records_tool_calls():
    _fresh_db()
    plan = make_plan("测试公司ABC")
    tasks_status: dict[str, str] = {}
    tool_calls: list[ToolCall] = []
    with SessionLocal() as s:
        collect_evidence(s, plan, tasks_status, tool_calls)
    # 每任务至少一条 tool_call
    assert len(tool_calls) >= 1
    for tc in tool_calls:
        assert tc.tool
        assert tc.timestamp


# ---------------------------------------------------------------------------
# 3. Evidence grounding test（所有事实绑定证据）
# ---------------------------------------------------------------------------
def test_analyze_no_evidence_yields_unsupported_open_question():
    _fresh_db()
    plan = make_plan("无证据公司Q")
    tasks_status: dict[str, str] = {}
    tool_calls: list[ToolCall] = []
    with SessionLocal() as s:
        evidence_by_task = collect_evidence(s, plan, tasks_status, tool_calls)
        findings, risk_findings = analyze_findings(s, plan, evidence_by_task, tool_calls)
    # 无证据任务 → supported=False 的 Open Question
    unsupported = [f for f in findings if not f.supported]
    assert len(unsupported) >= 1
    for f in unsupported:
        assert not f.evidence
        assert "未检索到证据" in f.content or "待验证" in f.content


def test_analyze_evidence_bounded_facts_have_refs():
    _fresh_db()
    # 构造一个带证据的 plan
    plan = make_plan("证据公司P")
    tasks_status: dict[str, str] = {}
    tool_calls: list[ToolCall] = []
    # 手工注入两条证据给 financial task
    ev_refs = [
        EvidenceRef(block_id=1, document_id="doc1", page_number=8, text="营业收入同比增长10%", final_score=0.85),
        EvidenceRef(block_id=2, document_id="doc1", page_number=9, text="净利润同比增长5%", final_score=0.82),
    ]
    evidence_by_task = {TASK_FINANCIAL_OVERVIEW: ev_refs}
    # 其余任务无证据
    for spec in plan.tasks:
        if spec.task_type not in evidence_by_task:
            evidence_by_task[spec.task_type] = []
    with SessionLocal() as s:
        findings, risk_findings = analyze_findings(s, plan, evidence_by_task, tool_calls)
    # 有证据的事实 → supported=True 且绑定 EvidenceRef
    grounded = [f for f in findings if f.supported and f.evidence]
    assert len(grounded) >= 1
    for f in grounded:
        assert f.evidence
        assert f.content
        # 事实不含投资观点
        assert not contains_forbidden_memo_content(f.content)


# ---------------------------------------------------------------------------
# 4. Memo generation test（7 段结构 + 禁止词护栏）
# ---------------------------------------------------------------------------
def test_memo_has_all_7_sections():
    plan = make_plan("美的集团", "000333")
    findings = [
        ResearchFinding(task_type=TASK_COMPANY_PROFILE, metric="segments", content="业务分部：暖通/消费电器/机器人", evidence=[EvidenceRef(block_id=1, document_id="d1", page_number=8, text="业务分部")], supported=True),
        ResearchFinding(task_type=TASK_FINANCIAL_OVERVIEW, metric="revenue", content="营业收入同比增长10%", evidence=[EvidenceRef(block_id=2, document_id="d1", page_number=9, text="营收同比增10%")], supported=True),
        ResearchFinding(task_type=TASK_BUSINESS_ANALYSIS, metric="business_map", content="海外业务占比30%", evidence=[EvidenceRef(block_id=3, document_id="d2", page_number=2, text="海外业务30%")], supported=True),
        ResearchFinding(task_type=TASK_RISK_DISCOVERY, metric="risk", content="逻辑风险：收入增长不等于利润增长", evidence=[EvidenceRef(block_id=4, document_id="d2", page_number=4, text="海外利润下滑")], supported=True),
        ResearchFinding(task_type=TASK_COMPETITION_FACTS, metric="competitor", content="竞争对手：格力/海尔", evidence=[EvidenceRef(block_id=5, document_id="d3", page_number=1, text="竞争对手")], supported=True),
        ResearchFinding(task_type=TASK_FINANCIAL_OVERVIEW, metric="cash_flow", content="未检索到现金流证据", evidence=[], supported=False),
    ]
    risk_findings = [
        RiskFinding(risk_type="logic", source_tool="reasoning", content="结论过度跳跃", evidence=[EvidenceRef(block_id=4, document_id="d2", page_number=4, text="海外利润下滑")], risk_score=85.0, risk_level="HIGH", logical_gap="收入→利润：缺口"),
    ]
    tasks_status = {
        TASK_COMPANY_PROFILE: TASK_DONE,
        TASK_FINANCIAL_OVERVIEW: TASK_DONE,
        TASK_BUSINESS_ANALYSIS: TASK_DONE,
        TASK_RISK_DISCOVERY: TASK_DONE,
        TASK_COMPETITION_FACTS: TASK_SKIPPED,
    }
    tool_calls = []
    memo = generate_memo(plan, findings, risk_findings, tasks_status, tool_calls)
    # ①~⑦ 段全部存在
    assert memo.company_overview
    assert memo.key_facts
    assert memo.financial_facts
    assert memo.business_facts
    assert memo.risk_findings
    assert memo.evidence_chain
    assert memo.open_questions
    # Open Questions 含无证据事实
    assert any("现金流" in q or "未检索" in q for q in memo.open_questions)
    # 评测指标
    assert memo.evidence_coverage > 0.0
    assert memo.unsupported_claim_rate > 0.0  # 含一条无证据事实
    assert memo.task_completion_rate > 0.0


def test_memo_forbidden_word_guard_raises():
    plan = make_plan("测试公司")
    # 含禁止词的事实
    findings = [
        ResearchFinding(
            task_type=TASK_FINANCIAL_OVERVIEW,
            metric="revenue",
            content="建议买入该公司股票，目标价50元",  # 投资建议禁止词
            evidence=[EvidenceRef(block_id=1, document_id="d1", page_number=1, text="营收")],
            supported=True,
        ),
    ]
    import pytest
    with pytest.raises(ValueError, match="禁止词"):
        generate_memo(plan, findings, [], {TASK_FINANCIAL_OVERVIEW: TASK_DONE}, [])


def test_memo_evidence_chain_dedup():
    plan = make_plan("测试公司")
    ev1 = EvidenceRef(block_id=1, document_id="d1", page_number=1, text="a")
    ev2 = EvidenceRef(block_id=1, document_id="d1", page_number=1, text="a")  # 重复
    ev3 = EvidenceRef(block_id=2, document_id="d1", page_number=2, text="b")
    findings = [
        ResearchFinding(task_type=TASK_COMPANY_PROFILE, metric="segments", content="事实A", evidence=[ev1, ev2], supported=True),
        ResearchFinding(task_type=TASK_FINANCIAL_OVERVIEW, metric="revenue", content="事实B", evidence=[ev3], supported=True),
    ]
    memo = generate_memo(plan, findings, [], {TASK_COMPANY_PROFILE: TASK_DONE, TASK_FINANCIAL_OVERVIEW: TASK_DONE}, [])
    # 去重后仅 2 条证据
    assert len(memo.evidence_chain) == 2


def test_memo_company_overview_disclaimer():
    plan = make_plan("美的集团", "000333")
    memo = generate_memo(plan, [], [], {}, [])
    assert "不构成投资建议" in memo.company_overview
    assert "股票推荐" in memo.company_overview


# ---------------------------------------------------------------------------
# 5. Orchestrator + API test
# ---------------------------------------------------------------------------
def test_run_research_end_to_end_persists():
    _fresh_db()
    with SessionLocal() as s:
        from app.services.research_agent.orchestrator import run_research, get_research
        rs = run_research(s, "测试公司E2E", "000XXX")
        assert rs.session_id.startswith("RESEARCH-")
        assert rs.phase == PHASE_MEMO_GENERATED
        assert rs.memo is not None
        # 持久化查询
        from app.models.research_agent import ResearchSessionRow
        row = s.query(ResearchSessionRow).filter(ResearchSessionRow.session_id == rs.session_id).first()
        db_id = row.id
        fetched = get_research(s, db_id)
        assert fetched.company == "测试公司E2E"
        assert fetched.memo is not None


def test_api_run_and_get():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/research/run", json={"company": "API测试公司", "stock_code": "000T"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["session_id"].startswith("RESEARCH-")
    assert body["phase"] == "Memo Generated"
    assert body["memo"] is not None
    # 查 db id
    from app.models.research_agent import ResearchSessionRow
    with SessionLocal() as s:
        row = s.query(ResearchSessionRow).filter(ResearchSessionRow.session_id == body["session_id"]).first()
        db_id = row.id
    # GET /research/{id}
    r = client.get(f"/api/v1/research/{db_id}")
    assert r.status_code == 200
    body2 = r.json()
    assert body2["company"] == "API测试公司"
    assert body2["memo"] is not None
    # plan / progress / findings / evidence 全在
    assert body2["plan"] is not None
    assert body2["phase"]
    assert "findings" in body2


def test_api_list():
    _fresh_db()
    client = TestClient(app)
    client.post("/api/v1/research/run", json={"company": "列表公司A"})
    client.post("/api/v1/research/run", json={"company": "列表公司B"})
    r = client.get("/api/v1/research")
    assert r.status_code == 200
    assert r.json()["count"] >= 2


def test_api_run_rejects_empty_company():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/research/run", json={"company": ""})
    assert r.status_code == 422 or r.status_code == 400


def test_api_get_not_found():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/research/999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. Phase 顺序
# ---------------------------------------------------------------------------
def test_phase_order_is_planning_to_memo():
    assert PHASE_ORDER[0] == PHASE_PLANNING
    assert PHASE_ORDER[-1] == PHASE_MEMO_GENERATED
    assert len(PHASE_ORDER) == 5


# ---------------------------------------------------------------------------
# 7. 禁止词检测
# ---------------------------------------------------------------------------
def test_contains_forbidden_memo_content():
    assert contains_forbidden_memo_content("建议买入该公司")
    assert contains_forbidden_memo_content("目标价50元")
    assert contains_forbidden_memo_content("卖出信号")
    assert not contains_forbidden_memo_content("营业收入同比增长10%")
    assert not contains_forbidden_memo_content("海外业务利润下滑")
