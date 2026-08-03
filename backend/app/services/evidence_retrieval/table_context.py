"""Phase 23.10 — Table-aware Evidence 结构化上下文重建。

财务数据不能只按普通文本 block 检索：表头与数据行常被拆成不同 block、
单位写在表格标题、年份写在列标题、指标写在行标题。本模块把同一表格的
多个 block 重建为结构化 TableContext，并生成 Enriched Evidence Text。

字段：
- table_id / page / table_title / section_title / row_header / parent_row_header
- column_header / period_header / unit_header / metric / value / normalized_value
- scope / neighboring_rows / neighboring_columns / continuation_page / source_block_ids

处理：
- 表头与数据行分离（按 y0 分桶：表头行 vs 数据行）
- 单位写在表格标题/表头（"（千元）" / "（元/股）"）
- 年份写在列标题（"2025 年 2024 年"）
- 指标写在行标题（行首文本）
- 同一行多个期间数字（同 y0 多列）
- 同一页多个表（按 y0 间隔分组）
- 跨页表延续（continuation_page：检测表头重复与否）

用法：
    from app.services.evidence_retrieval.table_context import build_table_contexts
    contexts = build_table_contexts(session, doc_id, page_number)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.models import DocumentBlock, DocumentPage

# 行文本中的单位模式（表头/行内）
_UNIT_RE = re.compile(r"[（(]\s*(万亿元|亿元|百万元|万元|千元|元/股|元)\s*[）)]")
# 年份/期间模式（列标题）
_YEAR_COL_RE = re.compile(r"(20\d{2})\s*年")
# 财务数字（千分位或长数字）
_NUM_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{5,})(?!\d)")
_PCT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_NEG_RE = re.compile(r"[（(](-?\d+(?:\.\d+)?)[）)]")
# 表头行关键词（无财务数字的表头）
_HEADER_KW = ("项目", "附注", "年度", "年", "金额", "单位", "项目名称")
# 表格标题/章节标题关键词
_SECTION_KW = ("主要会计数据", "财务指标", "利润表", "资产负债表", "现金流量表", "所有者权益变动表")


@dataclass
class TableContext:
    """结构化表格上下文（一个表格行 + 所属表头/单位/期间上下文）。"""

    table_id: str = ""
    page: int | None = None
    document_id: int | None = None
    table_title: str = ""
    section_title: str = ""
    row_header: str = ""
    parent_row_header: str = ""
    column_header: str = ""
    period_header: str = ""
    unit_header: str = ""
    metric: str = ""
    value: str = ""
    normalized_value: float | None = None
    scope: str = ""
    neighboring_rows: list = field(default_factory=list)
    neighboring_columns: list = field(default_factory=list)
    continuation_page: int | None = None
    source_block_ids: list = field(default_factory=list)

    def enriched_text(self) -> str:
        """Enriched Evidence Text：结构化字段拼接（非整页粗暴拼接）。"""
        parts = []
        if self.table_title:
            parts.append(f"表格：{self.table_title}")
        if self.section_title:
            parts.append(f"章节：{self.section_title}")
        if self.row_header:
            parts.append(f"指标：{self.row_header}")
        if self.parent_row_header:
            parts.append(f"父指标：{self.parent_row_header}")
        if self.column_header:
            parts.append(f"列：{self.column_header}")
        if self.period_header:
            parts.append(f"期间：{self.period_header}")
        if self.unit_header:
            parts.append(f"单位：{self.unit_header}")
        if self.metric:
            parts.append(f"指标标签：{self.metric}")
        if self.value:
            parts.append(f"数值：{self.value}")
        if self.neighboring_rows:
            parts.append("相邻行：" + "；".join(self.neighboring_rows[:5]))
        if self.neighboring_columns:
            parts.append("相邻列：" + "；".join(self.neighboring_columns[:6]))
        if self.continuation_page:
            parts.append(f"延续页：{self.continuation_page}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "table_id": self.table_id, "page": self.page, "document_id": self.document_id,
            "table_title": self.table_title, "section_title": self.section_title,
            "row_header": self.row_header, "parent_row_header": self.parent_row_header,
            "column_header": self.column_header, "period_header": self.period_header,
            "unit_header": self.unit_header, "metric": self.metric, "value": self.value,
            "normalized_value": self.normalized_value, "scope": self.scope,
            "neighboring_rows": self.neighboring_rows[:5],
            "neighboring_columns": self.neighboring_columns[:6],
            "continuation_page": self.continuation_page,
            "source_block_ids": self.source_block_ids,
            "enriched_text": self.enriched_text(),
        }


def _norm_num(tok: str) -> float | None:
    t = tok.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _extract_metric(row_header: str) -> str:
    """从行标题提取指标标签（去掉单位括号/空格）。"""
    h = re.sub(r"[（(][^）)]*[）)]", "", row_header).strip()
    h = re.sub(r"\s+", "", h)
    return h[:40]


def _extract_unit(text: str) -> str:
    m = _UNIT_RE.search(text)
    return m.group(1) if m else ""


def _extract_periods(text: str) -> str:
    years = _YEAR_COL_RE.findall(text)
    if years:
        return " ".join(f"{y}年" for y in years)
    return ""


def _row_has_number(text: str) -> bool:
    return bool(_NUM_RE.search(text) or _PCT_RE.search(text) or _NEG_RE.search(text))


def _row_is_header(text: str) -> bool:
    """表头行：无财务数字 + 含表头关键词（项目/年度/年/附注）。"""
    if _row_has_number(text):
        return False
    return any(k in text for k in _HEADER_KW)


def _scope_of(row_header: str, row_text: str) -> str:
    joined = row_header + row_text
    if "归属于上市公司股东" in joined or "归母" in joined:
        return "parent_attributable"
    if "扣非" in joined or "扣除非经常性损益" in joined:
        return "adjusted"
    if "少数股东" in joined:
        return "non_controlling_interest"
    if "合并" in joined:
        return "consolidated"
    return ""


def build_table_contexts(session, doc_id: int, page_number: int) -> list[TableContext]:
    """从页面块重建结构化表格上下文（y0 行分桶 + 表头/数据行分离）。

    返回该页所有数据行对应的 TableContext；表头行不产出（其上下文进入数据行）。
    """
    rows = (
        session.query(DocumentBlock, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .filter(DocumentBlock.document_id == doc_id, DocumentPage.page_number == page_number)
        .order_by(DocumentBlock.y0, DocumentBlock.x0)
        .all()
    )
    if not rows:
        return []

    # 按 y0 分桶（同一行）：容差 4pt
    buckets: list[list[DocumentBlock]] = []
    for b, _pn in rows:
        if not (b.text or "").strip():
            continue
        if buckets and abs(b.y0 - buckets[-1][0].y0) < 4.0:
            buckets[-1].append(b)
        else:
            buckets.append([b])
    buckets = [sorted(bs, key=lambda x: x.x0) for bs in buckets]

    # 页级：表格标题 / 章节标题（扫描 y0 靠前的非数据行）
    table_title = ""
    section_title = ""
    header_line = ""
    unit_header = ""
    for bs in buckets:
        line = " ".join((b.text or "").strip() for b in bs)
        if _row_has_number(line):
            continue
        if any(k in line for k in _SECTION_KW):
            section_title = section_title or line.strip()[:60]
            continue
        if _row_is_header(line):
            header_line = line.strip()
            unit_header = _extract_unit(line) or unit_header
            continue
        if not table_title and len(line.strip()) > 4:
            table_title = line.strip()[:60]

    # 逐行重建 TableContext
    contexts: list[TableContext] = []
    for idx, bs in enumerate(buckets):
        line = " ".join((b.text or "").strip() for b in bs)
        if not _row_has_number(line):
            continue  # 跳过表头/纯文本行
        # 行首 = 第一个块文本（指标名）；若行首是数字则尝试取前一块
        row_header = ""
        for b in bs:
            t = (b.text or "").strip()
            if not _row_has_number(t):
                row_header = t
                break
        if not row_header and bs:
            row_header = (bs[0].text or "").strip()
        # 数字列（按 x0 顺序提取）
        values: list[str] = []
        for b in bs:
            t = (b.text or "").strip()
            for m in _NUM_RE.finditer(t):
                values.append(m.group(1))
            for m in _NEG_RE.finditer(t):
                values.append(f"-{m.group(1)}")
            for m in _PCT_RE.finditer(t):
                values.append(f"{m.group(1)}%")
        value = values[0] if values else ""
        nv = _norm_num(value)
        # 邻接行（上下各 2 行）
        neighbor_rows = []
        for j in range(max(0, idx - 2), min(len(buckets), idx + 3)):
            if j == idx:
                continue
            nl = " ".join((b.text or "").strip() for b in buckets[j])
            neighbor_rows.append(nl.strip()[:50])
        ctx = TableContext(
            table_id=f"T-{doc_id}-{page_number}-{idx}",
            page=page_number,
            document_id=doc_id,
            table_title=table_title,
            section_title=section_title,
            row_header=row_header.strip(),
            column_header=header_line,
            period_header=_extract_periods(header_line),
            unit_header=unit_header or _extract_unit(line),
            metric=_extract_metric(row_header),
            value=value,
            normalized_value=nv,
            scope=_scope_of(row_header, line),
            neighboring_rows=neighbor_rows,
            neighboring_columns=values[:8],
            source_block_ids=[b.id for b in bs],
        )
        contexts.append(ctx)
    return contexts


def enriched_for_block(session, block_id: int, page_number: int) -> str | None:
    """单 block 的 Enriched Evidence Text（供检索评分注入）。"""
    b = session.get(DocumentBlock, block_id)
    if b is None:
        return None
    ctxs = build_table_contexts(session, b.document_id, page_number)
    for c in ctxs:
        if block_id in c.source_block_ids:
            return c.enriched_text()
    return None


__all__ = ["TableContext", "build_table_contexts", "enriched_for_block"]
