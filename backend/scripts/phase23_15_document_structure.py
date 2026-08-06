"""Phase 23.15 Step 1/2 — Document Structure Analysis + Table Detection

扫描 PDF（PyMuPDF），建立 document_sections 索引：
- 利润表 income_statement
- 资产负债表 balance_sheet
- 现金流量表 cash_flow
- 经营情况分析 management_discussion (MD&A)
- 业务章节 business
- 附注 notes

同时识别表格区域（table detection）：
- 表头页 + 数据行块（含数字/年份/单位/指标行）
- table_type: income_statement / balance_sheet / cash_flow / other

输出：
- backend/artifacts/gold_contract/phase23_15_document_sections.json
- backend/artifacts/gold_contract/phase23_15_tables.json

Run: cd backend && PYTHONPATH=. python scripts/phase23_15_document_structure.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
DB_PATH = REPO_ROOT / "data" / "finproof.db"
PDF_DIR = REPO_ROOT / "data" / "demo" / "source"
OUT_SECTIONS = BACKEND / "artifacts" / "gold_contract" / "phase23_15_document_sections.json"
OUT_TABLES = BACKEND / "artifacts" / "gold_contract" / "phase23_15_tables.json"

# 章节类型 → 页面首行关键词（精确匹配财务表标题）
SECTION_PATTERNS: list[tuple[str, tuple[str, ...], float]] = [
    ("income_statement", ("合并及公司利润表", "合并利润表", "利润表"), 0.98),
    ("balance_sheet", ("合并及公司资产负债表", "合并资产负债表", "资产负债表"), 0.98),
    ("cash_flow", ("合并及公司现金流量表", "合并现金流量表", "现金流量表"), 0.98),
    ("equity_changes", ("所有者权益变动表", "股东权益变动表"), 0.9),
    ("notes", ("财务报表附注", "附注"), 0.85),
    ("management_discussion", ("管理层讨论与分析", "经营情况讨论与分析"), 0.9),
    ("business", ("从事的主要业务", "业务概要", "经营情况分析", "主要经营情况"), 0.8),
    ("financial_highlights", ("主要会计数据", "主要财务指标"), 0.9),
    ("company_profile", ("公司简介", "公司信息"), 0.8),
]

# 表格识别：页内行关键词（表头 + 数据行）
_TABLE_HEADER_KW = ("项目", "附注", "2025年度", "2024年度", "年初余额", "期末余额", "本期金额", "上期金额", "合并", "公司")
_TABLE_METRIC_KW = ("收入", "利润", "成本", "费用", "收益", "资产", "负债", "权益", "现金流", "每股", "毛利率")
_TABLE_UNIT_KW = ("千元", "万元", "亿元", "元")


def _section_type_of(head_lines: list[str]) -> tuple[str, float] | None:
    """根据页首几行识别章节类型。"""
    joined = " ".join(head_lines)
    for stype, kws, conf in SECTION_PATTERNS:
        for kw in kws:
            if kw in joined:
                return stype, conf
    return None


def _is_table_page(text: str) -> bool:
    """页内是否含表格特征（表头关键词 + 指标行 + 单位 + 数字）。"""
    if any(kw in text for kw in _TABLE_HEADER_KW) and any(kw in text for kw in _TABLE_METRIC_KW):
        return True
    return any(u in text for u in _TABLE_UNIT_KW) and re.search(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", text)


def main() -> int:
    import fitz

    conn = sqlite3.connect(DB_PATH)
    # 文档列表（SOURCE_DOCUMENT）
    docs = conn.execute(
        "SELECT id, original_filename, report_period FROM documents WHERE document_role='SOURCE_DOCUMENT'"
    ).fetchall()
    print(f"documents: {docs}")

    all_sections = []
    all_tables = []
    sec_id = 0
    tbl_id = 0

    for doc_id, fname, period in docs:
        pdf_path = PDF_DIR / fname
        if not pdf_path.exists():
            print(f"  skip missing PDF: {pdf_path}")
            continue
        doc = fitz.open(pdf_path)
        print(f"\n=== doc_id={doc_id} {fname} pages={doc.page_count} ===")

        # 逐页识别章节起始
        page_sections: list[tuple[int, str, float]] = []  # (page, section_type, confidence)
        for i in range(doc.page_count):
            text = doc[i].get_text("text")
            head_lines = [l.strip() for l in text.splitlines()[:14] if l.strip()]
            hit = _section_type_of(head_lines)
            if hit:
                page_sections.append((i + 1, hit[0], hit[1]))

        # 合并连续同类型页 → 章节（page_start..page_end）
        if page_sections:
            cur_page, cur_type, cur_conf = page_sections[0]
            start = cur_page
            for pg, st, conf in page_sections[1:]:
                if st == cur_type and pg == start + (page_sections.index((cur_page, cur_type, cur_conf)) + 1):
                    # 同类型连续页合并
                    pass
                if st == cur_type:
                    # 同类型：合并范围（start..pg）
                    cur_page = pg
                    continue
                sec_id += 1
                all_sections.append({
                    "id": sec_id,
                    "document_id": doc_id,
                    "page_start": start,
                    "page_end": cur_page,
                    "section_type": cur_type,
                    "confidence": cur_conf,
                })
                start = pg
                cur_page = pg
                cur_type, cur_conf = st, conf
            sec_id += 1
            all_sections.append({
                "id": sec_id,
                "document_id": doc_id,
                "page_start": start,
                "page_end": cur_page,
                "section_type": cur_type,
                "confidence": cur_conf,
            })

        # 表格检测：含表格特征的页 → table 记录
        for i in range(doc.page_count):
            text = doc[i].get_text("text")
            if not _is_table_page(text):
                continue
            # 从页首识别 table_type
            head_lines = [l.strip() for l in text.splitlines()[:14] if l.strip()]
            joined = " ".join(head_lines)
            ttype = "other"
            if "利润表" in joined:
                ttype = "income_statement"
            elif "资产负债表" in joined:
                ttype = "balance_sheet"
            elif "现金流量表" in joined:
                ttype = "cash_flow"
            elif "所有者权益" in joined:
                ttype = "equity_changes"
            tbl_id += 1
            all_tables.append({
                "id": tbl_id,
                "document_id": doc_id,
                "page": i + 1,
                "table_type": ttype,
                "has_numbers": bool(re.search(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", text)),
                "has_units": any(u in text for u in _TABLE_UNIT_KW),
                "blocks": [],  # 由 Step 4 填充实际 block_ids
            })
        doc.close()

    conn.close()

    OUT_SECTIONS.parent.mkdir(parents=True, exist_ok=True)
    sections_out = {
        "phase": "23.15",
        "step": "1_document_sections",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_sections": len(all_sections),
        "sections": all_sections,
    }
    OUT_SECTIONS.write_text(json.dumps(sections_out, ensure_ascii=False, indent=2), encoding="utf-8")

    tables_out = {
        "phase": "23.15",
        "step": "2_table_detection",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_tables": len(all_tables),
        "tables": all_tables,
    }
    OUT_TABLES.write_text(json.dumps(tables_out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nwrote: {OUT_SECTIONS} ({len(all_sections)} sections)")
    print(f"wrote: {OUT_TABLES} ({len(all_tables)} tables)")
    from collections import Counter
    print("section types:", dict(Counter(s["section_type"] for s in all_sections)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
