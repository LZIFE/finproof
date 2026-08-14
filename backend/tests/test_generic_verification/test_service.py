"""backend/tests/test_generic_verification/test_service.py"""
import pytest

from app.core.exceptions import AppError
from app.services.generic_verification.service import verify_pdf


def _make_pdf(text_pages: list[str]) -> bytes:
    """用 PyMuPDF 生成带文本页的最小 PDF（中文字体 china-s，避免乱码）。"""
    import fitz

    doc = fitz.open()
    for t in text_pages:
        page = doc.new_page()
        page.insert_text((72, 72), t, fontsize=11, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def _mock_settings(monkeypatch):
    """默认 mock 模式 + 关闭 OCR，保证测试无外部依赖。"""
    s = _FakeSettings()
    monkeypatch.setattr("app.services.generic_verification.claim_extraction.get_settings", lambda: s)
    monkeypatch.setattr("app.services.generic_verification.ocr.get_settings", lambda: s)
    monkeypatch.setattr("app.services.generic_verification.service.get_settings", lambda: s)
    return s


class _FakeSettings:
    ocr_engine = "off"
    claim_extraction_base_url = ""
    claim_extraction_api_key = ""
    claim_extraction_model = ""
    claim_extraction_timeout_seconds = 10
    claim_extraction_max_retries = 0
    generic_extraction_prompt_version = "generic_claim_extraction_v1"
    generic_web_search = False


def test_verify_pdf_internal_conflict(monkeypatch):
    _mock_settings(monkeypatch)
    pdf = _make_pdf(["营业收入 1.2 亿元，详细数据见下表。", "营业收入 1.2 万元。"])
    result = verify_pdf(None, pdf, "sample.pdf")
    assert result["total_claims"] >= 1
    assert result["is_mock"] is True
    assert any(c["verdict"] == "REFUTED" for c in result["claims"])


def test_verify_pdf_rejects_broken_pdf(monkeypatch):
    _mock_settings(monkeypatch)
    with pytest.raises(AppError):
        verify_pdf(None, b"not a pdf", "broken.pdf")


def test_verify_pdf_error_report_sorted(monkeypatch):
    _mock_settings(monkeypatch)
    pdf = _make_pdf(["营业收入 1.2 亿元。", "营业收入 1.2 万元。"])
    result = verify_pdf(None, pdf, "sample.pdf")
    pages = [e["page_number"] for e in result["error_report"]]
    assert pages == sorted(pages)
