"""解析器单元测试：PDF（多页/中文/页码映射/文本块坐标/加密/无文本/损坏）与 Markdown。"""

import fitz
import pytest

from app.core.exceptions import AppError
from app.services.parser.markdown_parser import parse_markdown
from app.services.parser.pdf_parser import parse_pdf


def _make_pdf(texts: list[str] | None = None) -> bytes:
    doc = fitz.open()
    for i, t in enumerate(texts or ["中文第 1 页内容 finproof", "第二页内容"]):
        pg = doc.new_page()
        # china-s：PyMuPDF 内置简体中文字体，保证中文可正确往返提取
        pg.insert_text((72, 72), t, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def _make_two_block_pdf() -> bytes:
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "块一内容", fontname="china-s")
    pg.insert_text((72, 200), "块二内容", fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


# ---------- PDF ----------

def test_pdf_basic_extraction():
    parsed = parse_pdf(_make_pdf(["中文财务报告测试营业收入", "第二页内容"]))
    assert parsed.document_type == "pdf"
    assert parsed.page_count == 2
    assert parsed.total_characters > 0


def test_pdf_chinese_text():
    parsed = parse_pdf(_make_pdf(["中文财务报告测试营业收入"]))
    assert "营业收入" in parsed.pages[0].text


def test_pdf_page_number_mapping():
    parsed = parse_pdf(_make_pdf([f"第 {i} 页" for i in range(5)]))
    assert [p.page_number for p in parsed.pages] == [1, 2, 3, 4, 5]
    for p in parsed.pages:
        assert p.page_number == p.page_index + 1


def test_pdf_page_count_matches_pymupdf():
    data = _make_pdf(["a", "b", "c", "d"])
    doc = fitz.open(stream=data, filetype="pdf")
    n = len(doc)
    doc.close()
    assert parse_pdf(data).page_count == n == 4


def test_pdf_blocks_coordinates_and_reading_order():
    parsed = parse_pdf(_make_two_block_pdf())
    blocks = parsed.pages[0].blocks
    assert len(blocks) >= 2
    for b in blocks:
        assert b.x0 is not None and b.y0 is not None and b.x1 is not None and b.y1 is not None
        assert b.reading_order == b.block_index
    assert [b.y0 for b in blocks] == sorted(b.y0 for b in blocks)  # 阅读顺序按 y 排序


def test_pdf_encrypted_rejected():
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "secret")
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    with pytest.raises(AppError) as ei:
        parse_pdf(data)
    assert ei.value.code == "ENCRYPTED_PDF"


def test_pdf_no_text_rejected():
    doc = fitz.open()
    doc.new_page()  # 空白页
    data = doc.tobytes()
    doc.close()
    with pytest.raises(AppError) as ei:
        parse_pdf(data)
    assert ei.value.code == "NO_EXTRACTABLE_TEXT"


def test_pdf_corrupt_rejected():
    with pytest.raises(AppError) as ei:
        parse_pdf(b"%PDF-1.4 " + b"0" * 300)
    assert ei.value.code == "INVALID_FILE"


# ---------- Markdown ----------

def test_markdown_single_page_convention():
    parsed = parse_markdown("# 标题\n\n正文。")
    assert parsed.document_type == "markdown"
    assert parsed.page_count == 1
    page = parsed.pages[0]
    assert page.page_index == 0
    assert page.page_number == 1
    assert page.printed_page_label is None


def test_markdown_paragraph_order_and_lines():
    text = "# 标题\n\n第一段。\n第二行。\n\n第二段。\n"
    parsed = parse_markdown(text)
    blocks = parsed.pages[0].blocks
    assert [b.block_type for b in blocks] == ["heading", "paragraph", "paragraph"]
    assert blocks[0].heading_level == 1 and blocks[0].start_line == 1
    assert blocks[1].start_line == 3 and blocks[1].end_line == 4
    assert blocks[2].start_line == 6 and blocks[2].end_line == 6
    assert [b.reading_order for b in blocks] == [0, 1, 2]


def test_markdown_heading_levels():
    text = "# h1\n## h2\n### h3\n正文\n"
    blocks = parse_markdown(text).pages[0].blocks
    assert [b.heading_level for b in blocks if b.block_type == "heading"] == [1, 2, 3]


def test_markdown_full_text_preserved():
    text = "# 标题\n\n正文内容。\n"
    parsed = parse_markdown(text)
    assert parsed.pages[0].text == text
    assert parsed.total_characters == len(text)
    assert parsed.pages[0].text_sha256
