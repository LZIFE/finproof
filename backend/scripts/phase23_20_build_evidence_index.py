"""Phase 23.20 Task 1 — Financial Evidence Index 构建

遍历各文档的财务表格页，用 Evidence Window Reconstruction（Phase 23.19）
生成结构化 Financial Evidence 对象并持久化到 backend/artifacts/financial_evidence_index/。

对象字段：
{id, company, metric, metric_code, current_value, previous_value, growth,
 unit, period, table_type, source_blocks, page_id}

输出：backend/artifacts/financial_evidence_index/evidence_index_v1.json

Run: cd backend && PYTHONPATH=. python scripts/phase23_20_build_evidence_index.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DB_PATH = REPO_ROOT / "data" / "finproof.db"
OUT_DIR = BACKEND / "artifacts" / "financial_evidence_index"
OUT_PATH = OUT_DIR / "evidence_index_v1.json"
TABLES_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_15_tables.json"

# 只索引财务主表类型（跳过 other 噪声页）
INDEX_TABLE_TYPES = ("income_statement", "balance_sheet", "cash_flow", "equity_changes")


def main() -> int:
    import sqlite3

    from app.services.evidence_retrieval.evidence_window_reconstruction import (
        reconstruct_evidence_window,
    )

    conn = sqlite3.connect(DB_PATH)
    # 文档：id + company_name
    docs = {r[0]: r[1] for r in conn.execute("SELECT id, company_name FROM documents").fetchall()}
    # 表格索引
    tables = json.loads(TABLES_PATH.read_text(encoding="utf-8")).get("tables", [])
    # Phase 23.28 Task 2：章节索引（notes / management_discussion / financial_highlights 抽取）
    SECTIONS_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_15_document_sections.json"
    EXTRA_SECTION_TYPES = ("management_discussion", "notes", "financial_highlights")
    sections = (
        json.loads(SECTIONS_PATH.read_text(encoding="utf-8")).get("sections", [])
        if SECTIONS_PATH.exists() else []
    )
    extra_pages: dict[tuple, str] = {}  # (doc_id, page_number) -> section_type
    for s in sections:
        if s.get("section_type") in EXTRA_SECTION_TYPES:
            for pn in range(s.get("page_start", 0), s.get("page_end", 0) + 1):
                extra_pages[(s.get("document_id"), pn)] = s.get("section_type")

    # 加载 DocumentBlock model（需 ORM session）
    from app.db import SessionLocal
    from app.models import DocumentBlock

    session = SessionLocal()

    evidences: list[dict] = []
    seen_keys: set = set()
    eid = 0

    def _add_evidence(doc_id, page, table_type, block):
        """重建证据对象并去重入库。"""
        nonlocal eid
        obj = reconstruct_evidence_window(session, block)
        if not obj.get("has_number"):
            return
        key = (obj.get("metric"), obj.get("current_value"), doc_id, page)
        if key in seen_keys:
            return
        seen_keys.add(key)
        eid += 1
        evidences.append({
            "id": eid,
            "company": docs.get(doc_id, ""),
            "metric": obj.get("metric", ""),
            "metric_code": obj.get("metric_code", ""),
            "current_value": obj.get("current_value"),
            "previous_value": obj.get("previous_value"),
            "growth": obj.get("growth"),
            "unit": obj.get("unit", ""),
            "period": obj.get("period", ""),
            "periods": obj.get("periods", []),
            "table_type": table_type,
            "source_blocks": obj.get("source_blocks", []),
            "page_id": block.page_id,
            "page_number": page,
            "document_id": doc_id,
            "merged_text": (obj.get("merged_text") or "")[:300],
        })

    # 1) 主表抽取（income_statement / balance_sheet / cash_flow / equity_changes）
    for t in tables:
        if t.get("table_type") not in INDEX_TABLE_TYPES:
            continue
        doc_id = t.get("document_id")
        page = t.get("page")
        blocks = t.get("blocks") or []
        if not blocks:
            continue
        for bid in blocks:
            block = session.query(DocumentBlock).filter(DocumentBlock.id == bid).first()
            if block is None or not block.text:
                continue
            _add_evidence(doc_id, page, t.get("table_type", "other"), block)

    # 2) Phase 23.28：附注 / 管理层讨论 / 主要财务指标章节抽取
    page_id_cache: dict = {}
    for (doc_id, pn), stype in extra_pages.items():
        # page_number -> page_id（缓存）
        if (doc_id, pn) not in page_id_cache:
            row = conn.execute(
                "SELECT id FROM document_pages WHERE document_id=? AND page_number=?",
                (doc_id, pn),
            ).fetchone()
            page_id_cache[(doc_id, pn)] = row[0] if row else None
        pid = page_id_cache[(doc_id, pn)]
        if pid is None:
            continue
        blocks = conn.execute(
            "SELECT id FROM document_blocks WHERE page_id=? AND text IS NOT NULL AND text != '' ORDER BY block_index",
            (pid,),
        ).fetchall()
        for (bid,) in blocks:
            block = session.query(DocumentBlock).filter(DocumentBlock.id == bid).first()
            if block is None or not block.text:
                continue
            _add_evidence(doc_id, pn, stype, block)

    session.close()
    conn.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "phase": "23.20",
        "step": "1_financial_evidence_index",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": "v1",
        "total": len(evidences),
        "table_types": {tt: sum(1 for e in evidences if e["table_type"] == tt) for tt in INDEX_TABLE_TYPES},
        "evidence": evidences,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote: {OUT_PATH} ({len(evidences)} evidence objects)")
    print(f"table_types: {out['table_types']}")
    # 抽样验证
    for e in evidences[:5]:
        print(f"  id={e['id']} {e['company']} {e['metric']} current={e['current_value']} prev={e['previous_value']} growth={e['growth']} unit={e['unit']} page={e['page_number']} blocks={e['source_blocks'][:4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
