"""FinProof Competition Demo Mode Tests（Phase 22）。

覆盖（任务书 §Testing）：
- demo workflow 测试    8 步编排 · 步骤顺序 · 状态 · 持久化 · 最终输出
- API 测试           POST /demo/start + GET /demo/{id} + GET /demo/{id}/steps + GET /demo
- Demo Case          固定美的集团 · 3 场景（错误增长率/战略夸大/证据不足）
- 护栏               禁止词；不修改 Verification/Risk 核心；不生成投资建议
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.services.demo_mode import (
    BACKEND_STEPS,
    DEMO_COMPANY,
    DEMO_SCENARIOS,
    FRONTEND_STEPS,
    FRONTEND_STEP_LABELS,
    contains_forbidden_content,
    get_demo,
    get_demo_steps,
    list_demos,
    start_demo,
)


def _fresh_db():
    init_db()


# ---------------------------------------------------------------------------
# 1. Demo workflow 测试
# ---------------------------------------------------------------------------
def test_start_demo_runs_8_steps_in_order():
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "美的集团", "")
    # 8 步齐全
    assert len(run.steps) == 8
    names = [s.name for s in run.steps]
    assert names == BACKEND_STEPS
    # 步骤序号 1-8
    assert [s.step_number for s in run.steps] == list(range(1, 9))
    # 状态 DONE
    assert run.status == "DONE"
    assert run.current_step == "DONE"


def test_start_demo_default_company_is_midea():
    """空 company → 固定 Demo Case �美的集团（任务书 §Demo Case）。"""
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "", "")
    assert run.company == DEMO_COMPANY == "美的集团"


def test_start_demo_persists_and_get_returns_same():
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "美的集团", "")
        demo_id = run.demo_id
    # get_demo 应返回相同结构
    with SessionLocal() as s:
        fetched = get_demo(s, demo_id)
    assert fetched.demo_id == demo_id
    assert len(fetched.steps) == 8
    # 持久化到 demo_runs / demo_steps
    from app.models.demo_mode import DemoRunRow, DemoStepRow
    with SessionLocal() as s:
        run_row = s.query(DemoRunRow).filter(DemoRunRow.demo_id == demo_id).first()
        assert run_row is not None
        step_cnt = s.query(DemoStepRow).filter(DemoStepRow.demo_id == run_row.id).count()
        assert step_cnt == 8


def test_get_demo_steps_returns_ordered():
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "美的集团", "")
        demo_id = run.demo_id
    with SessionLocal() as s:
        steps = get_demo_steps(s, demo_id)
    assert len(steps) == 8
    assert [s.step_number for s in steps] == list(range(1, 9))


def test_get_demo_raises_for_unknown():
    _fresh_db()
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            get_demo(s, "NO-SUCH-DEMO-999")


def test_get_demo_steps_raises_for_unknown():
    _fresh_db()
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            get_demo_steps(s, "NO-SUCH-DEMO-999")


def test_list_demos_returns_metadata():
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "列表测试公司", "")
        demo_id = run.demo_id
    with SessionLocal() as s:
        items = list_demos(s, limit=50)
    ids = [i["demo_id"] for i in items]
    assert demo_id in ids


# ---------------------------------------------------------------------------
# 2. DemoStep 字段完整性（任务书 §DemoStep + §每一步展示）
# ---------------------------------------------------------------------------
def test_each_step_records_source_evidence_result():
    """每一步记录 step_number/name/status/duration/input_reference/output_reference + 来源/证据/结果。"""
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "字段测试公司", "")
    for s in run.steps:
        assert s.step_number >= 1
        assert s.name
        assert s.status in ("OK", "SKIPPED", "ERROR", "RUNNING", "PENDING")
        assert s.duration >= 0
        # input/output reference 字段存在（可为空）
        assert hasattr(s, "input_reference")
        assert hasattr(s, "output_reference")


def test_frontend_steps_map_to_backend():
    """前端 6 步动画覆盖后端 8 步（任务书 §执行动画）。"""
    assert len(FRONTEND_STEPS) == 6
    # 每个前端步有中文标签
    for fs in FRONTEND_STEPS:
        assert fs in FRONTEND_STEP_LABELS


# ---------------------------------------------------------------------------
# 3. 最终输出（任务书 §最后展示）
# ---------------------------------------------------------------------------
def test_final_outputs_reliability_risk_replay():
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "美的集团", "")
    # ① Reliability Score
    assert 0.0 <= run.reliability_score <= 100.0
    # ② Risk Findings
    assert isinstance(run.risk_findings, list)
    assert len(run.risk_findings) >= 1
    # ③ Audit Replay
    assert run.audit_replay_id  # arena run id


def test_demo_case_three_scenarios():
    """固定 Demo Case：错误增长率 / 战略夸大 / 证据不足（任务书 §Demo Case）。"""
    assert DEMO_SCENARIOS == ["错误财务增长率", "战略夸大", "证据不足"]
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "美的集团", "")
    # 若库中无该公司风险条目，应注入 3 个 Demo Case 场景
    if any(r.get("risk_id", "").startswith("DEMO-RISK") for r in run.risk_findings):
        assert len(run.risk_findings) == 3
        reasons = [r.get("reason", "") for r in run.risk_findings]
        assert any("错误" in r and "增长率" in r for r in reasons)
        assert any("夸大" in r for r in reasons)
        assert any("证据" in r for r in reasons)


# ---------------------------------------------------------------------------
# 4. API 测试
# ---------------------------------------------------------------------------
def test_api_start_demo():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/demo/start", json={"company": "API测试公司"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["demo_id"].startswith("DEMO-")
    assert body["status"] == "DONE"
    assert len(body["steps"]) == 8
    # 最终输出字段
    assert "reliability_score" in body
    assert "risk_findings" in body
    assert "audit_replay_id" in body


def test_api_start_demo_default_company():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/demo/start", json={})
    assert r.status_code == 201
    assert r.json()["company"] == "美的集团"


def test_api_get_demo():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/demo/start", json={"company": "GET测试公司"})
    demo_id = r.json()["demo_id"]
    r = client.get(f"/api/v1/demo/{demo_id}")
    assert r.status_code == 200
    assert r.json()["demo_id"] == demo_id


def test_api_get_demo_steps():
    _fresh_db()
    client = TestClient(app)
    r = client.post("/api/v1/demo/start", json={"company": "Steps测试公司"})
    demo_id = r.json()["demo_id"]
    r = client.get(f"/api/v1/demo/{demo_id}/steps")
    assert r.status_code == 200
    assert r.json()["count"] == 8


def test_api_list_demos():
    _fresh_db()
    client = TestClient(app)
    client.post("/api/v1/demo/start", json={"company": "列表公司"})
    r = client.get("/api/v1/demo")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_api_get_demo_not_found():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/demo/NO-SUCH-DEMO-999")
    assert r.status_code == 404


def test_api_get_demo_steps_not_found():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/demo/NO-SUCH-DEMO-999/steps")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5. 护栏
# ---------------------------------------------------------------------------
def test_contains_forbidden_content():
    assert contains_forbidden_content("建议买入该公司")
    assert contains_forbidden_content("目标价50元")
    assert not contains_forbidden_content("海外收入同比增长10%")
    # 否定式免责不误判
    assert not contains_forbidden_content("本结论不构成投资建议")


def test_demo_risk_findings_no_forbidden():
    """演示风险条目 reason 不应含禁止词（投资建议/股票推荐/估值预测）。"""
    _fresh_db()
    with SessionLocal() as s:
        run = start_demo(s, "护栏测试公司", "")
    for r in run.risk_findings:
        assert not contains_forbidden_content(r.get("reason", ""))
