"""PDF 解析器（PyMuPDF）：按物理页提取纯文本、文本块与坐标。纯函数，不写库。

页码规范：
- page_index = PyMuPDF 0 基索引
- page_number = 物理页码 = page_index + 1（金标准/API/前端默认体系）
- printed_page_label = None（财报印刷页码无法可靠识别，后续阶段可增强）

明确不做（Phase 2 边界）：财务指标识别、标题判断、主张提取、表格业务含义、
Embedding、大模型、证据关系判断。
"""

import hashlib

import fitz

from app.core.exceptions import AppError
from app.services.parser.types import ParsedBlock, ParsedDocument, ParsedPage


def _block_type(raw) -> str:
    # PyMuPDF blocks 第 7 项：旧版本为字符串，新版本为 int（0=text, 1=image）
    if isinstance(raw, str):
        return raw
    if isinstance(raw, int):
        return "text" if raw == 0 else "image"
    return "text"


def parse_pdf(data: bytes) -> ParsedDocument:
    """解析 PDF 字节流；加密/无文本/损坏时抛出带统一错误码的 AppError。"""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 —— 损坏 PDF
        raise AppError(
            f"PDF 文件无法打开（可能已损坏）: {exc}", status_code=415, code="INVALID_FILE"
        ) from exc

    try:
        if doc.needs_pass:
            raise AppError("PDF 已加密，不支持解析", status_code=415, code="ENCRYPTED_PDF")

        parsed = ParsedDocument(document_type="pdf")
        total_chars = 0
        for i, page in enumerate(doc):
            text = page.get_text("text")
            raw_blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,block_no,block_type)
            # 阅读顺序：按 (y0, x0) 排序
            ordered = sorted(raw_blocks, key=lambda b: (b[1], b[0]))
            blocks = []
            for idx, b in enumerate(ordered):
                x0, y0, x1, y1, btext, _bno, btype = b
                blocks.append(
                    ParsedBlock(
                        block_index=idx,
                        block_type=_block_type(btype),
                        text=btext if btext.strip() else None,
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        reading_order=idx,
                    )
                )
            char_count = len(text)
            total_chars += char_count
            parsed.pages.append(
                ParsedPage(
                    page_index=i,
                    page_number=i + 1,
                    printed_page_label=None,
                    text=text,
                    character_count=char_count,
                    text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    blocks=blocks,
                )
            )
        parsed.page_count = len(parsed.pages)
        parsed.total_characters = total_chars
        if total_chars == 0:
            raise AppError(
                "PDF 中未提取到任何文字（可能为扫描件），不支持解析",
                status_code=415,
                code="NO_EXTRACTABLE_TEXT",
            )
        return parsed
    finally:
        doc.close()
