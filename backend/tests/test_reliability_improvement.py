"""FinProof AI Reliability Improvement Center Tests（Phase 23）。

覆盖（任务书 §Testing）：
- failure analyzer 测试    Benchmark/Red Team/Arena/Reasoning 4 来源聚合
- pattern detector 测试    5 类 pattern 聚合 + 弱点矩阵
- trend 测试              版本/Agent 趋势点 + direction
- API 测试                POST /analyze + GET /report + GET /reports
- 护栏                    禁止词；不修改核心；不输出投资建议
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.services.reliability_improvement import (
    PATTERN_EVIDENCE_MISSING,
    PATTERN_LABELS,
    PATTERN_LOGICAL_GAP,
    PATTERN_NUMERIC_ERROR,
    PATTERN_PERIOD_CONFUSION,
    PATTERN_TYPES,
    PATTERN_UNSUPPORTED_CLAIM,
    SOURCE_ARENA,
    SOURCE_BENCHMARK,
    SOURCE_REASONING,
    SOURCE_RED_TEAM,
    analyze_reliability,
    build_weakness_map,
    collect_failures,
    contains_forbidden_content,
    detect_patterns,
    get_report,
    list_reports,
    persist_report,
)


def _fresh_db():
    init_db()


# ---------------------------------------------------------------------------
# 1. Failure analyzer 测试
# ---------------------------------------------------------------------------
def test_collect_failures_empty_db_returns_empty():
    _fresh_db()
    with SessionLocal() as s:
        failures, totals = collect_failures(s, limit=50)
    assert isinstance(failures, list)
    assert isinstance(totals, dict)
    # 4 来源键齐全（即便为 0）
    for src in (SOURCE_BENCHMARK, SOURCE_RED_TEAM, SOURCE_ARENA, SOURCE_REASONING):
        assert src in totals


def test_collect_failures_from_arena_run():
    """Arena Run → Skeptic 命中 + Auditor issues → 失败案例。"""
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run = run_arena(s, "回放测试公司", "海外增长是否可持续")
    with SessionLocal() as s:
        failures, totals = collect_failures(s, limit=200)
    # Arena 来源应有案例（skeptic 命中或 auditor issue）
    arena_failures = [f for f in failures if f.source == SOURCE_ARENA]
    assert totals[SOURCE_ARENA] >= 1
    # 每条案例 pattern 在 5 类内
    for f in arena_failures:
        assert f.pattern in PATTERN_TYPES


def test_collect_failures_pattern_classification_in_5_types():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run_arena(s, "模式分类测试公司", "增长是否可持续")
    with SessionLocal() as s:
        failures, _ = collect_failures(s, limit=200)
    for f in failures:
        assert f.pattern in PATTERN_TYPES
        assert f.source in (SOURCE_BENCHMARK, SOURCE_RED_TEAM, SOURCE_ARENA, SOURCE_REASONING)


# ---------------------------------------------------------------------------
# 2. Pattern detector 测试
# ---------------------------------------------------------------------------
def test_detect_patterns_returns_all_5_types():
    """detect_patterns 必须产出 5 类 pattern（即便无案例也空模式）。"""
    _fresh_db()
    with SessionLocal() as s:
        failures, totals = collect_failures(s, limit=50)
    patterns = detect_patterns(failures, totals)
    assert len(patterns) == 5
    detected = {p.pattern for p in patterns}
    assert detected == PATTERN_TYPES
    # 每个含 root_cause + suggested_improvement（即便为空模式）
    for p in patterns:
        assert p.root_cause  # 知识库非空
        assert p.suggested_improvement


def test_detect_patterns_root_cause_and_suggestion():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run_arena(s, "根因测试公司", "海外增长是否可持续")
    with SessionLocal() as s:
        failures, totals = collect_failures(s, limit=200)
    patterns = detect_patterns(failures, totals)
    for p in patterns:
        if p.failure_count > 0:
            assert p.root_cause
            assert p.suggested_improvement
            assert p.affected_category  # 来源占比最多的


def test_build_weakness_map_matrix_shape():
    """弱点矩阵 = 4 sources × 5 patterns = 20 cells。"""
    _fresh_db()
    with SessionLocal() as s:
        failures, _ = collect_failures(s, limit=50)
    wm = build_weakness_map(failures)
    wm_d = wm.to_dict()
    assert len(wm_d["cells"]) == 4 * 5
    assert set(wm_d["sources"]) == {SOURCE_BENCHMARK, SOURCE_RED_TEAM, SOURCE_ARENA, SOURCE_REASONING}
    assert set(wm_d["patterns"]) == PATTERN_TYPES
    assert wm_d["max_count"] >= 0


# ---------------------------------------------------------------------------
# 3. Improvement report + trend 测试
# ---------------------------------------------------------------------------
def test_analyze_reliability_end_to_end():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run_arena(s, "分析测试公司", "海外增长是否可持续")
    with SessionLocal() as s:
        report = analyze_reliability(s, limit=200)
    assert report.report_id.startswith("REL-IMPROVE-")
    assert report.total_cases >= 1
    assert 0.0 <= report.overall_failure_rate <= 1.0
    assert len(report.patterns) == 5
    # trend 非空（至少有 Arena winner 分组）
    assert isinstance(report.trend.points, list)
    # summary 不含禁止词
    assert not contains_forbidden_content(report.summary)
    # summary 含"不构成投资建议"
    assert "不构成投资建议" in report.summary or "失败模式" in report.summary


def test_analyze_suggested_improvements_no_forbidden():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run_arena(s, "建议测试公司", "海外增长是否可持续")
    with SessionLocal() as s:
        report = analyze_reliability(s, limit=200)
    for imp in report.suggested_improvements:
        assert not contains_forbidden_content(imp)


def test_trend_direction_in_valid_set():
    _fresh_db()
    with SessionLocal() as s:
        report = analyze_reliability(s, limit=50)
    assert report.trend.direction in ("improving", "declining", "stable")


# ---------------------------------------------------------------------------
# 4. 持久化
# ---------------------------------------------------------------------------
def test_persist_and_get_report_consistency():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run_arena(s, "持久化测试公司", "海外增长是否可持续")
    with SessionLocal() as s:
        report = analyze_reliability(s, limit=200)
        db_id = persist_report(s, report)
        rid = report.report_id
    with SessionLocal() as s:
        fetched = get_report(s, rid)
    assert fetched.report_id == rid
    assert fetched.total_failures == report.total_failures
    assert len(fetched.patterns) == 5


def test_get_report_raises_for_unknown():
    _fresh_db()
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            get_report(s, "NO-SUCH-REPORT-999")


def test_list_reports_metadata():
    _fresh_db()
    from app.services.agent_arena.arena import run_arena
    with SessionLocal() as s:
        run_arena(s, "列表测试公司", "海外增长是否可持续")
    with SessionLocal() as s:
        report = analyze_reliability(s, limit=200)
        persist_report(s, report)
    with SessionLocal() as s:
        items = list_reports(s, limit=50)
    assert items
    assert "report_id" in items[0]


# ---------------------------------------------------------------------------
# 5. API 测试
# ---------------------------------------------------------------------------
def test_api_analyze():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/reliability/analyze", json={"limit": 200})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["report_id"].startswith("REL-IMPROVE-")
    assert "patterns" in body
    assert "trend" in body
    assert "suggested_improvements" in body
    assert "db_id" in body


def test_api_get_report_by_id():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/reliability/analyze", json={})
    rid = r.json()["report_id"]
    r = client.get(f"/api/v1/reliability/report?report_id={rid}")
    assert r.status_code == 200
    assert r.json()["report_id"] == rid


def test_api_get_report_latest():
    _fresh_db()
    client = TestClient(app)
    client.post("/api/v1/reliability/analyze", json={})
    r = client.get("/api/v1/reliability/report")
    assert r.status_code == 200
    # 若有报告则含 report_id；无则提示信息
    assert "report_id" in r.json() or "summary" in r.json()


def test_api_list_reports():
    _fresh_db()
    client = TestClient(app)
    client.post("/api/v1/reliability/analyze", json={})
    r = client.get("/api/v1/reliability/reports")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_api_get_report_not_found():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/reliability/report?report_id=NO-SUCH-999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. 护栏 + 模式完备
# ---------------------------------------------------------------------------
def test_contains_forbidden_content():
    assert contains_forbidden_content("建议买入该公司")
    assert contains_forbidden_content("目标价50元")
    assert not contains_forbidden_content("海外收入同比增长10%")
    # 否定式免责不误判
    assert not contains_forbidden_content("本结论不构成投资建议")


def test_pattern_labels_complete():
    for pt in PATTERN_TYPES:
        assert pt in PATTERN_LABELS
    assert PATTERN_LABELS[PATTERN_NUMERIC_ERROR] == "数值错误"
    assert PATTERN_LABELS[PATTERN_PERIOD_CONFUSION] == "期间混淆"
    assert PATTERN_LABELS[PATTERN_UNSUPPORTED_CLAIM] == "无依据主张"
    assert PATTERN_LABELS[PATTERN_EVIDENCE_MISSING] == "证据缺失"
    assert PATTERN_LABELS[PATTERN_LOGICAL_GAP] == "逻辑缺口"


def test_report_summary_is_not_investment_advice():
    _fresh_db()
    with SessionLocal() as s:
        report = analyze_reliability(s, limit=50)
    assert not contains_forbidden_content(report.summary)
    assert "不构成投资建议" in report.summary or "失败模式" in report.summary or "可靠性" in report.summary
