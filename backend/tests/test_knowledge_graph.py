"""Phase 10 Financial Knowledge Graph 专项测试。

覆盖任务书 §8：
- entity extraction（实体抽取）
- graph construction（图谱构建）
- fact trace（事实追溯）
- conflict detection（冲突推理）

设计约束：不修改已有 Verification 逻辑，Knowledge Graph 作为新增层。
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal, init_db
from app.services import document_service as dsvc
from app.services.agent.executor import run_audit
from app.services.knowledge_graph.conflict_reasoner import (
    compute_overall_risk,
    detect_conflicts,
)
from app.services.knowledge_graph.entity_extractor import (
    extract_entities,
    extract_metric_facts,
)
from app.services.knowledge_graph.fact_graph import (
    get_business_map,
    get_company_profile,
    get_evidence_sources,
    get_entity_network,
    get_fact_relationships,
)
from app.services.knowledge_graph.graph_builder import (
    build_graph,
    build_facts,
    build_relationships,
    load_graph,
    save_graph,
)
from app.services.knowledge_graph.schemas import (
    CONFLICT_BUSINESS_OVERSTATEMENT,
    CONFLICT_CLAIM_VS_FACT,
    CONFLICT_COMPETITIVE_NO_EVIDENCE,
    CONFLICT_GROWTH_INSUFFICIENT,
    CONFLICT_NO_OPPOSITION,
    ENTITY_BUSINESS,
    ENTITY_COMPANY,
    ENTITY_COMPETITOR,
    ENTITY_METRIC,
    ENTITY_PRODUCT,
    ENTITY_REGION,
    Fact,
    KnowledgeGraph,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def _init():
    init_db()


@pytest.fixture()
def investment_audit():
    """注册投资材料并运行审计返回 (doc_id, audit_id)。"""
    material = (
        "# 美的集团投资观点材料\n\n"
        "公司海外业务高速增长，已成为利润增长的核心引擎。\n"
        "公司保持行业领先，空调线上线下市场份额遥遥领先。\n"
        "盈利能力持续提升，归母净利润必将持续高速增长。\n"
        "公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n"
        "归母净利润439.45亿元，同比增长38.02%。\n"
        "主营业务包括暖通空调、消费电器、机器人与自动化。\n"
        "竞争对手为海尔、格力、海信。\n"
    ).encode("utf-8")
    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="midea_kg_test.md",
            data=material,
            document_role="REPORT_TO_VERIFY",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        result = run_audit(s, doc.id, mode="mock")
        return doc.id, result["audit_id"]


@pytest.fixture()
def sample_company_facts() -> list[dict]:
    """演示用 Company Facts。"""
    return [
        {
            "fact_id": "CF-0001",
            "dimension": "FINANCIAL",
            "subject": "美的集团",
            "statement": "营业收入 4564.52 亿元",
            "value": 4564.52,
            "unit": "亿元",
            "period": "2025FY",
            "source": "FINANCIAL_REPORT",
            "source_label": "美的集团 2025 年年度报告",
            "evidence": "公司2025年实现营业收入4564.52亿元，同比增长12.11%。",
            "timestamp": "2026-03-31T00:00:00Z",
            "confidence": 0.95,
        },
        {
            "fact_id": "CF-0002",
            "dimension": "COMPETITION",
            "subject": "美的空调",
            "statement": "美的空调线上线下市场份额第一",
            "value": None,
            "unit": "",
            "period": "2025FY",
            "source": "NEWS",
            "source_label": "行业第三方报告",
            "evidence": "美的空调线上线下市场份额均位列第一。",
            "timestamp": "2026-07-28T00:00:00Z",
            "confidence": 0.75,
        },
    ]


@pytest.fixture()
def sample_claims() -> list[dict]:
    """演示用 Claims。"""
    return [
        {
            "claim_id": "INV-0001",
            "claim": "海外业务高速增长",
            "original_text": "公司海外业务高速增长",
            "entity_name": "美的集团",
        },
        {
            "claim_id": "INV-0002",
            "claim": "公司保持行业领先",
            "original_text": "公司保持行业领先，空调线上线下市场份额遥遥领先",
            "entity_name": "美的集团",
        },
        {
            "claim_id": "INV-0003",
            "claim": "盈利能力持续提升",
            "original_text": "盈利能力持续提升，归母净利润必将持续高速增长",
            "entity_name": "美的集团",
        },
    ]


@pytest.fixture()
def sample_evidence() -> list[dict]:
    """演示用 Evidence。"""
    return [
        {
            "page_number": 1,
            "block_id": "blk-1",
            "text": "公司2025年实现营业收入4564.52亿元，同比增长12.11%。",
            "evidence_type": "FINANCIAL",
        },
    ]


# ---------------------------------------------------------------------------
# §8.1 Entity Extraction
# ---------------------------------------------------------------------------
def test_extract_entities_returns_company(sample_claims, sample_evidence, sample_company_facts):
    """抽取应至少返回一个公司实体。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    company_entities = [e for e in entities if e.entity_type == ENTITY_COMPANY]
    assert len(company_entities) >= 1
    assert "美的" in company_entities[0].name or "美的集团" in company_entities[0].name


