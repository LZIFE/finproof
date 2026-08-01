"""FinProof AI Audit Replay Timeline Tests（Phase 21）。

覆盖（任务书 §Testing）：
- replay collector 测试    5 类事件聚合（claim/evidence/verification/risk/agent/conclusion）
- API 测试                 GET /api/v1/replay/{audit_id} + POST /build + GET /list
- 空输入 / 缺失 audit_id 边界
- 持久化测试               build → get 一致
- 护栏                     禁止词；不增加投资建议；所有内容来自已有数据
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.services.replay import (
    EVENT_AGENT,
    EVENT_CLAIM,
    EVENT_CONCLUSION,
    EVENT_EVIDENCE,
    EVENT_RISK,
    EVENT_TYPES,
    EVENT_VERIFICATION,
    TIMELINE_ORDER,
    build_replay,
    collect_events,
    contains_forbidden_content,
    get_replay,
    list_replay,
)


def _fresh_db():
    init_db()


# ---------------------------------------------------------------------------
# 1. Collector 测试（5 类事件聚合）
# ---------------------------------------------------------------------------
def test_collect_events_empty_for_unknown_audit_id():
    _fresh_db()
    with SessionLocal() as s:
        evs = collect_events(s, "NO-SUCH-AUDIT-999")
    assert evs == []


def test_collect_events_rejects_empty_audit_id():
    _fresh_db()
    with SessionLocal() as s:
        evs = collect_events(s, "")
    assert evs == []


def test_collect_events_from_arena_run():
    """Arena Run → claim/evidence/agent/conclusion 事件。"""
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "回放测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    with SessionLocal() as s:
        evs = collect_events(s, audit_id)
    types = {e.event_type for e in evs}
    # Arena 至少产生 claim / agent / conclusion 事件
    assert EVENT_CLAIM in types
    assert EVENT_AGENT in types
    assert EVENT_CONCLUSION in types
    # 时间线顺序：claim 应在 agent/conclusion 之前
    order_idx = {t: i for i, t in enumerate(TIMELINE_ORDER)}
    claim_pos = min((order_idx[e.event_type] for e in evs if e.event_type == EVENT_CLAIM), default=99)
    agent_pos = min((order_idx[e.event_type] for e in evs if e.event_type == EVENT_AGENT), default=99)
    assert claim_pos < agent_pos


def test_collect_events_from_research_session():
    """Research Session → claim/evidence 事件。"""
    _fresh_db()
    from app.services.research_agent.orchestrator import run_research
    with SessionLocal() as s:
        rs = run_research(s, "回放研究公司", "")
        audit_id = rs.session_id
    with SessionLocal() as s:
        evs = collect_events(s, audit_id)
    types = {e.event_type for e in evs}
    assert EVENT_CLAIM in types
    # Research 产出证据链 → 至少有 evidence 或 claim
    assert EVENT_CLAIM in types or EVENT_EVIDENCE in types


def test_collect_events_each_step_has_source_evidence_result():
    """每一步必须显示 来源/证据/结果（任务书 §前端）—— collector 字段齐全。"""
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "字段测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    with SessionLocal() as s:
        evs = collect_events(s, audit_id)
    # 非空事件必须含 actor（来源）/ evidence_reference / result_summary
    for e in evs:
        assert e.actor  # 来源
        assert e.content  # 结果
        # evidence_reference 可为空字符串但字段必须存在
        assert hasattr(e, "evidence_reference")


# ---------------------------------------------------------------------------
# 2. Service 测试（build / get / 持久化）
# ---------------------------------------------------------------------------
def test_build_replay_persists_and_get_returns_same():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "持久化测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    with SessionLocal() as s:
        built = build_replay(s, audit_id, persist=True)
        assert built.total_events > 0
        assert built.audit_id == audit_id
    # get_replay 应返回已持久化的事件
    with SessionLocal() as s:
        fetched = get_replay(s, audit_id)
        assert fetched.total_events == built.total_events
    # 持久化到 audit_replay_events
    from app.models.replay import AuditReplayEventRow
    with SessionLocal() as s:
        cnt = s.query(AuditReplayEventRow).filter(AuditReplayEventRow.audit_id == audit_id).count()
        assert cnt == built.total_events


def test_build_replay_no_duplicate_persist():
    """同 audit_id 重复 build 不应重复写入。"""
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "去重测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    with SessionLocal() as s:
        built1 = build_replay(s, audit_id, persist=True)
    with SessionLocal() as s:
        built2 = build_replay(s, audit_id, persist=True)
    assert built1.total_events == built2.total_events
    from app.models.replay import AuditReplayEventRow
    with SessionLocal() as s:
        cnt = s.query(AuditReplayEventRow).filter(AuditReplayEventRow.audit_id == audit_id).count()
        assert cnt == built1.total_events  # 不翻倍


def test_get_replay_empty_for_unknown_audit_id():
    _fresh_db()
    with SessionLocal() as s:
        tl = get_replay(s, "NO-SUCH-REPLAY-999")
    assert tl.total_events == 0
    assert tl.events == []


def test_build_replay_rejects_empty_audit_id():
    _fresh_db()
    with SessionLocal() as s:
        with pytest.raises(ValueError):
            build_replay(s, "")


def test_list_replay_returns_metadata():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "列表测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    with SessionLocal() as s:
        build_replay(s, audit_id, persist=True)
    with SessionLocal() as s:
        items = list_replay(s, limit=50)
    audit_ids = [i["audit_id"] for i in items]
    assert audit_id in audit_ids


# ---------------------------------------------------------------------------
# 3. API 测试
# ---------------------------------------------------------------------------
def test_api_get_replay_builds_if_missing():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "API测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    client = TestClient(app)
    r = client.get(f"/api/v1/replay/{audit_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audit_id"] == audit_id
    assert body["total_events"] > 0
    # 6 步顺序齐全
    assert "step_order" in body
    assert len(body["step_order"]) == 6
    # steps 字典含全部 6 类
    for et in EVENT_TYPES:
        assert et in body["steps"]


def test_api_post_build():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "API Build 测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    client = TestClient(app)
    r = client.post(f"/api/v1/replay/{audit_id}/build")
    assert r.status_code == 201, r.text
    assert r.json()["total_events"] > 0


def test_api_list_replays():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "列表 API 测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    client = TestClient(app)
    client.post(f"/api/v1/replay/{audit_id}/build")
    r = client.get("/api/v1/replay")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_api_get_replay_unknown_returns_empty_timeline():
    """缺失 audit_id → 自动构建返回空时间线（200，不 404）。"""
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/replay/NO-SUCH-AUDIT-EMPTY-001")
    assert r.status_code == 200
    assert r.json()["total_events"] == 0


# ---------------------------------------------------------------------------
# 4. Timeline 顺序与结构
# ---------------------------------------------------------------------------
def test_timeline_order_is_6_steps():
    assert TIMELINE_ORDER == [
        EVENT_CLAIM, EVENT_EVIDENCE, EVENT_VERIFICATION,
        EVENT_RISK, EVENT_AGENT, EVENT_CONCLUSION,
    ]
    assert len(TIMELINE_ORDER) == 6


def test_event_types_complete():
    assert EVENT_TYPES == {
        EVENT_CLAIM, EVENT_EVIDENCE, EVENT_VERIFICATION,
        EVENT_RISK, EVENT_AGENT, EVENT_CONCLUSION,
    }


def test_replay_timeline_steps_partition_events():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "分步测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    with SessionLocal() as s:
        tl = build_replay(s, audit_id, persist=False)
    # steps 字典应将事件按类型分桶
    total_in_steps = sum(len(v) for v in tl.steps.values())
    assert total_in_steps == tl.total_events


# ---------------------------------------------------------------------------
# 5. 护栏
# ---------------------------------------------------------------------------
def test_contains_forbidden_content():
    assert contains_forbidden_content("建议买入该公司")
    assert contains_forbidden_content("目标价50元")
    assert not contains_forbidden_content("海外收入同比增长10%")
    # 否定式免责不误判
    assert not contains_forbidden_content("本结论不构成投资建议")


def test_replay_events_no_forbidden_in_actor_content():
    """回放事件 actor/content 不应含禁止词（投资建议/股票推荐/估值预测）。

    注：证据原文可能含合规字样（如"卖出回笼"），不在此检查范围。
    """
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "护栏测试公司", "海外增长是否可持续")
        audit_id = run.run_id
    with SessionLocal() as s:
        evs = collect_events(s, audit_id)
    for e in evs:
        # actor 是来源标识，不应含禁止词
        assert not contains_forbidden_content(e.actor)
        # conclusion 事件的 content 不应含禁止词（Arena Judge 文本已含护栏）
        if e.event_type == EVENT_CONCLUSION:
            assert not contains_forbidden_content(e.content)
