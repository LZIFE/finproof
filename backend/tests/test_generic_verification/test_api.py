"""backend/tests/test_generic_verification/test_api.py"""
import fitz
from fastapi.testclient import TestClient

from app.main import create_app


def _make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def test_generic_verify_endpoint_ok():
    app = create_app()
    client = TestClient(app)
    pdf = _make_pdf("营业收入 1.2 亿元，详见第 1 章。")
    resp = client.post(
        "/api/v1/generic-verify",
        files={"file": ("sample.pdf", pdf, "application/pdf")},
        data={"mode": "auto"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_claims" in body
    assert "error_report" in body
    assert "is_mock" in body


def test_generic_verify_invalid_mode():
    app = create_app()
    client = TestClient(app)
    pdf = _make_pdf("营业收入 1.2 亿元。")
    resp = client.post(
        "/api/v1/generic-verify",
        files={"file": ("sample.pdf", pdf, "application/pdf")},
        data={"mode": "bogus"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_MODE"


def test_generic_verify_non_pdf_rejected():
    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/generic-verify",
        files={"file": ("sample.txt", b"hello", "text/plain")},
        data={"mode": "auto"},
    )
    # 与现有 documents API 约定一致：不支持的文件类型 → 415 UNSUPPORTED_DOCUMENT
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT"
