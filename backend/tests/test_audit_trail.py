"""Audit Trail / Governance Tests（Phase 12）。

覆盖：
- log_audit 记录审计日志
- list_logs 查询（按 user/action/target_type 过滤）
- get_log 单条查询
- API 端到端（POST /logs、GET /logs、GET /logs/{id}、GET /evidence-trace）
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.services.audit_trail import get_log, list_logs, log_audit


def _fresh_db():
    init_db()


def test_log_audit_and_get():
    _fresh_db()
    with SessionLocal() as s:
        log = log_audit(
            s,
            user="analyst_zhang",
            action="RUN_COMMITTEE",
            target_type="committee_report",
            target_id=42,
            model_version="v1.2",
            rule_version="r2024",
            evidence_used=[{"source": "annual_report.pdf", "page": 30}],
            detail={"note": "委员会审核"},
        )
        assert log.action == "RUN_COMMITTEE"
        assert log.user == "analyst_zhang"
        assert log.target_id == 42
        assert len(log.evidence_used) == 1
        assert log.detail["note"] == "委员会审核"

        got = get_log(s, log.log_id)
        assert got.log_id == log.log_id


def test_list_logs_filters():
    _fresh_db()
    with SessionLocal() as s:
        log_audit(s, user="u1", action="A1", target_type="t1", target_id=1)
        log_audit(s, user="u2", action="A2", target_type="t2", target_id=2)
        log_audit(s, user="u1", action="A3", target_type="t1", target_id=3)

        assert len(list_logs(s, user="u1")) == 2
        assert len(list_logs(s, action="A2")) == 1
        assert len(list_logs(s, target_type="t1")) == 2
        assert len(list_logs(s)) >= 3


def test_governance_api_endpoints():
    _fresh_db()
    client = TestClient(app)

    # Create log
    r = client.post(
        "/api/v1/governance/logs",
        json={
            "user": "analyst_li",
            "action": "RUN_VERIFICATION",
            "target_type": "verification_run",
            "target_id": 7,
            "model_version": "v1.0",
            "rule_version": "r2024",
            "evidence_used": [{"source": "q1_report.pdf", "page": 5}],
            "detail": {"claim_count": 26},
        },
    )
    assert r.status_code == 201, r.text
    log = r.json()
    assert log["action"] == "RUN_VERIFICATION"
    log_id = log["log_id"]

    # List logs
    r = client.get("/api/v1/governance/logs", params={"user": "analyst_li"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    # Get single log
    r = client.get(f"/api/v1/governance/logs/{log_id}")
    assert r.status_code == 200
    assert r.json()["log_id"] == log_id

    # Evidence trace
    r = client.get("/api/v1/governance/evidence-trace/verification_run/7")
    assert r.status_code == 200
    assert r.json()["count"] >= 1
