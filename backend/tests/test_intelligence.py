"""Phase 8 Investment Intelligence 专项测试。

覆盖任务书 §7：
- fact extraction（Evidence First）
- conflict detection（4 类发现）
- evidence trace（Claim ↓ Evidence ↓ Conflict ↓ Risk）
- intelligence workflow（run_investigation + save/get）

设计约束：不开发自动投资建议、不进行股票推荐、不替代投资经理决策。
"""

from datetime import datetime

import pytest

from app.db import SessionLocal, init_db
from app.services import document_service as dsvc
from app.services.intelligence.conflict_detector import (
    compute_overall_risk,
    detect_conflicts,
)
from app.services.intelligence.fact_extractor import (
    validate_fact_evidence,
    extract_facts_from_financial_report,
    register_external_fact,
    register_external_facts_from_dicts,
)
from app.services.intelligence.intelligence_agent import (
    build_company_profile,
    build_evidence_chain,
    run_investigation,
    save_report,
    get_report,
)
from app.services.intelligence.schemas import (
    CONFLICT_BUSINESS_DESC,
    CONFLICT_COMPETITIVE_EVIDENCE,
    CONFLICT_FINANCIAL_DATA,
    CONFLICT_GROWTH_LOGIC,
    CONFLICT_NO_OPPOSITION,
    FACT_DIM_BUSINESS,
    FACT_DIM_COMPETITION,
    FACT_DIM_FINANCIAL,
    FACT_DIM_MARKET,
    FACT_DIM_PRODUCT,
    FACT_SOURCE_ANNOUNCEMENT,
    FACT_SOURCE_NEWS,
    FACT_SOURCE_OFFICIAL_SITE,
    CompanyFact,
    InvestmentClaim,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def _init():
    init_db()


@pytest.fixture()
def financial_doc():
    """注册一份含数字与业务关键词的演示财报。"""
    data = (
        "# 美的集团 2025 年年度报告\n\n"
        "公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n"
        "归母净利润439.45亿元，同比增长38.02%。\n"
        "主营业务包括暖通空调、消费电器、机器人与自动化。\n"
        "海外业务已成为公司利润增长的核心引擎。\n"
        "公司空调线上线下市场份额保持第一。\n"
    ).encode("utf-8")
    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="midea_annual.md",
            data=data,
            document_role="SOURCE_DOCUMENT",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        yield doc.id


# ---------------------------------------------------------------------------
# §7.1 Fact Extraction（Evidence First）
# ---------------------------------------------------------------------------
def test_validate_fact_evidence_rejects_missing_fields():
    """Evidence First：缺 source / evidence / timestamp 即拒绝。"""
    fact = CompanyFact(fact_id="FACT-0001", dimension=FACT_DIM_FINANCIAL,
                       subject="美的", statement="营收 4564.52 亿元",
                       confidence=0.9)
    errors = validate_fact_evidence(fact)
    assert "source 缺失（Evidence First 要求每条事实可追溯）" in errors
    assert "evidence 缺失（事实必须附原始证据）" in errors
    assert "timestamp 缺失（事实必须有时间戳）" in errors


def test_validate_fact_evidence_rejects_bad_confidence():
    fact = CompanyFact(
        fact_id="FACT-0001", dimension=FACT_DIM_FINANCIAL, subject="x",
        statement="s", source=FACT_SOURCE_ANNOUNCEMENT, evidence="e",
        timestamp="2026-07-31T00:00:00Z", confidence=1.5,
    )
    assert any("confidence" in e for e in validate_fact_evidence(fact))


def test_register_external_fact_passes_evidence_first():
    fact = register_external_fact(
        existing_ids=[],
        dimension=FACT_DIM_FINANCIAL,
        subject="美的",
        statement="归母净利润预增",
        source=FACT_SOURCE_ANNOUNCEMENT,
        source_label="业绩预增公告",
        evidence="公司发布 2025 年半年度业绩预增公告。",
        timestamp="2026-07-21T00:00:00Z",
        confidence=0.85,
    )
    assert fact.fact_id.startswith("FACT-")
    assert fact.source == FACT_SOURCE_ANNOUNCEMENT
    assert fact.confidence == 0.85


def test_extract_facts_from_financial_report(financial_doc):
    """从已解析的演示财报抽取事实，含数字与定性两类。"""
    with SessionLocal() as s:
        facts = extract_facts_from_financial_report(s, financial_doc)
    assert len(facts) > 0
    # 至少有一条含数值的财务事实
    numeric_facts = [f for f in facts if f.value is not None]
    assert len(numeric_facts) >= 1
    # 每条都满足 Evidence First
    for f in facts:
        assert f.source  # 财报默认 FINANCIAL_REPORT
        assert f.evidence
        assert f.timestamp
        assert 0.0 <= f.confidence <= 1.0


def test_extract_facts_raises_on_missing_doc():
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            extract_facts_from_financial_report(s, 99999)


# ---------------------------------------------------------------------------
# §7.2 Conflict Detection（4 类发现）
# ---------------------------------------------------------------------------
def _make_fact(**kwargs) -> CompanyFact:
    base = dict(
        fact_id="FACT-0001",
        dimension=FACT_DIM_FINANCIAL,
        subject="美的",
        statement="营业收入 4564.52 亿元",
        value=4564.52,
        unit="亿元",
        period="2025FY",
        source="FINANCIAL_REPORT",
        source_label="美的集团 2025 年年度报告",
        evidence="公司2025年实现营业收入4564.52亿元。",
        timestamp="2026-03-31T00:00:00Z",
        confidence=0.95,
    )
    base.update(kwargs)
    return CompanyFact(**base)


def test_conflict_financial_data_mismatch():
    """FINANCIAL_DATA_CONFLICT：Claim 数值与 Fact 不一致。"""
    claims = [InvestmentClaim(claim_id="INV-0001", claim="营业收入 5000 亿元",
                              dimension=FACT_DIM_FINANCIAL, value=5000.0, unit="亿元")]
    facts = [_make_fact(value=4564.52, statement="营业收入 4564.52 亿元")]
    res = detect_conflicts(claims, facts)
    assert len(res.findings) == 1
    assert res.findings[0].conflict_type == CONFLICT_FINANCIAL_DATA
    assert res.findings[0].risk_score >= 80
    assert res.conflict_count == 1


def test_conflict_financial_data_match_is_no_opposition():
    """数值一致 → NO_OPPOSITION（支持，风险 0）。"""
    claims = [InvestmentClaim(claim_id="INV-0001", claim="营业收入 4564.52 亿元",
                              dimension=FACT_DIM_FINANCIAL, value=4564.52, unit="亿元")]
    facts = [_make_fact(value=4564.52)]
    res = detect_conflicts(claims, facts)
    assert res.findings[0].conflict_type == CONFLICT_NO_OPPOSITION
    assert res.findings[0].risk_score == 0.0
    assert res.support_count == 1


def test_conflict_growth_logic_insufficient():
    """GROWTH_LOGIC_INSUFFICIENT：增长类主张无数字证据。"""
    claims = [InvestmentClaim(claim_id="INV-0001", claim="海外业务高速增长",
                              dimension=FACT_DIM_MARKET)]
    # 仅有 MARKET 维度的定性事实，无 FINANCIAL 数值
    facts = [_make_fact(dimension=FACT_DIM_MARKET, value=None,
                        statement="海外业务成为利润增长引擎")]
    res = detect_conflicts(claims, facts)
    assert res.findings[0].conflict_type == CONFLICT_GROWTH_LOGIC
    assert res.findings[0].risk_score >= 50


def test_conflict_business_desc_contradiction():
    """BUSINESS_DESC_CONFLICT：Claim 含正向定性（非增长关键词），Fact 含负向定性。"""
    claims = [InvestmentClaim(claim_id="INV-0001", claim="公司业务稳健扩张",
                              dimension=FACT_DIM_FINANCIAL)]
    # Fact 含负向关键词"下降"，且无 value 避免触发 FINANCIAL 比对
    facts = [_make_fact(statement="公司净利润下降", evidence="公司净利润下降 5%",
                        value=None, dimension=FACT_DIM_FINANCIAL)]
    res = detect_conflicts(claims, facts)
    # Claim 含"扩张"（正向）↔ Fact 含"下降"（负向）→ 业务描述冲突
    assert res.findings[0].conflict_type == CONFLICT_BUSINESS_DESC


def test_conflict_competitive_evidence_missing():
    """COMPETITIVE_EVIDENCE_MISSING：领先主张无 COMPETITION Fact。"""
    claims = [InvestmentClaim(claim_id="INV-0001", claim="公司保持行业领先",
                              dimension=FACT_DIM_COMPETITION)]
    # 配对的 Fact 不含 COMPETITION 维度 → detector 兜底全部 facts
    facts = [_make_fact(dimension=FACT_DIM_FINANCIAL, value=100.0,
                        statement="营业收入 100 亿元")]
    res = detect_conflicts(claims, facts)
    assert res.findings[0].conflict_type == CONFLICT_COMPETITIVE_EVIDENCE


def test_conflict_competitive_evidence_strong_supports():
    """竞争 Fact 含"市场份额/第一"等强证据 → NO_OPPOSITION。"""
    claims = [InvestmentClaim(claim_id="INV-0001", claim="公司保持行业领先",
                              dimension=FACT_DIM_COMPETITION)]
    facts = [_make_fact(dimension=FACT_DIM_COMPETITION, value=None,
                        statement="美的空调线上线下市场份额第一",
                        evidence="美的空调线上线下市场份额第一。")]
    res = detect_conflicts(claims, facts)
    assert res.findings[0].conflict_type == CONFLICT_NO_OPPOSITION


def test_finding_has_unique_ids():
    claims = [InvestmentClaim(claim_id=f"INV-{i}", claim="领先", dimension=FACT_DIM_COMPETITION)
              for i in range(3)]
    facts = []
    res = detect_conflicts(claims, facts)
    ids = [f.finding_id for f in res.findings]
    assert len(set(ids)) == len(ids)
    assert all(fid.startswith("CFLT-") for fid in ids)


def test_compute_overall_risk_formula():
    """整体风险：0.5×最高 + 0.5×冲突平均，无冲突=0。"""
    from app.services.intelligence.schemas import ConflictFinding
    f1 = ConflictFinding(finding_id="CFLT-1", claim_id="c1", fact_id="f1",
                         claim="x", fact="y", conflict_type=CONFLICT_FINANCIAL_DATA,
                         difference="d", risk_score=80.0, risk_level="HIGH")
    f2 = ConflictFinding(finding_id="CFLT-2", claim_id="c2", fact_id="f2",
                         claim="x", fact="y", conflict_type=CONFLICT_BUSINESS_DESC,
                         difference="d", risk_score=60.0, risk_level="MEDIUM")
    score, level = compute_overall_risk([f1, f2])
    # 0.5*80 + 0.5*((80+60)/2) = 40 + 35 = 75
    assert score == 75.0
    assert level == "HIGH"
    # 无冲突 → 0 LOW
    assert compute_overall_risk([]) == (0.0, "LOW")


# ---------------------------------------------------------------------------
# §7.3 Evidence Trace（Claim ↓ Evidence ↓ Conflict ↓ Risk）
# ---------------------------------------------------------------------------
def test_evidence_chain_structure():
    """证据链每条含 claim / evidence / conflict_type / risk。"""
    claims = [InvestmentClaim(claim_id="INV-0001", claim="海外业务高速增长",
                              dimension=FACT_DIM_MARKET)]
    facts = [_make_fact(dimension=FACT_DIM_MARKET, value=None,
                        statement="海外业务增长", source=FACT_SOURCE_NEWS,
                        source_label="新闻", evidence="海外业务持续增长。")]
    detection = detect_conflicts(claims, facts)
    chain = build_evidence_chain(claims, facts, detection.findings)
    assert len(chain) == 1
    item = chain[0]
    assert item["claim_id"] == "INV-0001"
    assert "conflict_type" in item
    assert "risk_score" in item
    assert isinstance(item["evidence"], list)


def test_company_profile_aggregation():
    """Company Profile 从 Facts 聚合。"""
    facts = [
        _make_fact(dimension=FACT_DIM_BUSINESS, value=None, subject="暖通空调",
                   statement="主营业务包括暖通空调"),
        _make_fact(dimension=FACT_DIM_PRODUCT, value=None, subject="空调",
                   statement="空调产品"),
        _make_fact(dimension=FACT_DIM_COMPETITION, value=None,
                   statement="对手为海尔、格力", evidence="海尔格力"),
    ]
    profile = build_company_profile("美的集团", "000333", facts)
    assert profile.company == "美的集团"
    assert "暖通空调" in profile.business_fields
    assert "空调" in profile.products
    assert any(c in profile.competitors for c in ("海尔", "格力"))


# ---------------------------------------------------------------------------
# §7.4 Intelligence Workflow（端到端）
# ---------------------------------------------------------------------------
def test_run_investigation_end_to_end(financial_doc):
    """run_investigation：投资观点 + 外部事实 → 报告（含 conflicts/risk/evidence）。"""
    claims = [
        InvestmentClaim(claim_id="INV-0001", claim="海外业务高速增长",
                        dimension=FACT_DIM_MARKET, period="2025FY"),
        InvestmentClaim(claim_id="INV-0002", claim="公司保持行业领先",
                        dimension=FACT_DIM_COMPETITION, period="2025FY"),
        InvestmentClaim(claim_id="INV-0003", claim="盈利能力持续提升",
                        dimension=FACT_DIM_FINANCIAL, period="2025FY"),
    ]
    external_facts = [
        {
            "dimension": FACT_DIM_FINANCIAL, "subject": "美的", "statement": "归母净利润预增",
            "source": FACT_SOURCE_ANNOUNCEMENT, "source_label": "业绩预增公告",
            "evidence": "公司发布业绩预增公告。", "timestamp": "2026-07-21T00:00:00Z",
            "confidence": 0.85,
        },
        {
            "dimension": FACT_DIM_COMPETITION, "subject": "美的空调",
            "statement": "美的空调线上线下市场份额第一",
            "source": FACT_SOURCE_NEWS, "source_label": "行业第三方报告",
            "evidence": "美的空调线上线下市场份额均位列第一。",
            "timestamp": "2026-07-28T00:00:00Z", "confidence": 0.75,
        },
    ]
    with SessionLocal() as s:
        report = run_investigation(s, financial_doc, claims,
                                   external_fact_records=external_facts)
        d = report.to_dict()
        assert d["company"] == "美的集团"
        assert d["stock_code"] == "000333"
        # 至少有 1 条 conflict 或 1 条 support
        assert (d["conflict_count"] + d["support_count"]) >= 1
        # Verified Facts 至少含财报抽取的若干条
        assert len(d["verified_facts"]) >= 1
        # Evidence Chain 与 claims 数量一致
        assert len(d["evidence_chain"]) == len(claims)


def test_save_and_get_report_persistence(financial_doc):
    """save_report / get_report：报告持久化并可读回。"""
    claims = [
        InvestmentClaim(claim_id="INV-0001", claim="海外业务高速增长",
                        dimension=FACT_DIM_MARKET, period="2025FY"),
    ]
    with SessionLocal() as s:
        report = run_investigation(s, financial_doc, claims)
        report = save_report(s, report)
        rid = report.id
        assert rid is not None

    with SessionLocal() as s:
        loaded = get_report(s, rid)
        assert loaded.company == "美的集团"
        assert loaded.conflict_count == report.conflict_count
        assert loaded.overall_risk_score == report.overall_risk_score
        # Company Profile 还原
        assert loaded.company_profile.company == "美的集团"


def test_get_report_raises_on_missing():
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            get_report(s, 99999)


def test_run_investigation_raises_on_missing_doc():
    claims = [InvestmentClaim(claim_id="INV-0001", claim="x")]
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            run_investigation(s, 99999, claims)


# ---------------------------------------------------------------------------
# §7.5 Evidence First 边界：登记外部事实字典列表
# ---------------------------------------------------------------------------
def test_register_external_facts_from_dicts_assigns_unique_ids():
    records = [
        {
            "dimension": FACT_DIM_FINANCIAL, "statement": "营收 100 亿",
            "source": FACT_SOURCE_ANNOUNCEMENT, "evidence": "公告",
            "timestamp": "2026-07-31T00:00:00Z", "confidence": 0.8,
        },
        {
            "dimension": FACT_DIM_MARKET, "statement": "海外业务增长",
            "source": FACT_SOURCE_NEWS, "evidence": "新闻",
            "timestamp": "2026-07-31T00:00:00Z", "confidence": 0.7,
        },
    ]
    facts = register_external_facts_from_dicts([], records)
    assert len(facts) == 2
    ids = [f.fact_id for f in facts]
    assert len(set(ids)) == len(ids)


def test_register_external_facts_rejects_missing_source():
    with pytest.raises(ValueError):
        register_external_fact(
            existing_ids=[],
            dimension=FACT_DIM_FINANCIAL, subject="x", statement="s",
            source="", source_label="", evidence="e",
            timestamp="2026-07-31T00:00:00Z", confidence=0.8,
        )


# ---------------------------------------------------------------------------
# §7.6 Intelligence API
# ---------------------------------------------------------------------------
def test_intelligence_api_run_and_get(financial_doc):
    """Intelligence API：POST /runs / GET /runs/{id}。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    body = {
        "document_id": financial_doc,
        "claims": [
            {"claim_id": "INV-0001", "claim": "海外业务高速增长",
             "dimension": "MARKET", "period": "2025FY"},
            {"claim_id": "INV-0002", "claim": "公司保持行业领先",
             "dimension": "COMPETITION", "period": "2025FY"},
            {"claim_id": "INV-0003", "claim": "盈利能力持续提升",
             "dimension": "FINANCIAL", "period": "2025FY"},
        ],
        "external_facts": [
            {"dimension": "COMPETITION", "subject": "美的空调",
             "statement": "美的空调线上线下市场份额第一",
             "source": "NEWS", "source_label": "行业第三方报告",
             "evidence": "美的空调线上线下市场份额均位列第一。",
             "timestamp": "2026-07-28T00:00:00Z", "confidence": 0.75},
        ],
    }
    r = client.post("/api/v1/intelligence/runs", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["company"] == "美的集团"
    assert "conflicts" in data and "verified_facts" in data
    rid = data["id"]

    r2 = client.get(f"/api/v1/intelligence/runs/{rid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == rid


def test_intelligence_api_404_on_missing_doc():
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    body = {"document_id": 99999, "claims": [], "external_facts": []}
    r = client.post("/api/v1/intelligence/runs", json=body)
    assert r.status_code == 404


def test_intelligence_api_get_404_on_missing_report():
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    assert client.get("/api/v1/intelligence/runs/99999").status_code == 404
