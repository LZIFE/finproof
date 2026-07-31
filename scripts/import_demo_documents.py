#!/usr/bin/env python3
"""批量导入演示文档（Phase 2）。

用法：backend/.venv/bin/python scripts/import_demo_documents.py

要求：
- 与 API 共用同一套 document_service（不维护第二套解析逻辑）
- 可重复运行：重复导入同一文件走 SHA-256 去重，返回既有文档，不产生重复数据
- 输出每个文件的 document_id / 页数 / 字符数；失败时给出清晰错误并以非零码退出
- 不写死数据库主键（主键由服务层生成）
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.logging import setup_logging  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services import document_service as svc  # noqa: E402

setup_logging()

DEMO_FILES = [
    {
        "path": "data/demo/source/annual_report.pdf",
        "role": "SOURCE_DOCUMENT",
        "company": "美的集团",
        "code": "000333",
        "period": "2025FY",
        "pub": "2026-03-31",
    },
    {
        "path": "data/demo/source/q1_report.pdf",
        "role": "SOURCE_DOCUMENT",
        "company": "美的集团",
        "code": "000333",
        "period": "2025Q1",
        "pub": "2025-04-30",
    },
    {
        "path": "data/demo/source/half_year_report.pdf",
        "role": "SOURCE_DOCUMENT",
        "company": "美的集团",
        "code": "000333",
        "period": "2025H1",
        "pub": "2025-08-30",
    },
    {
        "path": "data/demo/reports/ai_report_with_errors.md",
        "role": "REPORT_TO_VERIFY",
        "company": "美的集团",
        "code": "000333",
        "period": "2025FY",
        "pub": None,
    },
    {
        "path": "data/demo/reports/corrected_report.md",
        "role": "REFERENCE_REPORT",
        "company": "美的集团",
        "code": "000333",
        "period": "2025FY",
        "pub": None,
    },
]


def main() -> int:
    init_db()
    ok = True
    with SessionLocal() as session:
        for item in DEMO_FILES:
            path = Path(item["path"])
            if not path.exists():
                print(f"[错误] 文件不存在: {path}")
                ok = False
                continue
            try:
                doc, duplicate = svc.register_document(
                    session,
                    filename=path.name,
                    data=path.read_bytes(),
                    document_role=item["role"],
                    company_name=item["company"],
                    stock_code=item["code"],
                    report_period=item["period"],
                    publication_date=item["pub"],
                )
                pages = svc.get_document_pages(session, doc.id)
                total_chars = sum(p.character_count for p in pages)
                tag = "去重" if duplicate else "新增"
                print(
                    f"[{tag}] {path.name} -> document_id={doc.id} "
                    f"status={doc.parse_status} pages={doc.page_count} chars={total_chars} "
                    f"duration_ms={doc.parse_duration_ms}"
                )
                if doc.parse_status != "COMPLETED":
                    print(f"       解析未完成: {doc.parse_error}")
                    ok = False
            except Exception as exc:  # noqa: BLE001
                print(f"[错误] {path.name}: {exc}")
                ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
