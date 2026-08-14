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


def test_generic_verify_persists_and_history():
    """核验结果持久化 + 历史列表/详情查询（实用功能回归）。"""
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
    run_id = body.get("run_id")
    assert run_id is not None and isinstance(run_id, int)

    # 历史列表
    hist = client.get("/api/v1/generic-verify/runs").json()
    assert hist["total"] >= 1
    assert any(r["id"] == run_id for r in hist["runs"])

    # 详情（含完整报告）
    detail = client.get(f"/api/v1/generic-verify/runs/{run_id}").json()
    assert detail["id"] == run_id
    assert "result" in detail
    assert detail["result"]["total_claims"] >= 1


def test_generic_verify_run_detail_not_found():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/generic-verify/runs/999999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_generic_verify_batch_multiple_files():
    """批量核验：多文件逐项返回，单文件失败不影响其余（实用功能回归）。"""
    app = create_app()
    client = TestClient(app)
    pdf_ok = _make_pdf("营业收入 1.2 亿元。")
    resp = client.post(
        "/api/v1/generic-verify/batch",
        files=[
            ("files", ("a.pdf", pdf_ok, "application/pdf")),
            ("files", ("broken.pdf", b"not a pdf", "application/pdf")),
        ],
        data={"mode": "auto"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_files"] == 2
    by_name = {i["filename"]: i for i in body["items"]}
    assert by_name["a.pdf"]["status"] == "COMPLETED"
    assert by_name["a.pdf"]["total_claims"] >= 1
    assert by_name["broken.pdf"]["status"] == "FAILED"
    assert "error" in by_name["broken.pdf"]


def test_generic_verify_export_markdown():
    """核验记录导出 Markdown 报告（实用功能回归）。"""
    app = create_app()
    client = TestClient(app)
    pdf = _make_pdf("营业收入 1.2 亿元，详见第 1 章。")
    resp = client.post(
        "/api/v1/generic-verify",
        files={"file": ("sample.pdf", pdf, "application/pdf")},
        data={"mode": "auto"},
    )
    run_id = resp.json()["run_id"]
    export = client.get(f"/api/v1/generic-verify/runs/{run_id}/export")
    assert export.status_code == 200
    text = export.text
    assert "通用 PDF 内容核验报告" in text
    assert "判定统计" in text
    assert "错误清单" in text


def test_export_markdown_escapes_pipe():
    """Markdown 导出须转义表格管道符（实用功能回归）。"""
    from app.services.generic_verification.service import export_markdown

    md = export_markdown({
        "filename": "x.pdf", "total_claims": 1, "is_mock": True,
        "verdicts": {"REFUTED": 1},
        "error_report": [{"page_number": 3, "source_text": "A|B", "verdict": "REFUTED",
                          "error_type": "NUMERIC_CONFLICT", "detail": "1.2 亿|1.2 万"}],
    })
    assert "A\\|B" in md
    assert "1.2 亿\\|1.2 万" in md
