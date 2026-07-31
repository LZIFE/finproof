"""演示数据集成测试：使用美的集团三份真实 PDF 验证解析链路与幂等导入。

验证点：
1. 三份 PDF 全部解析成功（COMPLETED）
2. 数据库页数与 PyMuPDF 页数完全一致（276 / 11 / 205）
3. 每页 page_number = page_index + 1
4. 总字符数大于合理下限
5. 关键证据页能够提取到对应文本
6. PDF 重新导入不会重复生成数据
"""

import fitz
import pytest

from app.db import SessionLocal
from app.services import document_service as svc

REPO_ROOT = pytest.__file__ and __import__("pathlib").Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "data" / "demo" / "source"

DEMO_PDFS = [
    ("annual_report.pdf", 276, 200_000),
    ("q1_report.pdf", 11, 10_000),
    ("half_year_report.pdf", 205, 150_000),
]

# 关键证据页锚点（来自金标准，页号 = PDF 物理页码 page_number）
KEY_PAGE_EXPECTATIONS = [
    ("annual_report.pdf", 9, ["营业收入", "456,451,731", "407,149,600", "12.11%"]),
    ("annual_report.pdf", 135, ["营业总收入", "458,502,407", "409,084,266"]),
    ("q1_report.pdf", 2, ["营业收入", "127,838,538", "20.49%"]),
    ("half_year_report.pdf", 17, ["营业总收入2523", "15.7%", "OBM"]),
    ("half_year_report.pdf", 96, ["252,331,494", "218,121,839", "26,013,690"]),
]


def _norm(s: str) -> str:
    import re

    return re.sub(r"\s+", "", s)


def _pymupdf_page_count(path) -> int:
    doc = fitz.open(str(path))
    n = len(doc)
    doc.close()
    return n


def test_all_demo_pdfs_parse_completed():
    with SessionLocal() as s:
        for name, _pages, _chars in DEMO_PDFS:
            doc, _ = svc.register_document(
                s, filename=name, data=(SOURCE_DIR / name).read_bytes(),
                document_role="SOURCE_DOCUMENT", company_name="美的集团",
                stock_code="000333",
            )
            assert doc.parse_status == "COMPLETED", f"{name}: {doc.parse_error}"


def test_page_count_matches_pymupdf():
    with SessionLocal() as s:
        for name, expected_pages, _min_chars in DEMO_PDFS:
            doc, _ = svc.register_document(
                s, filename=name, data=(SOURCE_DIR / name).read_bytes()
            )
            assert doc.page_count == expected_pages
            assert doc.page_count == _pymupdf_page_count(SOURCE_DIR / name)
            pages = svc.get_document_pages(s, doc.id)
            assert len(pages) == expected_pages
            for p in pages:
                assert p.page_number == p.page_index + 1


def test_total_characters_above_floor():
    with SessionLocal() as s:
        for name, _pages, min_chars in DEMO_PDFS:
            doc, _ = svc.register_document(
                s, filename=name, data=(SOURCE_DIR / name).read_bytes()
            )
            pages = svc.get_document_pages(s, doc.id)
            total = sum(p.character_count for p in pages)
            assert total > min_chars, f"{name}: {total} 字符低于下限 {min_chars}"


def test_key_evidence_pages_extractable():
    """关键证据页能读到文本且含核心数字/关键词（空白归一化后）。"""
    with SessionLocal() as s:
        for name, page_no, keywords in KEY_PAGE_EXPECTATIONS:
            doc, _ = svc.register_document(
                s, filename=name, data=(SOURCE_DIR / name).read_bytes()
            )
            page = svc.get_document_page(s, doc.id, page_no)
            assert page.text.strip(), f"{name} 第 {page_no} 页为空"
            norm_text = _norm(page.text)
            for kw in keywords:
                assert _norm(kw) in norm_text, f"{name} p{page_no} 未找到关键词 {kw}"


def test_reimport_is_idempotent():
    with SessionLocal() as s:
        ids = []
        for name, _pages, _chars in DEMO_PDFS:
            data = (SOURCE_DIR / name).read_bytes()
            d1, _ = svc.register_document(s, filename=name, data=data)
            d2, dup = svc.register_document(s, filename=f"again_{name}", data=data)
            ids.append(d1.id)
            assert dup is True
            assert d2.id == d1.id
        assert len(ids) == 3
        assert s.query(svc.Document).count() == 3  # 无重复数据
