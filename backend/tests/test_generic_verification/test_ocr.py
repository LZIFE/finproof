"""backend/tests/test_generic_verification/test_ocr.py"""
import pytest

from app.core.exceptions import AppError
from app.services.generic_verification.ocr import (
    SCAN_PAGE_MIN_CHARS,
    is_scan_page,
    ocr_pages,
)
from app.services.parser.types import ParsedPage


def _page(text: str, page_number: int = 1) -> ParsedPage:
    return ParsedPage(
        page_index=page_number - 1, page_number=page_number,
        printed_page_label=None, text=text, character_count=len(text),
        text_sha256="x", blocks=[],
    )


def test_scan_page_detection():
    assert is_scan_page(_page("", 1))
    assert is_scan_page(_page(" ", 2))
    assert not is_scan_page(_page("第一章 概述" * 20, 3))


def test_scan_page_min_chars_constant():
    assert SCAN_PAGE_MIN_CHARS == 50


def test_ocr_pages_skips_text_pages(monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.services.generic_verification.ocr.render_ocr_text",
        lambda pdf_bytes, page_number, lang="chi_sim": called.append(page_number) or "OCR文本",
    )
    pages = [_page("", 1), _page("正文" * 60, 2)]
    result = ocr_pages(pages, b"pdf-bytes")
    assert result == {1: "OCR文本"}
    assert called == [1]


def test_ocr_raises_when_disabled():
    from app.services.generic_verification import ocr as ocr_mod

    class _FakeSettings:
        ocr_engine = "off"

    ocr_mod.get_settings = lambda: _FakeSettings()
    with pytest.raises(AppError):
        ocr_mod.render_ocr_text(b"", 1)


def test_parse_with_ocr_fallback_text_pdf(monkeypatch):
    """文本 PDF：扫描页回填，其余页不动。"""
    import fitz

    from app.services.generic_verification import ocr as ocr_mod

    class _FakeSettings:
        ocr_engine = "tesseract"

    ocr_mod.get_settings = lambda: _FakeSettings()
    monkeypatch.setattr("app.services.generic_verification.ocr.render_ocr_text",
                        lambda pdf_bytes, page_number, lang="chi_sim": f"OCR第{page_number}页")

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "扫描页无文本", fontsize=11)  # 空文本页
    data = doc.tobytes()
    doc.close()

    parsed = ocr_mod.parse_with_ocr(data)
    # 空文本页被 OCR 回填：页面 text 非空
    assert any(p.text.strip() for p in parsed.pages)
