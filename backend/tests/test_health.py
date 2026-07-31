"""健康检查接口测试。"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_ok():
    with TestClient(create_app()) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "finproof-api"
    # 数据库信息为尽力而为字段，必须是 sqlite 版本字符串或 error 前缀
    assert isinstance(body.get("database"), str)


def test_api_health_alias():
    with TestClient(create_app()) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["service"] == "finproof-api"


def test_unknown_route_returns_404():
    with TestClient(create_app()) as client:
        resp = client.get("/no-such-route")
    assert resp.status_code == 404
