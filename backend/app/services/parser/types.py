"""解析器共享数据结构（PDF 与 Markdown 统一输出形态）。"""

from dataclasses import dataclass, field


@dataclass
class ParsedBlock:
    block_index: int
    block_type: str  # text | image | heading | paragraph
    text: str | None
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    reading_order: int = 0
    start_line: int | None = None  # Markdown 行号范围（1 基）
    end_line: int | None = None
    heading_level: int | None = None  # Markdown 标题层级


@dataclass
class ParsedPage:
    page_index: int  # 0 基（PyMuPDF 下标）
    page_number: int  # 1 基物理页码
    printed_page_label: str | None  # 无法可靠识别时为 None
    text: str
    character_count: int
    text_sha256: str
    blocks: list[ParsedBlock] = field(default_factory=list)


@dataclass
class ParsedDocument:
    document_type: str  # pdf | markdown
    page_count: int = 0
    total_characters: int = 0
    pages: list[ParsedPage] = field(default_factory=list)