def test_extract_entities_returns_multiple_types(sample_claims, sample_evidence, sample_company_facts):
    """抽取应覆盖多种实体类型（业务/产品/地区/竞争对手/指标）。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    types_found = {e.entity_type for e in entities}
    # 至少覆盖 3 种类型（COMPANY + 至少 2 种其他）
    assert ENTITY_COMPANY in types_found
    assert len(types_found) >= 3


def test_extract_entities_dedup_names(sample_claims, sample_evidence, sample_company_facts):
    """同名实体应去重。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    names = [e.name for e in entities]
    assert len(names) == len(set(names))


def test_extract_entities_has_unique_ids(sample_claims, sample_evidence, sample_company_facts):
    """每个实体应有唯一 ENT-XXXXX ID。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    ids = [e.entity_id for e in entities]
    assert len(ids) == len(set(ids))
    assert all(eid.startswith("ENT-") for eid in ids)


def test_extract_metric_facts_from_company_facts(sample_company_facts):
    """从 Company Facts 的 evidence 字段抽取数字类事实。"""
    metric_facts = extract_metric_facts(sample_company_facts, [], [])
    # CF-0001 的 evidence 含 "营业收入4564.52亿元"
    revenue_facts = [f for f in metric_facts if "营业收入" in f.get("predicate", "")]
    assert len(revenue_facts) >= 1
    assert revenue_facts[0]["object_value"] == 4564.52
    assert revenue_facts[0]["unit"] == "亿元"


# ---------------------------------------------------------------------------
# §8.2 Graph Construction
# ---------------------------------------------------------------------------
def test_build_facts_evidence_first(sample_claims, sample_evidence, sample_company_facts):
    """构建的事实必须包含 Evidence First 字段。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    facts = build_facts(entities, sample_company_facts, sample_claims, sample_evidence)
    assert len(facts) >= 1
    for f in facts:
        assert f.source  # Evidence First
        assert f.evidence
        assert f.timestamp
        assert 0.0 <= f.confidence <= 1.0


def test_build_relationships_types(sample_claims, sample_evidence, sample_company_facts):
    """构建的关系应覆盖多种关系类型。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    facts = build_facts(entities, sample_company_facts, sample_claims, sample_evidence)
    rels = build_relationships(entities, facts)
    types_found = {r.relationship_type for r in rels}
    # 至少覆盖 3 种关系类型
    assert len(types_found) >= 3
    # 所有关系有唯一 ID
    ids = [r.relationship_id for r in rels]
    assert len(ids) == len(set(ids))
    assert all(rid.startswith("REL-") for rid in ids)


def test_build_graph_aggregates_all(sample_claims, sample_evidence, sample_company_facts):
    """build_graph 应聚合实体/关系/事实。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    graph = build_graph(entities, sample_company_facts, sample_claims, sample_evidence)
    assert len(graph.entities) == len(entities)
    assert len(graph.facts) >= 1
    assert len(graph.relationships) >= 1


