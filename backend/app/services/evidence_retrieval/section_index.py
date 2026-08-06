"""Phase 23.15 Step 4 — Section-aware Retrieval 模块

在 retrieve_for_claim 的候选生成前，用 Claim→Section Routing + document_sections 索引
把检索范围收窄到目标章节页（section → table → block 三级），并对目标章节页块加分。

核心：
- load_section_index(): 加载 document_sections.json（章节页范围）
- load_table_index(): 加载 tables.json（表格页 + blocks）
- target_pages_for_claim(): claim → 目标章节页集合
- section_bonus_for_page(): 页是否在目标章节内 → 加分

被 service.retrieve_for_claim 调用（Phase 23.15 接入点）。
"""
from __future__ import annotations

import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]  # backend/app/services/evidence_retrieval/ → 上3级 = backend/
REPO_ROOT = BACKEND.parent

_SECTIONS_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_15_document_sections.json"
_TABLES_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_15_tables.json"

_sections_cache: list[dict] | None = None
_tables_cache: list[dict] | None = None


def load_section_index() -> list[dict]:
    """加载 document_sections 索引（doc_id → [(page_start, page_end, section_type)]）。"""
    global _sections_cache
    if _sections_cache is None:
        if _SECTIONS_PATH.exists():
            _sections_cache = json.loads(_SECTIONS_PATH.read_text(encoding="utf-8")).get("sections", [])
        else:
            _sections_cache = []
    return _sections_cache


def load_table_index() -> list[dict]:
    """加载 tables 索引（doc_id+page → table_type/blocks）。"""
    global _tables_cache
    if _tables_cache is None:
        if _TABLES_PATH.exists():
            _tables_cache = json.loads(_TABLES_PATH.read_text(encoding="utf-8")).get("tables", [])
        else:
            _tables_cache = []
    return _tables_cache


def sections_for_document(document_id: int) -> list[dict]:
    """该文档的章节列表。"""
    return [s for s in load_section_index() if s.get("document_id") == document_id]


def tables_for_document(document_id: int) -> list[dict]:
    """该文档的表格页列表。"""
    return [t for t in load_table_index() if t.get("document_id") == document_id]


def page_section_types(document_id: int, page_number: int) -> list[str]:
    """页所在的章节类型列表（跨章节边界可能多个）。"""
    out: list[str] = []
    for s in sections_for_document(document_id):
        if s.get("page_start") <= page_number <= s.get("page_end"):
            out.append(s.get("section_type", ""))
    return [t for t in out if t]


def target_pages_for_claim(document_id: int, sections: list[str]) -> set[int]:
    """claim 路由的章节类型 → 目标物理页集合（含表格页优先）。"""
    pages: set[int] = set()
    for s in sections_for_document(document_id):
        if s.get("section_type") in sections:
            pages.update(range(s.get("page_start", 0), s.get("page_end", 0) + 1))
    return pages


def table_pages_for_types(document_id: int, sections: list[str]) -> set[int]:
    """表格索引中属于目标章节类型的页集合（table 级检索）。"""
    pages: set[int] = set()
    for t in tables_for_document(document_id):
        if t.get("table_type") in sections or t.get("table_type") == "other":
            pages.add(t.get("page"))
    return pages


def section_bonus_for_page(document_id: int, page_number: int, sections: list[str]) -> float:
    """页是否落在目标章节 → 返回加分（0 或 1）。"""
    types = page_section_types(document_id, page_number)
    if not sections:
        return 0.0
    if any(t in sections for t in types):
        return 1.0
    return 0.0
