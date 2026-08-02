"""Continuous Monitoring Tests（Phase 12）。

覆盖：
- Thesis CRUD（add / list / get）
- 冲突检测（detect_conflicts）：METRIC_DRIFT / DIRECTION_REVERSAL / NEW_RISK
- 监控运行（run_monitoring）→ 告警生成
- 告警状态更新
- API 端到端
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.services.monitoring import (
    add_thesis,
    detect_conflicts,
    get_alert,
    list_alerts,
    list_theses,
    run_monitoring,
    update_alert_status,
)
from app.schemas.monitoring import InvestmentThesis


def _fresh_db():
    init_db()


def test_thesis_crud():
    _fresh_db()
    with SessionLocal() as s:
        t = add_thesis(
            s,
            thesis_id="THS-001",
            company="公司A",
            claim="毛利率维持稳定",
            metric="毛利率",
            metric_value=30.0,
            metric_unit="%",
            source="年报",
            risk_score=20.0,
        )
        assert t.thesis_id == "THS-001"
        assert t.metric_value == 30.0

        lst = list_theses(s)
        assert len(lst) >= 1


def test_detect_conflicts_metric_drift():
    thesis = InvestmentThesis(
        thesis_id="THS-001",
        company="公司A",
        claim="毛利率维持稳定",
        metric="毛利率",
        metric_value=30.0,
        metric_unit="%",
    )
    # 新毛利率 10%，偏离 66.7% > 15%
    conflict = detect_conflicts(thesis, "毛利率大幅下滑", new_metric_value=10.0)
    assert conflict.conflict_type == "METRIC_DRIFT"
    assert conflict.risk_score > 0
    assert "毛利率" in conflict.difference


def test_detect_conflicts_direction_reversal():
    thesis = InvestmentThesis(
        thesis_id="THS-002",
        company="公司B",
        claim="营收持续增长",
    )
    conflict = detect_conflicts(thesis, "营收同比下滑")
    assert conflict.conflict_type == "DIRECTION_REVERSAL"
    assert conflict.risk_score >= 70.0


def test_detect_conflicts_new_risk():
    thesis = InvestmentThesis(
        thesis_id="THS-003",
        company="公司C",
        claim="公司经营正常",
    )
    conflict = detect_conflicts(thesis, "公司收到立案通知")
    assert conflict.conflict_type == "NEW_RISK"
    assert conflict.risk_score >= 75.0


def test_detect_conflicts_none():
    thesis = InvestmentThesis(
        thesis_id="THS-004",
        company="公司D",
        claim="公司经营正常",
        metric="营收",
        metric_value=100.0,
        metric_unit="亿",
    )
    # 新 Fact 与历史一致，无明显冲突
    conflict = detect_conflicts(thesis, "公司经营正常", new_metric_value=100.0)
    assert conflict.conflict_type == "NONE"
    assert conflict.risk_score == 0.0


def test_run_monitoring_generates_alerts():
    _fresh_db()
    with SessionLocal() as s:
        add_thesis(
            s,
            thesis_id="THS-MON",
            company="公司M",
            claim="营收持续增长",
            metric="营收",
            metric_value=100.0,
            metric_unit="亿",
            portfolio_id="PF-MON",
        )
        alerts = run_monitoring(
            s,
            "PF-MON",
            [{"thesis_id": "THS-MON", "new_fact": "营收同比下滑", "new_metric_value": 50.0}],
        )
        assert len(alerts) == 1
        assert alerts[0].conflict_type in ("METRIC_DRIFT", "DIRECTION_REVERSAL")
        assert alerts[0].status == "OPEN"

        # List alerts
        lst = list_alerts(s, "PF-MON")
        assert len(lst) >= 1


def test_update_alert_status():
    _fresh_db()
    with SessionLocal() as s:
        add_thesis(
            s,
            thesis_id="THS-UP",
            company="公司U",
            claim="营收持续增长",
            portfolio_id="PF-UP",
        )
        alerts = run_monitoring(
            s,
            "PF-UP",
            [{"thesis_id": "THS-UP", "new_fact": "营收同比下滑"}],
        )
        assert len(alerts) == 1
        aid = alerts[0].alert_id
        upd = update_alert_status(s, aid, "RESOLVED")
        assert upd.status == "RESOLVED"

        # Invalid status
        try:
            update_alert_status(s, aid, "INVALID")
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


def test_monitoring_api_endpoints():
    _fresh_db()
    client = TestClient(app)

    # Create thesis
    r = client.post(
        "/api/v1/monitoring/theses",
        json={
            "thesis_id": "THS-API",
            "company": "公司API",
            "claim": "毛利率维持稳定",
            "metric": "毛利率",
            "metric_value": 30.0,
            "metric_unit": "%",
            "risk_score": 20.0,
            "portfolio_id": "PF-API",
        },
    )
    assert r.status_code == 201, r.text

    # List theses
    r = client.get("/api/v1/monitoring/theses", params={"portfolio_id": "PF-API"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    # Run monitoring
    r = client.post(
        "/api/v1/monitoring/runs",
        json={
            "portfolio_id": "PF-API",
            "new_facts": [
                {"thesis_id": "THS-API", "new_fact": "毛利率大幅下滑", "new_metric_value": 10.0}
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["alerts_count"] >= 1

    # List alerts
    r = client.get("/api/v1/monitoring/alerts", params={"portfolio_id": "PF-API"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    # Update alert status
    alert_id = body["alerts"][0]["alert_id"]
    r = client.patch(f"/api/v1/monitoring/alerts/{alert_id}", json={"status": "RESOLVED"})
    assert r.status_code == 200
    assert r.json()["status"] == "RESOLVED"