def test_save_and_load_graph_persistence(sample_claims, sample_evidence, sample_company_facts):
    """图谱持久化并可读回。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    graph = build_graph(entities, sample_company_facts, sample_claims, sample_evidence)
    with SessionLocal() as s:
        graph = save_graph(s, graph, document_id=99999)  # 测试用文档 ID
        # 读回
        loaded = load_graph(s, document_id=99999)
        assert len(loaded.entities) == len(graph.entities)
        assert len(loaded.facts) == len(graph.facts)
        assert len(loaded.relationships) == len(graph.relationships)


# ---------------------------------------------------------------------------
# §8.3 Fact Trace（事实追溯）
# ---------------------------------------------------------------------------
def test_get_company_profile_aggregates(sample_claims, sample_evidence, sample_company_facts):
    """Company Profile 应聚合业务/产品/地区/竞争对手。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    graph = build_graph(entities, sample_company_facts, sample_claims, sample_evidence)
    profile = get_company_profile(graph)
    assert profile.company
    # 应至少覆盖一种业务或产品
    assert len(profile.businesses) >= 1 or len(profile.products) >= 1


def test_get_business_map_structure(sample_claims, sample_evidence, sample_company_facts):
    """Business Map 应返回业务分部结构。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    graph = build_graph(entities, sample_company_facts, sample_claims, sample_evidence)
    bmap = get_business_map(graph)
    assert bmap.company
    # business_segments 应为列表
    assert isinstance(bmap.business_segments, list)


def test_get_fact_relationships_trace(sample_claims, sample_evidence, sample_company_facts):
    """Fact Relationships 应追溯事实的主体实体与关联关系。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    graph = build_graph(entities, sample_company_facts, sample_claims, sample_evidence)
    if not graph.facts:
        pytest.skip("无事实可追溯")
    fact_id = graph.facts[0].fact_id
    fr = get_fact_relationships(graph, fact_id)
    assert fr.fact_id == fact_id
    assert fr.fact  # 事实详情
    # 主体实体应存在
    assert fr.subject_entity


