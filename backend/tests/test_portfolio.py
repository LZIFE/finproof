"""Portfolio Risk Dashboard Tests（Phase 12）。

覆盖：
- 项目 CRUD（add / list / get / update_risk）
- 聚合（aggregate_risk）：加权平均、排名、分布、最高风险
- 快照（build_snapshot / list_snapshots / get_snapshot）
- API 端到端（POST /projects、PATCH、POST /snapshots、GET）
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.services.portfolio import (
    add_project,
    aggregate_risk,
    build_snapshot,
    get_project,
    list_projects,
    list_snapshots,
    update_project_risk,
)
from app.schemas.portfolio import (
    PortfolioProject,
    risk_level_of,
)


def _fresh_db():
    init_db()


def test_portfolio_project_crud():
    _fresh_db()
    with SessionLocal() as s:
        p = add_project(s, "PF-TEST", "公司A", "000001", weight=0.4, latest_risk_score=55.0)
        assert p.company == "公司A"
        assert p.latest_risk_level == "MEDIUM"

        lst = list_projects(s, "PF-TEST")
        assert len(lst) == 1

        got = get_project(s, p.project_id)
        assert got.company == "公司A"

        upd = update_project_risk(s, p.project_id, 80.0)
        assert upd.latest_risk_score == 80.0
        assert upd.latest_risk_level == "HIGH"


def test_aggregate_risk_weighted_and_ranking():
    projects = [
        PortfolioProject(project_id=1, portfolio_id="PF-X", company="A", weight=0.5, latest_risk_score=60.0),
        PortfolioProject(project_id=2, portfolio_id="PF-X", company="B", weight=0.5, latest_risk_score=80.0),
    ]
    snap = aggregate_risk(projects)
    # 加权平均: 0.5*60 + 0.5*80 = 70 → HIGH
    assert snap.portfolio_risk_score == 70.0
    assert snap.portfolio_risk_level == "HIGH"
    # 排名: B(80) 第一, A(60) 第二
    assert snap.company_ranking[0].company == "B"
    assert snap.company_ranking[0].rank == 1
    assert snap.company_ranking[1].company == "A"
    # 分布: A(60)=MEDIUM, B(80)=HIGH
    high = next(d for d in snap.risk_distribution if d.risk_level == "HIGH")
    med = next(d for d in snap.risk_distribution if d.risk_level == "MEDIUM")
    assert high.count == 1
    assert med.count == 1
    assert high.share == 0.5


def test_aggregate_risk_zero_weight_equal_share():
    projects = [
        PortfolioProject(project_id=1, portfolio_id="PF-X", company="A", weight=0.0, latest_risk_score=40.0),
        PortfolioProject(project_id=2, portfolio_id="PF-X", company="B", weight=0.0, latest_risk_score=60.0),
    ]
    snap = aggregate_risk(projects)
    # 等权退路: (40+60)/2 = 50
    assert snap.portfolio_risk_score == 50.0
    assert snap.portfolio_risk_level == "MEDIUM"


def test_build_snapshot_persists_and_lists():
    _fresh_db()
    with SessionLocal() as s:
        add_project(s, "PF-SNAP", "公司A", "000001", weight=0.5, latest_risk_score=60.0)
        add_project(s, "PF-SNAP", "公司B", "000002", weight=0.5, latest_risk_score=80.0)
        snap = build_snapshot(s, "PF-SNAP")
        assert snap.id is not None
        assert snap.portfolio_risk_score == 70.0

        listed = list_snapshots(s, "PF-SNAP")
        assert len(listed) == 1


def test_risk_level_thresholds():
    assert risk_level_of(20.0) == "LOW"
    assert risk_level_of(30.0) == "MEDIUM"
    assert risk_level_of(65.0) == "MEDIUM"
    assert risk_level_of(66.0) == "HIGH"


def test_portfolio_api_endpoints():
    _fresh_db()
    client = TestClient(app)

    # Create project
    r = client.post(
        "/api/v1/portfolio/projects",
        json={
            "portfolio_id": "PF-API",
            "company": "公司X",
            "stock_code": "600000",
            "weight": 0.6,
            "latest_risk_score": 50.0,
        },
    )
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["company"] == "公司X"
    pid = project["project_id"]

    # List projects
    r = client.get("/api/v1/portfolio/projects", params={"portfolio_id": "PF-API"})
    assert r.status_code == 200
    assert r.json()["count"] == 1

    # Update risk
    r = client.patch(f"/api/v1/portfolio/projects/{pid}", json={"latest_risk_score": 90.0})
    assert r.status_code == 200
    assert r.json()["latest_risk_level"] == "HIGH"

    # Build snapshot
    r = client.post("/api/v1/portfolio/snapshots", json={"portfolio_id": "PF-API"})
    assert r.status_code == 201, r.text
    snap = r.json()
    assert snap["portfolio_risk_level"] == "HIGH"
    assert len(snap["company_ranking"]) == 1

    # List snapshots
    r = client.get("/api/v1/portfolio/snapshots", params={"portfolio_id": "PF-API"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1
