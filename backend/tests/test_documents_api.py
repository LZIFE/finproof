"""文档接入 API 单元测试：上传/去重/列表过滤分页/详情/页面/统一错误结构。"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c


def _pdf(text: str = "API 测试内容") -> bytes:
    doc = fitz.open()
    for i in range(3):
        pg = doc.new_page()
        pg.insert_text((72, 72), f"{text} 第{i + 1}页")
    data = doc.tobytes()
    doc.close()
    return data


def test_upload_pdf_created(client):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("demo.pdf", _pdf(), "application/pdf")},
        data={"document_role": "SOURCE_DOCUMENT", "company_name": "美的集团", "stock_code": "000333"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate"] is False
    doc = body["document"]
    assert doc["parse_status"] == "COMPLETED"
    assert doc["page_count"] == 3
    assert doc["sha256"]
    assert doc["company_name"] == "美的集团"


def test_upload_duplicate_returns_existing(client):
    data = _pdf()
    r1 = client.post("/api/v1/documents", files={"file": ("a.pdf", data, "application/pdf")})
    r2 = client.post("/api/v1/documents", files={"file": ("b.pdf", data, "application/pdf")})
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r2.json()["duplicate"] is True
    assert r2.json()["document"]["id"] == r1.json()["document"]["id"]


def test_upload_markdown(client):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("report.md", "# 标题\n\n正文。".encode(), "text/markdown")},
        data={"document_role": "REPORT_TO_VERIFY"},
    )
    assert r.status_code == 201
    assert r.json()["document"]["document_type"] == "markdown"
    assert r.json()["document"]["page_count"] == 1


def test_upload_unsupported_extension(client):
    r = client.post("/api/v1/documents", files={"file": ("evil.exe", b"%PDF", "application/octet-stream")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT"


def test_upload_fake_pdf(client):
    r = client.post("/api/v1/documents", files={"file": ("fake.pdf", b"hello", "application/pdf")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "INVALID_FILE"


def test_upload_empty_file(client):
    r = client.post("/api/v1/documents", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "EMPTY_FILE"


def test_upload_encrypted_pdf(client):
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "x")
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    r = client.post("/api/v1/documents", files={"file": ("enc.pdf", data, "application/pdf")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "ENCRYPTED_PDF"


def test_upload_too_large(client, monkeypatch):
    monkeypatch.setenv("FINPROOF_MAX_UPLOAD_SIZE_MB", "0")  # 0 MB：任何非空文件都超限
    get_settings.cache_clear()
    try:
        r = client.post("/api/v1/documents", files={"file": ("big.pdf", _pdf(), "application/pdf")})
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "FILE_TOO_LARGE"
    finally:
        get_settings.cache_clear()


def test_upload_path_traversal_filename(client):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("../../etc/passwd.pdf", _pdf(), "application/pdf")},
    )
    assert r.status_code == 201
    assert r.json()["document"]["original_filename"] == "passwd.pdf"


def test_upload_invalid_role(client):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", _pdf(), "application/pdf")},
        data={"document_role": "NOT_A_ROLE"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_DOCUMENT_ROLE"


def test_list_filter_pagination(client):
    client.post("/api/v1/documents", files={"file": ("a.pdf", _pdf("A"), "application/pdf")},
                data={"document_role": "SOURCE_DOCUMENT"})
    client.post("/api/v1/documents", files={"file": ("b.md", "# b".encode(), "text/markdown")},
                data={"document_role": "REPORT_TO_VERIFY"})
    r = client.get("/api/v1/documents?role=SOURCE_DOCUMENT&page=1&page_size=10")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["documents"][0]["document_role"] == "SOURCE_DOCUMENT"
    r2 = client.get("/api/v1/documents?status=COMPLETED")
    assert r2.json()["total"] == 2
    r3 = client.get("/api/v1/documents?role=BAD")
    assert r3.status_code == 422 and r3.json()["error"]["code"] == "INVALID_DOCUMENT_ROLE"


def test_document_not_found(client):
    r = client.get("/api/v1/documents/99999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_pages_list_and_detail(client):
    r = client.post("/api/v1/documents", files={"file": ("a.pdf", _pdf(), "application/pdf")})
    doc_id = r.json()["document"]["id"]
    rp = client.get(f"/api/v1/documents/{doc_id}/pages")
    assert rp.status_code == 200
    assert rp.json()["total_pages"] == 3
    pages = rp.json()["pages"]
    assert [p["page_number"] for p in pages] == [1, 2, 3]
    assert all(p["character_count"] > 0 and not p["is_empty"] for p in pages)
    assert pages[0]["text_preview"]
    rd = client.get(f"/api/v1/documents/{doc_id}/pages/2")
    assert rd.status_code == 200
    detail = rd.json()
    assert detail["page_index"] == 1 and detail["page_number"] == 2
    assert detail["character_count"] > 0
    assert detail["blocks"] and detail["blocks"][0]["x0"] is not None


def test_page_not_found(client):
    r = client.post("/api/v1/documents", files={"file": ("a.pdf", _pdf(), "application/pdf")})
    doc_id = r.json()["document"]["id"]
    r404 = client.get(f"/api/v1/documents/{doc_id}/pages/999")
    assert r404.status_code == 404
    assert r404.json()["error"]["code"] == "PAGE_NOT_FOUND"
