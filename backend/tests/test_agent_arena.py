"""FinProof Financial AI Agent Arena Tests（Phase 19）。

覆盖（任务书 §Testing）：
- arena workflow 测试      Analyst → Skeptic → Auditor → Judge 端到端
- agent communication 测试  角色间消息传递
- scoring 测试             5 项子分 + Final Arena Score
- API 测试                 POST /api/v1/arena/run + GET /api/v1/arena/{id}
- frontend guard           禁止词护栏
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.services.agent_arena import (
    audit_debate,
    challenge_viewpoints,
    contains_forbidden_content,
    decide_winner,
    generate_viewpoints,
    score_arena,
)
from app.services.agent_arena.schemas import (
    AnalystViewpoint,
    ArenaScore,
    AuditorReport,
    CHALLENGE_CONTRADICTORY_FACTS,
    CHALLENGE_GROWTH_QUALITY,
    CHALLENGE_MISSING_EVIDENCE,
    CHALLENGE_OVERSTATEMENT,
    CHALLENGE_UNSUPPORTED_CLAIM,
    EvidenceRef,
    PHASE_AUDITOR_VERIFIES,
    PHASE_JUDGE_SCORES,
    PHASE_ORDER,
    PHASE_SKEPTIC_ATTACKS,
    PHASE_ANALYST,
    PHARE_DONE,
    ROLE_ANALYST,
    ROLE_AUDITOR,
    ROLE_JUDGE,
    ROLE_SKEPTIC,
    SkepticChallenge,
)


def _fresh_db():
    init_db()


def _vp(claim: str, evidence: list[EvidenceRef] | None = None, unsupported: bool = False, confidence: float = 0.9, metric: str = "revenue", vid: str = "AV-001") -> AnalystViewpoint:
    return AnalystViewpoint(
        viewpoint_id=vid,
        claim=claim,
        evidence=evidence or [],
        confidence=confidence,
        metric=metric,
        unsupported=unsupported,
    )


# ---------------------------------------------------------------------------
# 1. Arena workflow 端到端
# ---------------------------------------------------------------------------
def test_run_arena_end_to_end_persists():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena, get_arena
    with SessionLocal() as s:
        run = run_arena(s, "美的集团", "美的海外增长是否可持续")
        assert run.run_id.startswith("ARENA-")
        assert run.phase == PHARE_DONE
        assert run.result is not None
        assert run.result.score.final_arena_score >= 0.0
        # 4 角色 message
        roles = [m.role for m in run.messages]
        assert ROLE_ANALYST in roles
        assert ROLE_SKEPTIC in roles
        assert ROLE_AUDITOR in roles
        assert ROLE_JUDGE in roles
        # 持久化查询
        from app.models.agent_arena import ArenaRunRow
        row = s.query(ArenaRunRow).filter(ArenaRunRow.run_id == run.run_id).first()
        db_id = row.id
        fetched = get_arena(s, db_id)
        assert fetched.company == "美的集团"


def test_run_arena_rejects_empty_inputs():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        with pytest.raises(ValueError):
            run_arena(s, "", "问题")
        with pytest.raises(ValueError):
            run_arena(s, "公司", "")


# ---------------------------------------------------------------------------
# 2. Agent communication（角色间消息传递）
# ---------------------------------------------------------------------------
def test_agent_messages_phases_in_order():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "测试公司", "增长是否可持续")
    phases = [m.phase for m in run.messages]
    # Analyst → Skeptic → Auditor → Judge
    assert phases[0] == PHASE_ANALYST
    assert phases[1] == PHASE_SKEPTIC_ATTACKS
    assert phases[2] == PHASE_AUDITOR_VERIFIES
    assert phases[3] == PHASE_JUDGE_SCORES


def test_skeptic_targets_analyst_viewpoints():
    _fresh_db()
    vps = [
        _vp("海外收入增长，因此海外业务是利润增长核心", evidence=[EvidenceRef(block_id=1, text="海外收入同比增10%")], unsupported=False, confidence=0.7, vid="AV-001"),
        _vp("公司增长，但无证据", evidence=[], unsupported=True, vid="AV-002"),
    ]
    with SessionLocal() as s:
        challenges, msg = challenge_viewpoints(s, vps, "测试公司")
    # 挑战指向具体 viewpoint_id
    assert all(c.target_viewpoint_id for c in challenges)
    # 无证据观点被 Unsupported Claim 挑战
    unsupported_challenges = [c for c in challenges if c.challenge_type == CHALLENGE_UNSUPPORTED_CLAIM]
    assert any(c.target_viewpoint_id == "AV-002" for c in unsupported_challenges)


def test_auditor_judges_challenge_validity():
    vps = [
        _vp("海外收入增长", evidence=[EvidenceRef(block_id=1, text="海外收入同比增10%")], vid="AV-001"),
        _vp("无证据观点", evidence=[], unsupported=True, vid="AV-002"),
    ]
    challenges = [
        SkepticChallenge(challenge_id="SC-001", target_viewpoint_id="AV-002", challenge_type=CHALLENGE_UNSUPPORTED_CLAIM, counter_claim="无证据", valid=True),
        SkepticChallenge(challenge_id="SC-002", target_viewpoint_id="AV-001", challenge_type="", counter_claim="", missing_evidence="", valid=True),  # 无内容 → 应判 invalid
    ]
    report, msg = audit_debate(vps, challenges, [])
    # 无内容的挑战被判 invalid
    assert "SC-002" in report.invalid_challenges
    # 针对无证据观点的挑战判 valid
    assert "SC-001" in report.valid_challenges


# ---------------------------------------------------------------------------
# 3. Scoring
# ---------------------------------------------------------------------------
def test_score_arena_full_evidence_no_forbidden():
    vps = [
        _vp("海外收入同比增长10%", evidence=[EvidenceRef(block_id=1, text="海外收入同比增10%")], unsupported=False, confidence=0.9, vid="AV-001"),
        _vp("净利润同比增长5%", evidence=[EvidenceRef(block_id=2, text="净利润同比增5%")], unsupported=False, confidence=0.85, vid="AV-002"),
    ]
    challenges: list[SkepticChallenge] = []
    auditor = AuditorReport(
        audit_score=90.0, evidence_coverage=1.0, logical_consistency=1.0, risk_completeness=1.0,
        valid_challenges=[], invalid_challenges=[], issues=[],
    )
    score = score_arena(vps, challenges, auditor, tool_call_count=8)
    assert 0.0 <= score.final_arena_score <= 100.0
    # 全证据覆盖 + 无禁止词 → safety 满分
    assert score.safety_score.score == 100.0
    assert score.evidence_score.score == 100.0


def test_score_arena_forbidden_word_zero_safety():
    vps = [
        _vp("建议买入该公司，目标价50元", evidence=[EvidenceRef(block_id=1, text="营收")], unsupported=False, vid="AV-001"),
    ]
    auditor = AuditorReport(audit_score=50.0, evidence_coverage=1.0, logical_consistency=1.0, risk_completeness=1.0, issues=[])
    score = score_arena(vps, [], auditor, tool_call_count=5)
    # 禁止词零容忍 → safety = 0
    assert score.safety_score.score == 0.0


def test_score_arena_efficiency_penalizes_redundant_calls():
    vps = [_vp("增长", evidence=[EvidenceRef(block_id=1, text="增长")], vid="AV-001")]
    auditor = AuditorReport(audit_score=80.0, evidence_coverage=1.0, logical_consistency=1.0, risk_completeness=1.0, issues=[])
    score = score_arena(vps, [], auditor, tool_call_count=30)  # 冗余
    assert score.efficiency_score.score < 100.0
    score2 = score_arena(vps, [], auditor, tool_call_count=10)
    assert score2.efficiency_score.score == 100.0


def test_decide_winner_skeptic_when_many_valid_challenges():
    vps = [
        _vp("增长", evidence=[EvidenceRef(block_id=1, text="增长")], vid="AV-001"),
        _vp("领先", evidence=[], unsupported=True, vid="AV-002"),
        _vp("核心", evidence=[EvidenceRef(block_id=2, text="核心")], vid="AV-003"),
    ]
    challenges = [
        SkepticChallenge(challenge_id="SC-1", target_viewpoint_id="AV-002", challenge_type=CHALLENGE_UNSUPPORTED_CLAIM, counter_claim="无证据", valid=True),
        SkepticChallenge(challenge_id="SC-2", target_viewpoint_id="AV-001", challenge_type=CHALLENGE_GROWTH_QUALITY, counter_claim="现金流", valid=True),
    ]
    auditor = AuditorReport(audit_score=60.0, evidence_coverage=0.66, logical_consistency=1.0, risk_completeness=1.0, valid_challenges=["SC-1", "SC-2"], invalid_challenges=[])
    score = score_arena(vps, challenges, auditor, tool_call_count=8)
    winner = decide_winner(score, vps, challenges, auditor)
    # 命中率 2/3 >= 0.5 → skeptic
    assert winner == "skeptic"


def test_decide_winner_analyst_when_high_evidence_low_challenges():
    vps = [
        _vp("增长", evidence=[EvidenceRef(block_id=1, text="增长")], vid="AV-001"),
        _vp("利润", evidence=[EvidenceRef(block_id=2, text="利润")], vid="AV-002"),
    ]
    auditor = AuditorReport(audit_score=90.0, evidence_coverage=1.0, logical_consistency=1.0, risk_completeness=1.0, valid_challenges=[], invalid_challenges=[])
    score = score_arena(vps, [], auditor, tool_call_count=6)
    winner = decide_winner(score, vps, [], auditor)
    assert winner == "analyst"


# ---------------------------------------------------------------------------
# 4. Skeptic 挑战类型覆盖
# ---------------------------------------------------------------------------
def test_skeptic_detects_overstatement():
    vps = [_vp("海外业务是利润增长核心引擎", evidence=[EvidenceRef(block_id=1, text="海外收入增")], confidence=0.6, vid="AV-001")]
    with SessionLocal() as s:
        challenges, _ = challenge_viewpoints(s, vps, "测试公司")
    types = [c.challenge_type for c in challenges]
    # 含强表述 + 低置信 → 至少触发 Overstatement 或 Reasoning 相关
    assert any(t in types for t in (CHALLENGE_OVERSTATEMENT, CHALLENGE_MISSING_EVIDENCE))


def test_skeptic_detects_missing_evidence():
    vps = [_vp("经营现金流改善", evidence=[EvidenceRef(block_id=1, text="营收增长")], vid="AV-001")]  # 证据不含现金流
    with SessionLocal() as s:
        challenges, _ = challenge_viewpoints(s, vps, "测试公司")
    types = [c.challenge_type for c in challenges]
    assert CHALLENGE_MISSING_EVIDENCE in types


def test_skeptic_detects_growth_quality_risk():
    vps = [_vp("营收增长", evidence=[EvidenceRef(block_id=1, text="营收同比增10% 经营现金流同比下降20% 应收账款同比上升")], vid="AV-001")]
    with SessionLocal() as s:
        challenges, _ = challenge_viewpoints(s, vps, "测试公司")
    types = [c.challenge_type for c in challenges]
    assert CHALLENGE_GROWTH_QUALITY in types


def test_skeptic_detects_contradictory_facts():
    vps = [_vp("海外利润增长", evidence=[EvidenceRef(block_id=1, text="海外利润同比下滑5%")], vid="AV-001")]
    with SessionLocal() as s:
        challenges, _ = challenge_viewpoints(s, vps, "测试公司")
    types = [c.challenge_type for c in challenges]
    assert CHALLENGE_CONTRADICTORY_FACTS in types


# ---------------------------------------------------------------------------
# 5. Analyst
# ---------------------------------------------------------------------------
def test_analyst_every_viewpoint_bound_or_unsupported():
    _fresh_db()
    with SessionLocal() as s:
        vps, evs, msg = generate_viewpoints(s, "测试公司AN", "增长是否可持续")
    # 每个观点：要么有证据，要么 unsupported=True（不凭空生成假事实）
    for v in vps:
        if not v.evidence:
            assert v.unsupported


def test_analyst_no_forbidden_in_claims():
    _fresh_db()
    with SessionLocal() as s:
        vps, evs, msg = generate_viewpoints(s, "测试公司NB", "增长是否可持续")
    for v in vps:
        assert not contains_forbidden_content(v.claim)


# ---------------------------------------------------------------------------
# 6. API
# ---------------------------------------------------------------------------
def test_api_run_and_get():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/arena/run", json={"company": "API测试公司", "research_question": "海外增长是否可持续"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["run_id"].startswith("ARENA-")
    assert body["phase"] == "Done"
    assert body["result"] is not None
    assert "final_arena_score" in body["result"]["score"]

    from app.models.agent_arena import ArenaRunRow
    with SessionLocal() as s:
        row = s.query(ArenaRunRow).filter(ArenaRunRow.run_id == body["run_id"]).first()
        db_id = row.id

    r = client.get(f"/api/v1/arena/{db_id}")
    assert r.status_code == 200
    body2 = r.json()
    assert body2["company"] == "API测试公司"
    assert len(body2["messages"]) >= 4  # 4 角色 message


def test_api_list():
    _fresh_db()
    client = TestClient(app)
    client.post("/api/v1/arena/run", json={"company": "列表公司A", "research_question": "增长是否可持续"})
    r = client.get("/api/v1/arena")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_api_run_rejects_empty():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/arena/run", json={"company": "", "research_question": "x"})
    assert r.status_code in (400, 422)


def test_api_get_not_found():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/arena/999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 7. Frontend guard
# ---------------------------------------------------------------------------
def test_contains_forbidden_content():
    assert contains_forbidden_content("建议买入该公司")
    assert contains_forbidden_content("目标价50元")
    assert contains_forbidden_content("卖出信号")
    assert not contains_forbidden_content("海外收入同比增长10%")
    # 否定式免责不误判
    assert not contains_forbidden_content("本结论不构成投资建议")


# ---------------------------------------------------------------------------
# 8. Phase order
# ---------------------------------------------------------------------------
def test_phase_order():
    assert PHASE_ORDER[0] == PHASE_ANALYST
    assert PHASE_ORDER[-1] == PHARE_DONE
    assert len(PHASE_ORDER) == 5
