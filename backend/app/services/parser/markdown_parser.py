"""Markdown 解析器：保留完整原文、标题层级与段落顺序，按行号定位。

页码约定（不虚构 PDF 页码）：
- Markdown 作为单逻辑页：page_index = 0，page_number = 1
- 定位依据为 block 的 start_line / end_line（1 基行号）与 heading_level

block_type：heading（# 开头）| paragraph（连续非空行）。
"""

import hashlib

from app.services.parser.types import ParsedBlock, ParsedDocument, ParsedPage


def parse_markdown(text: str) -> ParsedDocument:
    lines = text.splitlines()
    blocks: list[ParsedBlock] = []
    idx = 0
    para_lines: list[tuple[int, str]] = []

    def flush_paragraph() -> None:
        nonlocal idx
        if not para_lines:
            return
        start = para_lines[0][0]
        end = para_lines[-1][0]
        content = "\n".join(raw for _, raw in para_lines)
        blocks.append(
            ParsedBlock(
                block_index=idx,
                block_type="paragraph",
                text=content,
                reading_order=idx,
                start_line=start,
                end_line=end,
            )
        )
        idx += 1
        para_lines.clear()

    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            blocks.append(
                ParsedBlock(
                    block_index=idx,
                    block_type="heading",
                    text=title,
                    reading_order=idx,
                    start_line=lineno,
                    end_line=lineno,
                    heading_level=level,
                )
            )
            idx += 1
        else:
            para_lines.append((lineno, raw))
    flush_paragraph()

    page = ParsedPage(
        page_index=0,
        page_number=1,
        printed_page_label=None,
        text=text,
        character_count=len(text),
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        blocks=blocks,
    )
    return ParsedDocument(
        document_type="markdown",
        page_count=1,
        total_characters=len(text),
        pages=[page],
    )
