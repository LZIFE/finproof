"""扫描件 OCR 兜底（默认 off，无 Tesseract 依赖也可运行）。

- is_scan_page：字符数 < 50 且无文本 → 扫描页
- render_ocr_text：PyMuPDF 从字节渲染指定页 → pytesseract 识别（中文 chi_sim）
- parse_with_ocr：解析入口（Task 10 统一调用），文本 PDF 回填扫描页 / 全扫描件整篇 OCR
- ocr_engine 配置非 tesseract 或 pytesseract 未安装 → 抛 OCR_NOT_AVAILABLE（不静默降级）
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.parser.pdf_parser import parse_pdf
from app.services.parser.types import ParsedBlock, ParsedDocument, ParsedPage

logger = logging.getLogger(__name__)

SCAN_PAGE_MIN_CHARS = 50


def is_scan_page(page: ParsedPage) -> bool:
    return page.character_count < SCAN_PAGE_MIN_CHARS and not page.text.strip()


def render_ocr_text(pdf_bytes: bytes, page_number: int, lang: str = "chi_sim") -> str:
    """从原始 PDF 字节渲染第 page_number 页（1 基）并 OCR。"""
    cfg = get_settings()
    if cfg.ocr_engine != "tesseract":
        raise AppError("OCR 未启用（FINPROOF_OCR_ENGINE 需设为 tesseract）",
                       status_code=422, code="OCR_NOT_AVAILABLE")
    try:
        import fitz
        import pytesseract
    except ImportError as exc:  # noqa: BLE001
        raise AppError("OCR 依赖未安装（pymupdf / pytesseract）",
                       status_code=422, code="OCR_NOT_AVAILABLE") from exc
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[page_number - 1].get_pixmap(dpi=200)
        return pytesseract.image_to_string(pix.tobytes("png"), lang=lang)
    finally:
        doc.close()


def ocr_pages(pages: list[ParsedPage], pdf_bytes: bytes) -> dict[int, str]:
    """对扫描页执行 OCR，返回 {page_number: ocr_text}（单页失败跳过）。"""
    out: dict[int, str] = {}
    for p in pages:
        if not is_scan_page(p):
            continue
        try:
            out[p.page_number] = render_ocr_text(pdf_bytes, p.page_number)
        except AppError:
            logger.warning("OCR 失败 page=%s", p.page_number)
    return out


def _build_page_with_ocr(pdf_bytes: bytes, page_number: int, ocr_text: str) -> ParsedPage:
    text = ocr_text.strip()
    return ParsedPage(
        page_index=page_number - 1,
        page_number=page_number,
        printed_page_label=None,
        text=text,
        character_count=len(text),
        text_sha256="ocr:" + str(hash(text)),
        blocks=[ParsedBlock(block_index=0, block_type="paragraph", text=text)],
    )


def parse_with_ocr(pdf_bytes: bytes) -> ParsedDocument:
    """解析 PDF，扫描页以 OCR 文本回填；全扫描件整篇 OCR。

    文本 PDF：parse_pdf 成功后，对 is_scan_page 的页用 OCR 结果替换该页文本。
    全扫描件：parse_pdf 抛 NO_EXTRACTABLE_TEXT → 若 ocr_engine==tesseract，
    逐页渲染 OCR 构造 ParsedDocument；否则原样抛出。
    """
    try:
        parsed = parse_pdf(pdf_bytes)
    except AppError as exc:
        if exc.code == "NO_EXTRACTABLE_TEXT" and get_settings().ocr_engine == "tesseract":
            import fitz

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                pages = [_build_page_with_ocr(pdf_bytes, i + 1, render_ocr_text(pdf_bytes, i + 1))
                         for i in range(len(doc))]
            finally:
                doc.close()
            return ParsedDocument(document_type="pdf", page_count=len(pages),
                                  total_characters=sum(len(p.text) for p in pages), pages=pages)
        raise
    # 文本 PDF：回填扫描页
    new_pages: list[ParsedPage] = []
    for p in parsed.pages:
        if is_scan_page(p):
            ocr_text = render_ocr_text(pdf_bytes, p.page_number)
            new_pages.append(_build_page_with_ocr(pdf_bytes, p.page_number, ocr_text))
        else:
            new_pages.append(p)
    parsed.pages = new_pages
    parsed.total_characters = sum(len(p.text) for p in new_pages)
    return parsed
