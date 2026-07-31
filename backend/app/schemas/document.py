"""文档 API 的 Pydantic 响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    stored_filename: str
    document_type: str
    document_role: str
    company_name: str | None
    stock_code: str | None
    report_period: str | None
    publication_date: str | None
    mime_type: str
    file_size: int
    sha256: str
    page_count: int
    parse_status: str
    parse_error: str | None
    parse_duration_ms: int | None
    extraction_method: str | None
    created_at: datetime
    updated_at: datetime


class PageListItem(BaseModel):
    page_number: int
    character_count: int
    is_empty: bool
    text_preview: str


class BlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    block_index: int
    block_type: str
    text: str | None
    x0: float | None
    y0: float | None
    x1: float | None
    y1: float | None
    reading_order: int
    heading_level: int | None
    start_line: int | None
    end_line: int | None


class PageDetailOut(BaseModel):
    page_index: int
    page_number: int
    printed_page_label: str | None
    character_count: int
    text: str
    blocks: list[BlockOut]


class UploadResponse(BaseModel):
    document: DocumentOut
    duplicate: bool


class DocumentListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    documents: list[DocumentOut]


class PageListResponse(BaseModel):
    document_id: int
    total_pages: int
    pages: list[PageListItem]
