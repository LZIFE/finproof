"""Phase 23.11.6 — Block 正文注入脚本（盲审输入生成）

流程：
1. 读取 data/gold_review/phase23_11_6/review_items.json
2. 对每个 candidate_group 的 block_ids，按原始顺序从 documents 表查坐标，
   再用 PyMuPDF 打开原始 PDF，按坐标重新提取 block 正文。
3. 生成 review_items_with_block_text.json（中间文件，不污染原始数据）。
4. 同时生成 block_text_injection.log，记录每条 block 的提取状态。

字段说明：
- block_text_status: OK | EMPTY_BLOCK | MISSING_BLOCK_TEXT
  - OK: 成功提取到非空正文
  - EMPTY_BLOCK: 提取到空字符串（财报表格真空单元格，非数据缺失）
  - MISSING_BLOCK_TEXT: PDF 打不开 / 坐标越界 / 提取异常

注入到 candidate_group 的新字段：
- blocks: [{block_id, block_index, block_type, x0,y0,x1,y1,
            block_text, block_text_status}]
- context_before / context_after: 保留原样
- candidate_group_id / page: 保留原样

严格不注入的字段（盲审信息隔离）：
- expected_verdict / gold_verdict / 系统 prediction
- reconstruction_coverage（旧字段，保留但不进提示词）
- 已有审核结果（review_results_agent*.json）
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import fitz  # PyMuPDF

# 路径
REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "finproof.db"
REVIEW_ITEMS_PATH = (
    REPO_ROOT / "data" / "gold_review" / "phase23_11_6" / "review_items.json"
)
OUTPUT_PATH = (
    REPO_ROOT
    / "data"
    / "gold_review"
    / "phase23_11_6"
    / "review_items_with_block_text.json"
)
LOG_PATH = (
    REPO_ROOT / "data" / "gold_review" / "phase23_11_6" / "block_text_injection.log"
)

# PDF 来源映射：documents.original_filename -> data/demo/source/<file>
# （documents 表 stored_filename='original.pdf' 不可靠，按 original_filename 定位）
PDF_SOURCE_DIR = REPO_ROOT / "data" / "demo" / "source"


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logger = logging.getLogger("block_text_injection")
logger.setLevel(logging.INFO)


def setup_logging() -> None:
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    # 也输出到 stderr，便于直接运行查看
    import sys

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)


# ---------------------------------------------------------------------------
# Block 正文提取
# ---------------------------------------------------------------------------

# PDF 文档缓存：{document_id: fitz.Document}
_pdf_cache: dict[int, fitz.Document] = {}
# 坐标缓存：{block_id: (page_id, block_index, x0, y0, x1, y1, document_id)}
_coord_cache: dict[int, tuple] = {}


def _open_pdf(document_id: int, original_filename: str) -> fitz.Document | None:
    """打开并缓存 PDF。失败返回 None。"""
    if document_id in _pdf_cache:
        return _pdf_cache[document_id]
    pdf_path = PDF_SOURCE_DIR / original_filename
    if not pdf_path.exists():
        logger.error(
            "doc_id=%d PDF not found: %s", document_id, pdf_path
        )
        return None
    try:
        doc = fitz.open(pdf_path)
        _pdf_cache[document_id] = doc
        logger.info("doc_id=%d opened PDF: %s (pages=%d)", document_id, pdf_path, doc.page_count)
        return doc
    except Exception as exc:  # noqa: BLE001
        logger.error("doc_id=%d PDF open failed: %s", document_id, exc)
        return None


def _load_block_coords(conn: sqlite3.Connection, block_ids: list) -> None:
    """预加载 block 坐标到缓存。

    block_ids 可能是 str 或 int；同时用两种 key 存入缓存，避免类型不匹配。
    """
    if not block_ids:
        return
    int_bids = [int(b) for b in block_ids]
    qs = ",".join(["?"] * len(int_bids))
    rows = conn.execute(
        f"SELECT id, page_id, block_index, x0, y0, x1, y1, document_id "
        f"FROM document_blocks WHERE id IN ({qs})",
        int_bids,
    ).fetchall()
    for r in rows:
        coord_tuple = r[1:]  # (page_id, block_index, x0, y0, x1, y1, document_id)
        _coord_cache[r[0]] = coord_tuple  # int key
        _coord_cache[str(r[0])] = coord_tuple  # str key


def _get_document_filename(conn: sqlite3.Connection, document_id: int) -> str | None:
    """通过 document_id 查 documents.original_filename。"""
    row = conn.execute(
        "SELECT original_filename FROM documents WHERE id=?", (document_id,)
    ).fetchone()
    return row[0] if row else None


def extract_block_text(
    conn: sqlite3.Connection,
    block_id: int,
) -> dict:
    """提取单个 block 的正文。

    返回:
        {
            block_id, block_index, block_type, x0, y0, x1, y1,
            block_text, block_text_status,
            page_id, document_id
        }

    block_text_status:
        OK                — 成功提取到非空正文
        EMPTY_BLOCK       — 提取到空字符串（真空单元格，非缺失）
        MISSING_BLOCK_TEXT — PDF 打不开 / block 不在表里 / 提取异常
    """
    result = {
        "block_id": block_id,
        "block_index": None,
        "block_type": None,
        "x0": None, "y0": None, "x1": None, "y1": None,
        "block_text": "",
        "block_text_status": "MISSING_BLOCK_TEXT",
        "page_id": None,
        "document_id": None,
    }

    coord = _coord_cache.get(block_id)
    if coord is None:
        # block 不在 document_blocks 表里
        logger.error("block_id=%d NOT FOUND in document_blocks", block_id)
        return result

    page_id, block_index, x0, y0, x1, y1, document_id = coord
    # 查 block_type
    bt_row = conn.execute(
        "SELECT block_type FROM document_blocks WHERE id=?", (block_id,)
    ).fetchone()
    block_type = bt_row[0] if bt_row else None

    result.update({
        "block_index": block_index,
        "block_type": block_type,
        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "page_id": page_id,
        "document_id": document_id,
    })

    # 打开 PDF
    original_filename = _get_document_filename(conn, document_id)
    if original_filename is None:
        logger.error("block_id=%d doc_id=%d filename lookup failed", block_id, document_id)
        return result

    doc = _open_pdf(document_id, original_filename)
    if doc is None:
        return result

    # page_id == page_number（PDF 物理页码，1-based），转 0-based 索引
    # 但 fitz 页索引是 0-based，所以 page_index = page_number - 1
    # 数据库里 page_id 字段实际就是 document_pages.id，而 document_pages.page_number 是物理页
    # 之前诊断发现 page_id == page_number（doc 1 的 page 135 -> page_id=135 == page_number=135）
    # 这里保险起见，用 page_id 直接当 page_number
    page_index = page_id - 1
    if page_index < 0 or page_index >= doc.page_count:
        logger.error(
            "block_id=%d page_id=%d out of range (page_count=%d)",
            block_id, page_id, doc.page_count,
        )
        return result

    page = doc[page_index]
    try:
        rect = fitz.Rect(x0, y0, x1, y1)
        text = page.get_textbox(rect)
    except Exception as exc:  # noqa: BLE001
        logger.error("block_id=%d textbox extraction failed: %s", block_id, exc)
        return result

    # 清理：去除尾部换行
    text_clean = text.rstrip()
    result["block_text"] = text_clean
    if text_clean:
        result["block_text_status"] = "OK"
    else:
        result["block_text_status"] = "EMPTY_BLOCK"
    return result


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def inject_block_text() -> dict:
    """主流程：读取 review_items，注入 block 正文，输出中间文件。

    返回统计信息。
    """
    setup_logging()
    logger.info("=" * 60)
    logger.info("Block 正文注入脚本启动")
    logger.info("input:  %s", REVIEW_ITEMS_PATH)
    logger.info("output: %s", OUTPUT_PATH)
    logger.info("log:    %s", LOG_PATH)

    # 读取原始 review_items
    with open(REVIEW_ITEMS_PATH, "r", encoding="utf-8") as f:
        review_data = json.load(f)

    items = review_data["items"]
    logger.info("loaded %d review items", len(items))

    # 收集所有 block_ids，预加载坐标
    conn = sqlite3.connect(DB_PATH)
    all_block_ids = []
    for it in items:
        for cg in it["candidate_groups"]:
            all_block_ids.extend(cg["block_ids"])
    _load_block_coords(conn, all_block_ids)
    logger.info("preloaded coords for %d block_ids", len(all_block_ids))

    # 统计
    stats = {
        "total_items": len(items),
        "items_with_full_text": 0,
        "items_with_partial_text": 0,
        "items_missing_text": 0,
        "total_candidate_groups": 0,
        "total_blocks_processed": 0,
        "blocks_ok": 0,
        "blocks_empty": 0,
        "blocks_missing": 0,
        "missing_item_ids": [],
        "partial_item_ids": [],
        "block_status_counts": {"OK": 0, "EMPTY_BLOCK": 0, "MISSING_BLOCK_TEXT": 0},
    }

    # 注入
    for item in items:
        item_id = item["item_id"]
        item_has_missing = False
        item_has_partial = False
        item_total_blocks = 0
        item_ok_blocks = 0

        for cg in item["candidate_groups"]:
            stats["total_candidate_groups"] += 1
            blocks_info = []
            # 严格按 block_ids 原始顺序提取
            for bid in cg["block_ids"]:
                stats["total_blocks_processed"] += 1
                item_total_blocks += 1
                binfo = extract_block_text(conn, bid)
                blocks_info.append(binfo)
                status = binfo["block_text_status"]
                stats["block_status_counts"][status] = stats["block_status_counts"].get(status, 0) + 1
                if status == "OK":
                    stats["blocks_ok"] += 1
                    item_ok_blocks += 1
                elif status == "EMPTY_BLOCK":
                    stats["blocks_empty"] += 1
                else:
                    stats["blocks_missing"] += 1
                    item_has_missing = True

            # 把 blocks_info 注入 candidate_group（不破坏原字段）
            cg["blocks"] = blocks_info

        # item 级别分类
        # MISSING_BLOCK_TEXT 出现 → item_missing
        # 否则若 EMPTY_BLOCK 出现但所有 block 都至少 OK/EMPTY → partial
        # 实际策略：
        #   - 任一 block MISSING → item_missing_text
        #   - 否则若有 EMPTY_BLOCK → item_partial_text（部分block无正文）
        #   - 否则全部 OK → item_full_text
        any_missing = any(
            b["block_text_status"] == "MISSING_BLOCK_TEXT"
            for cg in item["candidate_groups"]
            for b in cg["blocks"]
        )
        any_empty = any(
            b["block_text_status"] == "EMPTY_BLOCK"
            for cg in item["candidate_groups"]
            for b in cg["blocks"]
        )

        if any_missing:
            stats["items_missing_text"] += 1
            stats["missing_item_ids"].append(item_id)
        elif any_empty:
            stats["items_with_partial_text"] += 1
            stats["partial_item_ids"].append(item_id)
        else:
            stats["items_with_full_text"] += 1

    conn.close()

    # 输出
    output_data = {
        "phase": review_data.get("phase", "23.11.6"),
        "total": review_data.get("total", len(items)),
        "injection_meta": {
            "script": "scripts/phase23_11_6_inject_block_text.py",
            "block_text_source": "PyMuPDF get_textbox(rect) on original PDF",
            "pdf_source_dir": str(PDF_SOURCE_DIR),
            "fields_stripped_from_blind_review": [
                "reconstruction_coverage",
                "number_match",
                "metric_match",
                "period_match",
                "unit_match",
                "company_match",
            ],
        },
        "stats": stats,
        "items": items,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    logger.info("wrote output: %s", OUTPUT_PATH)

    # 打印统计
    logger.info("=" * 60)
    logger.info("Block 正文注入完成统计:")
    logger.info("  total items: %d", stats["total_items"])
    logger.info("  items full text:    %d", stats["items_with_full_text"])
    logger.info("  items partial text: %d", stats["items_with_partial_text"])
    logger.info("  items missing text: %d", stats["items_missing_text"])
    logger.info("  total blocks processed: %d", stats["total_blocks_processed"])
    logger.info("  blocks OK:    %d", stats["blocks_ok"])
    logger.info("  blocks EMPTY: %d", stats["blocks_empty"])
    logger.info("  blocks MISSING: %d", stats["blocks_missing"])
    if stats["missing_item_ids"]:
        logger.info("  MISSING item ids: %s", stats["missing_item_ids"])
    if stats["partial_item_ids"]:
        logger.info("  PARTIAL item ids: %s", stats["partial_item_ids"])

    return stats


if __name__ == "__main__":
    inject_block_text()