def test_get_evidence_sources_grouped(sample_claims, sample_evidence, sample_company_facts):
    """Evidence Sources 应按来源分组。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    graph = build_graph(entities, sample_company_facts, sample_claims, sample_evidence)
    sources = get_evidence_sources(graph)
    assert isinstance(sources, list)
    for src in sources:
        assert "source" in src
        assert "fact_count" in src
        assert "facts" in src


def test_get_entity_network_structure(sample_claims, sample_evidence, sample_company_facts):
    """Entity Network 应返回 nodes + edges 结构。"""
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    graph = build_graph(entities, sample_company_facts, sample_claims, sample_evidence)
    net = get_entity_network(graph)
    assert "nodes" in net
    assert "edges" in net
    assert len(net["nodes"]) == len(graph.entities)


# ---------------------------------------------------------------------------
# §8.4 Conflict Detection
# ---------------------------------------------------------------------------
def _build_graph_for_conflict(sample_claims, sample_evidence, sample_company_facts) -> KnowledgeGraph:
    entities = extract_entities(sample_claims, sample_evidence, sample_company_facts)
    return build_graph(entities, sample_company_facts, sample_claims, sample_evidence)


def test_conflict_business_overstatement(sample_claims, sample_evidence, sample_company_facts):
    """BUSINESS_OVERSTATEMENT：含夸大关键词的 Claim。"""
    graph = _build_graph_for_conflict(sample_claims, sample_evidence, sample_company_facts)
    claims = [{"claim_id": "INV-0002", "original_text": "公司保持行业领先，遥遥领先"}]
    res = detect_conflicts(claims, graph)
    assert len(res.findings) == 1
    assert res.findings[0].conflict_type == CONFLICT_BUSINESS_OVERSTATEMENT
    assert res.findings[0].risk_score >= 65


def test_conflict_growth_insufficient(sample_claims, sample_evidence, sample_company_facts):
    """GROWTH_INSUFFICIENT：增长类 Claim 无数字事实支持。"""
    graph = _build_graph_for_conflict(sample_claims, sample_evidence, sample_company_facts)
    # 构造一个无数字事实支持的图谱（清空 facts）
    graph_no_facts = KnowledgeGraph(
        entities=graph.entities,
        relationships=graph.relationships,
        facts=[],  # 无数字事实
    )
    claims = [{"claim_id": "INV-0001", "original_text": "海外业务高速增长"}]
    res = detect_conflicts(claims, graph_no_facts)
    assert res.findings[0].conflict_type == CONFLICT_GROWTH_INSUFFICIENT


def test_conflict_competitive_no_evidence(sample_claims, sample_evidence, sample_company_facts):
    """COMPETITIVE_NO_EVIDENCE：竞争优势 Claim 无强证据。"""
    # 构造无强证据的图谱（移含市场份额/第一的事实）
    graph = _build_graph_for_conflict(sample_claims, sample_evidence, sample_company_facts)
    # 移除含"市场份额/第一"的事实
    graph_no_strong = KnowledgeGraph(
        entities=graph.entities,
        relationships=graph.relationships,
        facts=[
            f for f in graph.facts
            if not any(kw in f"{f.predicate} {f.evidence}" for kw in ("市场份额", "第一", "排名"))
        ],
    )
    claims = [{"claim_id": "INV-0002", "original_text": "公司保持行业领先"}]
    res = detect_conflicts(claims, graph_no_strong)
    assert res.findings[0].conflict_type == CONFLICT_COMPETITIVE_NO_EVIDENCE


def test_conflict_no_opposition_when_supported(sample_claims, sample_evidence, sample_company_facts):
    """NO_OPPOSITION：Claim 有图谱强证据支持。"""
    graph = _build_graph_for_conflict(sample_claims, sample_evidence, sample_company_facts)
    # 添加含"市场份额/第一"的事实
    from app.services.knowledge_graph.schemas import Fact

    strong_fact = Fact(
        fact_id="FACT-STRONG-0001",
        subject_entity_id=graph.entities[0].entity_id if graph.entities else "",
        predicate="市场份额",
        object_value=None,
        unit="%",
        period="2025FY",
        source="NEWS",
        source_label="行业第三方报告",
        evidence="美的空调线上线下市场份额第一",
        timestamp="2026-07-28T00:00:00Z",
        confidence=0.85,
    )
    graph_with_strong = KnowledgeGraph(
        entities=graph.entities,
        relationships=graph.relationships,
        facts=graph.facts + [strong_fact],
    )
    claims = [{"claim_id": "INV-0002", "original_text": "公司保持行业领先"}]
    res = detect_conflicts(claims, graph_with_strong)
    assert res.findings[0].conflict_type == CONFLICT_NO_OPPOSITION
    assert res.findings[0].risk_score == 0.0


def test_conflict_findings_have_unique_ids(sample_claims, sample_evidence, sample_company_facts):
    """所有 ConflictFinding 应有唯一 CFLT-XXXXX ID。"""
    graph = _build_graph_for_conflict(sample_claims, sample_evidence, sample_company_facts)
    claims = [
        {"claim_id": "INV-0001", "original_text": "海外业务高速增长"},
        {"claim_id": "INV-0002", "original_text": "公司保持行业领先"},
        {"claim_id": "INV-0003", "original_text": "盈利能力持续提升"},
    ]
    res = detect_conflicts(claims, graph)
    ids = [f.finding_id for f in res.findings]
    assert len(ids) == len(set(ids))
    assert all(fid.startswith("CFLT-") for fid in ids)


def test_conflict_finding_has_graph_facts_field(sample_claims, sample_evidence, sample_company_facts):
    """ConflictFinding 应含 graph_facts 字段（任务书 §5）。"""
    graph = _build_graph_for_conflict(sample_claims, sample_evidence, sample_company_facts)
    claims = [{"claim_id": "INV-0002", "original_text": "公司遥遥领先"}]
    res = detect_conflicts(claims, graph)
    finding = res.findings[0]
    assert hasattr(finding, "graph_facts")
    # graph_facts 应为列表
    assert isinstance(finding.graph_facts, list)


def test_compute_overall_risk_formula():
    """整体风险：0.5×最高 + 0.5×冲突平均。"""
    from app.services.knowledge_graph.schemas import ConflictFinding

    f1 = ConflictFinding(
        finding_id="CFLT-1", claim_id="c1", claim="x",
        conflict_type=CONFLICT_CLAIM_VS_FACT, graph_facts=[],
        difference="d", risk_score=80.0, risk_level="HIGH",
    )
    f2 = ConflictFinding(
        finding_id="CFLT-2", claim_id="c2", claim="x",
        conflict_type=CONFLICT_BUSINESS_OVERSTATEMENT, graph_facts=[],
        difference="d", risk_score=60.0, risk_level="MEDIUM",
    )
    score, level = compute_overall_risk([f1, f2])
    # 0.5*80 + 0.5*((80+60)/2) = 40 + 35 = 75
    assert score == 75.0
    assert level == "HIGH"
    # 无冲突 → 0 LOW
    assert compute_overall_risk([]) == (0.0, "LOW")


# ---------------------------------------------------------------------------
# §8.5 Integration: full workflow with audit
# ---------------------------------------------------------------------------
def test_full_workflow_with_audit(investment_audit):
    """完整流程：审计 → 实体抽取 → 图谱构建 → 冲突推理。"""
    doc_id, audit_id = investment_audit
    # 收集 Claims / Evidence / Company Facts（从审计结果）
    import json

    from app.models.audit import AuditReport
    from app.models.claim import Claim, ExtractionRun
    from app.models.evidence import EvidenceCandidate

    with SessionLocal() as s:
        audit = s.get(AuditReport, audit_id)
        assert audit is not None
        doc_id_from_audit = audit.document_id

        run = (
            s.query(ExtractionRun)
            .filter(ExtractionRun.document_id == doc_id_from_audit)
            .order_by(ExtractionRun.id.desc())
            .first()
        )
        claims = []
        if run is not None:
            rows = s.query(Claim).filter(Claim.extraction_run_id == run.id).all()
            for r in rows:
                claims.append(
                    {
                        "claim_id": r.claim_uid,
                        "original_text": r.source_text,
                        "entity_name": r.entity_name,
                    }
                )

        evidence_rows = (
            s.query(EvidenceCandidate)
            .filter(EvidenceCandidate.document_id == doc_id)
            .limit(50)
            .all()
        )
        evidence = [{"text": e.text or ""} for e in evidence_rows]

        # Company Facts 兜底：从文档块抽取
        from app.models import DocumentBlock

        blocks = s.query(DocumentBlock).filter(DocumentBlock.document_id == doc_id).all()
        company_facts = [
            {
                "dimension": "FINANCIAL",
                "subject": "美的集团",
                "statement": (b.text or "")[:80],
                "evidence": (b.text or "")[:200],
                "source": "FINANCIAL_REPORT",
                "source_label": "投资材料",
                "timestamp": "2026-07-31T00:00:00Z",
                "confidence": 0.85,
            }
            for b in blocks if (b.text or "").strip()
        ]

        # 完整流程
        entities = extract_entities(claims, evidence, company_facts)
        assert len(entities) >= 1

        graph = build_graph(entities, company_facts, claims, evidence)
        assert len(graph.facts) >= 1
        assert len(graph.relationships) >= 1

        # 冲突推理
        if claims:
            detection = detect_conflicts(claims, graph)
            assert len(detection.findings) == len(claims)
            # 至少有一条结论（冲突或支持）
            assert detection.conflict_count + detection.support_count >= 1


# ---------------------------------------------------------------------------
# §8.6 Knowledge Graph API
# ---------------------------------------------------------------------------
def test_kg_api_build_and_get(investment_audit):
    """Knowledge Graph API：POST /build / GET /{document_id}。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    doc_id, audit_id = investment_audit
    client = TestClient(create_app())
    body = {"document_id": doc_id, "audit_id": audit_id}
    r = client.post("/api/v1/knowledge-graph/build", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["document_id"] == doc_id
    assert data["entity_count"] >= 1
    assert "graph" in data

    r2 = client.get(f"/api/v1/knowledge-graph/{doc_id}")
    assert r2.status_code == 200
    data2 = r2.json()
    assert "entity_network" in data2
    assert "evidence_sources" in data2


def test_kg_api_conflicts(investment_audit):
    """Knowledge Graph API：POST /conflicts。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    doc_id, audit_id = investment_audit
    client = TestClient(create_app())
    # 先构建图谱
    client.post("/api/v1/knowledge-graph/build", json={"document_id": doc_id, "audit_id": audit_id})
    # 冲突推理
    r = client.post("/api/v1/knowledge-graph/conflicts", json={"document_id": doc_id})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "findings" in data
    assert "overall_risk_score" in data


def test_kg_api_profile_and_business_map(investment_audit):
    """Knowledge Graph API：GET /profile / GET /business-map / GET /evidence-sources。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    doc_id, audit_id = investment_audit
    client = TestClient(create_app())
    client.post("/api/v1/knowledge-graph/build", json={"document_id": doc_id, "audit_id": audit_id})

    r1 = client.get(f"/api/v1/knowledge-graph/{doc_id}/profile")
    assert r1.status_code == 200
    assert "company" in r1.json()

    r2 = client.get(f"/api/v1/knowledge-graph/{doc_id}/business-map")
    assert r2.status_code == 200
    assert "business_segments" in r2.json()

    r3 = client.get(f"/api/v1/knowledge-graph/{doc_id}/evidence-sources")
    assert r3.status_code == 200
    assert "sources" in r3.json()


def test_kg_api_404_on_missing_graph():
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    assert client.get("/api/v1/knowledge-graph/99999").status_code == 404
    assert client.get("/api/v1/knowledge-graph/99999/profile").status_code == 404


# ---------------------------------------------------------------------------
# §8.7 Committee Integration（Research Agent 调用 Knowledge Graph）
# ---------------------------------------------------------------------------
def test_committee_research_agent_calls_knowledge_graph(investment_audit):
    """Research Agent 应调用 Knowledge Graph 工具（tools_called 含 knowledge_graph）。"""
    from app.services.investment_committee.research_agent import (
        RESEARCH_TOOLS,
        TOOL_KNOWLEDGE_GRAPH,
        run_research,
    )
    from app.services.investment_committee.schemas import (
        AGENT_RESEARCH,
        AgentTask,
    )

    doc_id, audit_id = investment_audit
    # 先构建知识图谱
    from app.services.knowledge_graph.entity_extractor import extract_entities
    from app.services.knowledge_graph.graph_builder import build_graph, save_graph

    with SessionLocal() as s:
        # 兜底 Company Facts
        from app.models import DocumentBlock

        blocks = s.query(DocumentBlock).filter(DocumentBlock.document_id == doc_id).all()
        company_facts = [
            {
                "dimension": "FINANCIAL",
                "subject": "美的集团",
                "statement": (b.text or "")[:80],
                "evidence": (b.text or "")[:200],
                "source": "FINANCIAL_REPORT",
                "source_label": "投资材料",
                "timestamp": "2026-07-31T00:00:00Z",
                "confidence": 0.85,
            }
            for b in blocks if (b.text or "").strip()
        ]
        entities = extract_entities([], [], company_facts)
        graph = build_graph(entities, company_facts, [], [])
        save_graph(s, graph, document_id=doc_id)

    # 运行 Research Agent
    task = AgentTask(agent=AGENT_RESEARCH, document_id=doc_id, audit_id=audit_id)
    with SessionLocal() as s:
        result = run_research(s, task)
    assert result.status == "DONE"
    assert TOOL_KNOWLEDGE_GRAPH in result.tools_called
    assert TOOL_KNOWLEDGE_GRAPH in RESEARCH_TOOLS
