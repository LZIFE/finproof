"""主张提取 API 单元测试：创建运行 / 运行详情 / 主张列表过滤 / 详情 / 审核 / 404。"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPORT_TEXT = "# 标题\n\n公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n"


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c


def _register_report(client) -> int:
    r = client.post(
        "/api/v1/documents",
        files={"file": ("report.md", REPORT_TEXT.encode(), "text/markdown")},
        data={"document_role": "REPORT_TO_VERIFY", "company_name": "美的集团", "stock_code": "000333"},
    )
    assert r.status_code == 201
    return r.json()["document"]["id"]


def test_create_claim_extraction(client):
    doc_id = _register_report(client)
    r = client.post(f"/api/v1/documents/{doc_id}/claim-extractions", json={"mode": "mock", "force": False})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["mode"] == "mock"
    assert body["extracted_claim_count"] > 0
    assert body["extraction_run_id"] > 0


def test_run_detail(client):
    doc_id = _register_report(client)
    run_id = client.post(f"/api/v1/documents/{doc_id}/claim-extractions", json={"mode": "mock"}).json()["extraction_run_id"]
    r = client.get(f"/api/v1/claim-extractions/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["provider"] == "mock"
    assert body["prompt_version"] == "v1"
    assert body["duration_ms"] is not None


def test_claims_list_filters_and_pagination(client):
    doc_id = _register_report(client)
    client.post(f"/api/v1/documents/{doc_id}/claim-extractions", json={"mode": "mock"})
    r = client.get(f"/api/v1/documents/{doc_id}/claims?page=1&page_size=2")
    assert r.status_code == 200
    assert r.json()["total"] > 0
    assert len(r.json()["claims"]) <= 2
    r_high = client.get(f"/api/v1/documents/{doc_id}/claims?risk_level=HIGH")
    assert all(c["risk_level"] == "HIGH" for c in r_high.json()["claims"])
    r_bad = client.get(f"/api/v1/documents/{doc_id}/claims?claim_type=NOPE")
    assert r_bad.status_code == 422
    assert r_bad.json()["error"]["code"] == "INVALID_CLAIM_TYPE"


def test_claim_detail_and_review(client):
    doc_id = _register_report(client)
    client.post(f"/api/v1/documents/{doc_id}/claim-extractions", json={"mode": "mock"})
    claim_id = client.get(f"/api/v1/documents/{doc_id}/claims?page_size=1").json()["claims"][0]["id"]
    r = client.get(f"/api/v1/claims/{claim_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["source_text"] and body["claim_type"] and body["source_block_id"]
    rv = client.patch(f"/api/v1/claims/{claim_id}/review", json={"review_status": "APPROVED", "comment": "ok"})
    assert rv.status_code == 200
    assert rv.json()["review_status"] == "APPROVED" and rv.json()["review_comment"] == "ok"
    rv2 = client.patch(f"/api/v1/claims/{claim_id}/review", json={"review_status": "EDITED", "changes": {"reported_value": 9.9}})
    assert rv2.json()["review_status"] == "EDITED"
    assert rv2.json()["reported_value"] != 9.9  # 原输出保留


def test_404_paths(client):
    assert client.get("/api/v1/claim-extractions/99999").status_code == 404
    assert client.get("/api/v1/claims/99999").status_code == 404
    assert client.get("/api/v1/documents/99999/claims").status_code == 404


def test_extraction_on_source_document_rejected(client):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("src.pdf", b"%PDF-1.4", "application/pdf")},
        data={"document_role": "SOURCE_DOCUMENT"},
    )
    assert r.status_code == 415  # 假PDF被拒（不进入角色校验路径）
