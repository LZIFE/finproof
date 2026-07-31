"""文档服务层单元测试：注册/去重/同名不同内容/安全校验/失败回滚与状态映射。"""

import fitz
import pytest

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db import SessionLocal
from app.services import document_service as svc


def _pdf_bytes(text: str = "中文内容", pages: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page()
        pg.insert_text((72, 72), f"{text} {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def _blank_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def _encrypted_pdf() -> bytes:
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "secret")
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    return data


def test_register_pdf_completed():
    with SessionLocal() as s:
        doc, dup = svc.register_document(s, filename="test.pdf", data=_pdf_bytes())
        assert doc.parse_status == "COMPLETED"
        assert doc.page_count == 2
        assert doc.document_type == "pdf"
        assert dup is False


def test_register_markdown():
    with SessionLocal() as s:
        doc, _ = svc.register_document(s, filename="r.md", data="# 标题\n\n正文。".encode("utf-8"))
        assert doc.document_type == "markdown"
        assert doc.page_count == 1
        assert doc.parse_status == "COMPLETED"
        assert doc.extraction_method == "markdown_parser"


def test_duplicate_same_content():
    data = _pdf_bytes()
    with SessionLocal() as s:
        d1, _ = svc.register_document(s, filename="a.pdf", data=data)
        d2, dup = svc.register_document(s, filename="b.pdf", data=data)
        assert dup is True
        assert d2.id == d1.id
        assert s.query(svc.Document).count() == 1


def test_same_name_different_content():
    with SessionLocal() as s:
        d1, _ = svc.register_document(s, filename="x.pdf", data=_pdf_bytes("AAA"))
        d2, _ = svc.register_document(s, filename="x.pdf", data=_pdf_bytes("BBB"))
        assert d1.id != d2.id
        assert s.query(svc.Document).count() == 2


def test_invalid_extension_no_row():
    with SessionLocal() as s:
        with pytest.raises(AppError) as ei:
            svc.register_document(s, filename="evil.exe", data=b"%PDF")
        assert ei.value.code == "UNSUPPORTED_DOCUMENT"
        assert s.query(svc.Document).count() == 0


def test_fake_pdf_no_row():
    with SessionLocal() as s:
        with pytest.raises(AppError) as ei:
            svc.register_document(s, filename="fake.pdf", data=b"not a pdf at all")
        assert ei.value.code == "INVALID_FILE"
        assert s.query(svc.Document).count() == 0


def test_empty_file():
    with SessionLocal() as s:
        with pytest.raises(AppError) as ei:
            svc.register_document(s, filename="empty.pdf", data=b"")
        assert ei.value.code == "EMPTY_FILE"


def test_encrypted_pdf_rejected_no_row():
    with SessionLocal() as s:
        with pytest.raises(AppError) as ei:
            svc.register_document(s, filename="enc.pdf", data=_encrypted_pdf())
        assert ei.value.code == "ENCRYPTED_PDF"
        assert s.query(svc.Document).count() == 0


def test_no_text_pdf_unsupported_row_no_pages():
    with SessionLocal() as s:
        with pytest.raises(AppError) as ei:
            svc.register_document(s, filename="blank.pdf", data=_blank_pdf())
        assert ei.value.code == "NO_EXTRACTABLE_TEXT"
        doc = s.query(svc.Document).filter(svc.Document.original_filename == "blank.pdf").first()
        assert doc is not None
        assert doc.parse_status == "UNSUPPORTED"
        assert len(svc.get_document_pages(s, doc.id)) == 0


def test_corrupt_pdf_no_pages_residue():
    with SessionLocal() as s:
        try:
            svc.register_document(s, filename="bad.pdf", data=b"%PDF-1.4 " + b"0" * 300)
        except AppError as e:
            assert e.code in ("INVALID_FILE", "NO_EXTRACTABLE_TEXT")
        rows = s.query(svc.Document).filter(svc.Document.original_filename == "bad.pdf").all()
        assert all(len(svc.get_document_pages(s, r.id)) == 0 for r in rows)


def test_file_too_large(monkeypatch):
    monkeypatch.setenv("FINPROOF_MAX_UPLOAD_SIZE_MB", "0")  # 0 MB：任何非空文件都超限
    get_settings.cache_clear()
    try:
        with SessionLocal() as s:
            with pytest.raises(AppError) as ei:
                svc.register_document(s, filename="big.pdf", data=_pdf_bytes())
            assert ei.value.code == "FILE_TOO_LARGE"
    finally:
        get_settings.cache_clear()


def test_path_traversal_filename_sanitized():
    with SessionLocal() as s:
        doc, _ = svc.register_document(s, filename="../../etc/passwd.pdf", data=_pdf_bytes())
        assert doc.original_filename == "passwd.pdf"
        assert doc.stored_filename == "original.pdf"


def test_parse_failure_marks_failed_and_rolls_back(monkeypatch):
    def boom(data):
        raise RuntimeError("simulated parse failure")

    monkeypatch.setattr(svc, "parse_pdf", boom)
    with SessionLocal() as s:
        with pytest.raises(AppError) as ei:
            svc.register_document(s, filename="boom.pdf", data=_pdf_bytes())
        assert ei.value.code == "PARSE_FAILED"
        doc = s.query(svc.Document).filter(svc.Document.original_filename == "boom.pdf").first()
        assert doc is not None
        assert doc.parse_status == "FAILED"
        assert "RuntimeError" in doc.parse_error
        assert len(svc.get_document_pages(s, doc.id)) == 0


def test_list_filter_and_pagination():
    with SessionLocal() as s:
        svc.register_document(s, filename="a.pdf", data=_pdf_bytes("A"), document_role="SOURCE_DOCUMENT")
        svc.register_document(s, filename="b.md", data="# b".encode(), document_role="REPORT_TO_VERIFY")
        total, docs = svc.list_documents(s, role="SOURCE_DOCUMENT", page=1, page_size=10)
        assert total == 1 and docs[0].original_filename == "a.pdf"
        total2, _ = svc.list_documents(s, status="COMPLETED")
        assert total2 == 2
        total3, _ = svc.list_documents(s, page=1, page_size=1)
        assert total3 == 2 and len(docs) >= 1


def test_get_document_or_404():
    with SessionLocal() as s:
        with pytest.raises(AppError) as ei:
            svc.get_document_or_404(s, 99999)
        assert ei.value.code == "DOCUMENT_NOT_FOUND"
