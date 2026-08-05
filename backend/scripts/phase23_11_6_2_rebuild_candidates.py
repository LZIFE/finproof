"""Phase 23.11.6.2 — 候选 Evidence 重建脚本

从 Gold 标注的 source document / page / original Gold Evidence text 出发，
重新构建 Candidate Bundle，修复 review_items.json 的候选 block 选取缺陷。

修复要点：
1. 不再信任上游 grounding audit 给的 candidate_block_ids（它选了真空单元格）
2. 从 existing_page 出发，加载该页 + 前后页所有 DocumentBlock
3. 用 PyMuPDF 重新提取每个 block 的正文
4. 结构化分类每个 block：
   is_blank, is_micro_cell, is_header, is_unit_label,
   is_period_header, is_metric_row, is_numeric_row
5. 构建 Candidate Bundle（不再是孤立 Block）：
   - 大正文 Block（如 4443）直接作为完整 Bundle
   - 短文本 Block（单位"千元"、期间"2024年度"、行标题"营业收入"）保留并组合
   - 空白 Block / 微单元格不单独作为候选
6. 最多 5 组可信 Candidate Bundle
7. 排序使用：Gold Evidence 文本相似度、关键数字匹配、指标匹配
   —— 但不自动确认 Gold
8. 不调用任何模型

输出：
- data/gold_review/phase23_11_6_2/review_items_rebuilt.json
- backend/artifacts/gold_contract/phase23_11_6_2_candidate_recall.json

Run: cd backend && PYTHONPATH=. python scripts/phase23_11_6_2_rebuild_candidates.py
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
if str(BACKEND) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(BACKEND))

# 路径
DB_PATH = REPO_ROOT / "data" / "finproof.db"
PDF_SOURCE_DIR = REPO_ROOT / "data" / "demo" / "source"
GROUNDING_AUDIT_PATH = (
    BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_1_grounding_audit.json"
)
OLD_REVIEW_ITEMS = REPO_ROOT / "data" / "gold_review" / "phase23_11_6" / "review_items.json"

OUTPUT_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2"
REBUILT_PATH = OUTPUT_DIR / "review_items_rebuilt.json"
RECALL_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_candidate_recall.json"
LOG_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_rebuild_candidates.log"

# 候选 Bundle 上限
MAX_BUNDLES = 5
# 空白 / 微单元格阈值（pt）
MICRO_CELL_MAX_WIDTH = 15.0
MICRO_CELL_MAX_HEIGHT = 20.0
# 短文本 Block 保留阈值：正文长度 >= 1 即保留（单位"千元"=3字符）
MIN_TEXT_LEN_TO_KEEP = 1

logger = logging.getLogger("rebuild_candidates")


def setup_logging() -> None:
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    import sys
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Block 正文提取（复用 inject_block_text 的逻辑，但内联以避免 import 副作用）
# ---------------------------------------------------------------------------

_pdf_cache: dict[int, fitz.Document] = {}
_block_coord_cache: dict[int, tuple] = {}
_block_text_cache: dict[int, dict] = {}


def _open_pdf(document_id: int, original_filename: str) -> fitz.Document | None:
    if document_id in _pdf_cache:
        return _pdf_cache[document_id]
    pdf_path = PDF_SOURCE_DIR / original_filename
    if not pdf_path.exists():
        logger.error("doc_id=%d PDF not found: %s", document_id, pdf_path)
        return None
    try:
        doc = fitz.open(pdf_path)
        _pdf_cache[document_id] = doc
        return doc
    except Exception as exc:  # noqa: BLE001
        logger.error("doc_id=%d PDF open failed: %s", document_id, exc)
        return None


def _get_document_filename(conn: sqlite3.Connection, document_id: int) -> str | None:
    row = conn.execute(
        "SELECT original_filename FROM documents WHERE id=?", (document_id,)
    ).fetchone()
    return row[0] if row else None


def extract_block_text(conn: sqlite3.Connection, block_id: int) -> dict:
    """提取单个 block 的正文（带坐标）。"""
    if block_id in _block_text_cache:
        return _block_text_cache[block_id]

    result = {
        "block_id": block_id,
        "block_index": None,
        "block_type": None,
        "x0": None, "y0": None, "x1": None, "y1": None,
        "width": None, "height": None,
        "block_text": "",
        "block_text_status": "MISSING_BLOCK_TEXT",
        "page_id": None,
        "document_id": None,
    }

    # 加载坐标
    if block_id not in _block_coord_cache:
        row = conn.execute(
            "SELECT id, page_id, block_index, x0, y0, x1, y1, document_id "
            "FROM document_blocks WHERE id=?",
            (block_id,),
        ).fetchone()
        if row is None:
            _block_text_cache[block_id] = result
            return result
        _block_coord_cache[block_id] = row[1:]

    page_id, block_index, x0, y0, x1, y1, document_id = _block_coord_cache[block_id]
    bt_row = conn.execute(
        "SELECT block_type FROM document_blocks WHERE id=?", (block_id,)
    ).fetchone()
    block_type = bt_row[0] if bt_row else None

    result.update({
        "block_index": block_index,
        "block_type": block_type,
        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "width": (x1 - x0) if (x0 is not None and x1 is not None) else None,
        "height": (y1 - y0) if (y0 is not None and y1 is not None) else None,
        "page_id": page_id,
        "document_id": document_id,
    })

    original_filename = _get_document_filename(conn, document_id)
    if original_filename is None:
        _block_text_cache[block_id] = result
        return result

    doc = _open_pdf(document_id, original_filename)
    if doc is None:
        _block_text_cache[block_id] = result
        return result

    page_index = page_id - 1
    if page_index < 0 or page_index >= doc.page_count:
        _block_text_cache[block_id] = result
        return result

    try:
        page = doc[page_index]
        rect = fitz.Rect(x0, y0, x1, y1)
        text = page.get_textbox(rect)
    except Exception as exc:  # noqa: BLE001
        logger.error("block_id=%d textbox extraction failed: %s", block_id, exc)
        _block_text_cache[block_id] = result
        return result

    text_clean = text.rstrip()
    result["block_text"] = text_clean
    if text_clean:
        result["block_text_status"] = "OK"
    else:
        result["block_text_status"] = "EMPTY_BLOCK"

    _block_text_cache[block_id] = result
    return result


# ---------------------------------------------------------------------------
# Block 结构化分类
# ---------------------------------------------------------------------------

# 单位标签关键词
UNIT_LABELS = ["千元", "百元", "万元", "亿元", "人民币", "USD", "EUR", "港币"]
# 期间表头关键词
PERIOD_HEADERS = ["年度", "本期", "上期", "本期金额", "上期金额", "本期发生额",
                  "2025", "2024", "2023", "本年", "上年", "当期", "同期"]
# 指标行表头
METRIC_ROWS = ["营业收入", "营业总收入", "营业成本", "净利润", "归属于",
               "一、", "二、", "三、", "其中：", "减："]
# 数值行（含数字 + 千分位逗号）
NUMBER_PATTERN = re.compile(r"\d[\d,]*\.?\d*")


def classify_block(binfo: dict) -> dict:
    """对单个 block 做结构化分类。"""
    text = binfo.get("block_text") or ""
    width = binfo.get("width") or 0
    height = binfo.get("height") or 0

    is_blank = (binfo["block_text_status"] == "EMPTY_BLOCK") or (not text.strip())
    is_micro_cell = (
        width < MICRO_CELL_MAX_WIDTH and height < MICRO_CELL_MAX_HEIGHT
    )
    is_unit_label = any(u in text for u in UNIT_LABELS) and len(text) < 30
    is_period_header = any(p in text for p in PERIOD_HEADERS) and len(text) < 30
    is_header = binfo.get("block_type") == "heading"
    is_metric_row = any(m in text for m in METRIC_ROWS)
    is_numeric_row = bool(NUMBER_PATTERN.search(text)) and not is_metric_row

    return {
        "is_blank": is_blank,
        "is_micro_cell": is_micro_cell,
        "is_header": is_header,
        "is_unit_label": is_unit_label,
        "is_period_header": is_period_header,
        "is_metric_row": is_metric_row,
        "is_numeric_row": is_numeric_row,
    }


# ---------------------------------------------------------------------------
# 关键数字提取与匹配
# ---------------------------------------------------------------------------

def extract_key_numbers(text: str) -> list[str]:
    """提取关键数字（带千分位逗号），用于 Gold Evidence 与候选的数字匹配。"""
    if not text:
        return []
    # 匹配 456,451,731 / 12.11% / 458,502,407 等格式
    matches = re.findall(r"\d[\d,]*\.?\d*%?", text)
    # 过滤掉过短的纯页码数字（如单独的 "7"、"8"）
    filtered = []
    for m in matches:
        # 保留带逗号的、带百分号的、或长度 >= 4 的
        if "," in m or "%" in m or len(m.replace(".", "")) >= 4:
            filtered.append(m)
    return filtered


def number_match_score(gold_numbers: list[str], cand_numbers: list[str]) -> float:
    """计算 Gold 关键数字在候选中的覆盖率（0-1）。"""
    if not gold_numbers:
        return 0.0
    gold_set = set(gold_numbers)
    cand_set = set(cand_numbers)
    overlap = gold_set & cand_set
    return len(overlap) / len(gold_set)


def text_similarity(gold_text: str, cand_text: str) -> float:
    """简单的 Jaccard 字符相似度（0-1）。"""
    if not gold_text or not cand_text:
        return 0.0
    gold_chars = set(gold_text)
    cand_chars = set(cand_text)
    if not gold_chars or not cand_chars:
        return 0.0
    overlap = gold_chars & cand_chars
    union = gold_chars | cand_chars
    return len(overlap) / len(union)


# ---------------------------------------------------------------------------
# Candidate Bundle 构建
# ---------------------------------------------------------------------------

def build_bundles_for_page(
    conn: sqlite3.Connection,
    document_id: int,
    page_id: int,
    gold_evidence_text: str,
) -> list[dict]:
    """为指定页构建 Candidate Bundle 列表。

    策略：
    1. 加载该页所有 block，提取正文 + 分类
    2. 排除 is_blank 且 is_micro_cell 的 block（真空微单元格）
    3. 保留含正文的 block（包括短文本如"千元"、"营业收入"行标题）
    4. 构建 Bundle：
       - 大正文 block（len > 50）单独成 Bundle
       - 短文本 block（单位/期间/行标题）按空间相邻组合成 Bundle
    5. 用 Gold Evidence 文本相似度 + 关键数字匹配排序
    6. 最多返回 MAX_BUNDLES 个
    """
    # 加载该页所有 block
    rows = conn.execute(
        "SELECT id, block_index, block_type, x0, y0, x1, y1, reading_order "
        "FROM document_blocks WHERE document_id=? AND page_id=? "
        "ORDER BY block_index",
        (document_id, page_id),
    ).fetchall()

    if not rows:
        return []

    # 提取每个 block 的正文 + 分类
    block_infos = []
    for r in rows:
        bid = r[0]
        binfo = extract_block_text(conn, bid)
        binfo["reading_order"] = r[7]
        classification = classify_block(binfo)
        binfo.update(classification)
        block_infos.append(binfo)

    # 过滤：排除真空微单元格
    candidate_blocks = [
        b for b in block_infos
        if not (b["is_blank"] and b["is_micro_cell"])
    ]

    # 提取 Gold 关键数字
    gold_numbers = extract_key_numbers(gold_evidence_text)

    # 构建 Bundle
    bundles = []

    # 策略 A：大正文 block 单独成 Bundle
    big_blocks = [b for b in candidate_blocks if len(b["block_text"] or "") > 50]
    for b in big_blocks:
        bundle = _make_bundle(
            conn, document_id, page_id, [b], block_infos, gold_numbers, gold_evidence_text
        )
        if bundle:
            bundles.append(bundle)

    # 策略 B：短文本 block 按空间相邻组合
    short_blocks = [
        b for b in candidate_blocks
        if len(b["block_text"] or "") <= 50 and not b["is_blank"]
    ]
    if short_blocks:
        # 按 y0 分组（同一行）
        short_blocks.sort(key=lambda b: (b["y0"] or 0, b["x0"] or 0))
        # 简单分组：相邻 y0 在 5pt 内的 block 组合
        groups = []
        current_group = [short_blocks[0]]
        for b in short_blocks[1:]:
            if abs((b["y0"] or 0) - (current_group[-1]["y0"] or 0)) < 5:
                current_group.append(b)
            else:
                groups.append(current_group)
                current_group = [b]
        groups.append(current_group)

        for grp in groups:
            bundle = _make_bundle(
                conn, document_id, page_id, grp, block_infos, gold_numbers, gold_evidence_text
            )
            if bundle:
                bundles.append(bundle)

    # 策略 C：如果以上都没产出，把所有非空 block 组合成一个大 Bundle
    if not bundles:
        non_empty = [b for b in candidate_blocks if not b["is_blank"]]
        if non_empty:
            bundle = _make_bundle(
                conn, document_id, page_id, non_empty, block_infos, gold_numbers, gold_evidence_text
            )
            if bundle:
                bundles.append(bundle)

    # 去重：相同 source_block_ids 的 Bundle 只保留第一个
    seen_keys = set()
    unique_bundles = []
    for bd in bundles:
        key = tuple(sorted(bd["source_block_ids"]))
        if key not in seen_keys:
            seen_keys.add(key)
            unique_bundles.append(bd)

    # 排序：reconstruction_coverage 降序（数字匹配 + 文本相似度）
    unique_bundles.sort(
        key=lambda b: (b["reconstruction_coverage"], b["text_similarity"]),
        reverse=True,
    )

    # 截断到 MAX_BUNDLES
    return unique_bundles[:MAX_BUNDLES]


def _make_bundle(
    conn: sqlite3.Connection,
    document_id: int,
    page_id: int,
    blocks: list[dict],
    all_page_blocks: list[dict],
    gold_numbers: list[str],
    gold_evidence_text: str,
) -> dict | None:
    """构建单个 Candidate Bundle。"""
    if not blocks:
        return None

    # source_block_ids（按 block_index 排序）
    sorted_blocks = sorted(blocks, key=lambda b: b["block_index"] or 0)
    source_block_ids = [str(b["block_id"]) for b in sorted_blocks]

    # block_texts（按 block_index 顺序拼接）
    block_texts = [
        {"block_id": str(b["block_id"]),
         "block_index": b["block_index"],
         "text": b["block_text"] or ""}
        for b in sorted_blocks
    ]

    # reconstructed_text（拼接所有 block 正文）
    reconstructed_text = "\n".join(
        (b["block_text"] or "") for b in sorted_blocks
    ).strip()

    if not reconstructed_text:
        return None  # 空 Bundle 不返回

    # 表格标题 / section_title / unit_header / period_headers / row_headers
    # 从该页所有 block 里推断
    table_title = ""
    section_title = ""
    unit_header = ""
    period_headers = []
    row_headers = []

    for b in all_page_blocks:
        text = (b["block_text"] or "").strip()
        if not text:
            continue
        if b["is_unit_label"] and not unit_header:
            unit_header = text
        if b["is_period_header"]:
            period_headers.append(text)
        if b["is_metric_row"]:
            row_headers.append(text)

    # context_before / context_after
    # 取该页 block_index 最小 / 最大的非空 block 的前后文
    sorted_page = sorted(all_page_blocks, key=lambda b: b["block_index"] or 0)
    context_before = ""
    context_after = ""
    if sorted_blocks and sorted_page:
        first_idx = sorted_page.index(sorted_blocks[0]) if sorted_blocks[0] in sorted_page else 0
        last_idx = sorted_page.index(sorted_blocks[-1]) if sorted_blocks[-1] in sorted_page else 0
        if first_idx > 0:
            context_before = (sorted_page[first_idx - 1]["block_text"] or "")[:200]
        if last_idx < len(sorted_page) - 1:
            context_after = (sorted_page[last_idx + 1]["block_text"] or "")[:200]

    # spatial_relationship
    spatial_relationship = {
        "page": page_id,
        "block_count": len(sorted_blocks),
        "y_range": [
            min((b["y0"] or 0) for b in sorted_blocks),
            max((b["y1"] or 0) for b in sorted_blocks),
        ],
        "x_range": [
            min((b["x0"] or 0) for b in sorted_blocks),
            max((b["x1"] or 0) for b in sorted_blocks),
        ],
    }

    # 匹配评分
    cand_numbers = extract_key_numbers(reconstructed_text)
    nm_score = number_match_score(gold_numbers, cand_numbers)
    ts_score = text_similarity(gold_evidence_text, reconstructed_text)

    # reconstruction_coverage（0-1，用于内部排序，不展示给模型）
    reconstruction_coverage = round(0.5 * nm_score + 0.3 * ts_score + 0.2 * (1.0 if cand_numbers else 0.0), 4)

    return {
        "candidate_group_id": "",  # 后填
        "document_id": document_id,
        "page": page_id,
        "source_block_ids": source_block_ids,
        "block_texts": block_texts,
        "reconstructed_text": reconstructed_text,
        "table_title": table_title,
        "section_title": section_title,
        "unit_header": unit_header,
        "period_headers": period_headers[:5],  # 最多保留5个
        "row_headers": row_headers[:10],  # 最多保留10个
        "context_before": context_before,
        "context_after": context_after,
        "spatial_relationship": spatial_relationship,
        "reconstruction_coverage": reconstruction_coverage,
        "text_similarity": round(ts_score, 4),
        "number_match": round(nm_score, 4),
        "metric_match": "UNKNOWN",
        "period_match": "UNKNOWN",
        "unit_match": "UNKNOWN",
        "scope_match": "UNKNOWN",
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def rebuild_candidates() -> dict:
    """主流程：重建候选 Evidence，生成 review_items_rebuilt.json。"""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Phase 23.11.6.2 候选 Evidence 重建脚本启动")
    logger.info("grounding audit: %s", GROUNDING_AUDIT_PATH)
    logger.info("output: %s", REBUILT_PATH)

    # 读取上游 grounding audit
    audit = json.loads(GROUNDING_AUDIT_PATH.read_text(encoding="utf-8"))
    per_evidence = audit["per_evidence"]
    logger.info("grounding audit per_evidence: %d", len(per_evidence))

    # 读取旧 review_items.json（用于保留 claim_text / company / report_name 等字段）
    old_items = json.loads(OLD_REVIEW_ITEMS.read_text(encoding="utf-8"))["items"]
    old_by_id = {it["item_id"]: it for it in old_items}

    # 数据库连接
    conn = sqlite3.connect(DB_PATH)

    # 只处理 HUMAN_REVIEW_REQUIRED（32 条）
    rebuilt_items = []
    recall_items = []
    stats = {
        "total_evidence": 0,
        "rebuilt_with_bundles": 0,
        "no_bundles_found": 0,
        "total_bundles": 0,
        "bundles_with_text": 0,
        "empty_bundles_excluded": 0,
    }

    for pe in per_evidence:
        if pe.get("new_status") != "HUMAN_REVIEW_REQUIRED":
            continue
        stats["total_evidence"] += 1
        iid = pe["gold_evidence_id"]
        cid = pe["claim_id"]
        gold_evidence_text = pe.get("evidence_text") or ""
        existing_page = pe.get("existing_page")
        # 上游 grounding audit 里没有 document_id 字段，从 old_items 取
        old_it = old_by_id.get(iid, {})
        # old_items 的 candidate_groups 里有 document_id
        old_doc_id = None
        if old_it.get("candidate_groups"):
            old_doc_id = old_it["candidate_groups"][0].get("document_id")
        # 如果没有，从 company 推断（demo 美的集团 -> doc 1）
        if old_doc_id is None:
            old_doc_id = 1  # 默认 demo 美的集团

        logger.info("-" * 40)
        logger.info("[%d] %s page=%s doc=%s",
                    stats["total_evidence"], iid, existing_page, old_doc_id)

        # 构建 Bundle：在 existing_page、existing_page-1、existing_page+1 三页搜索
        bundles = []
        pages_to_search = []
        if existing_page:
            pages_to_search = [existing_page]
            # 前后页（如果 existing_page > 1）
            if existing_page > 1:
                pages_to_search.append(existing_page - 1)
            pages_to_search.append(existing_page + 1)

        for pid in pages_to_search:
            if pid is None or pid < 1:
                continue
            page_bundles = build_bundles_for_page(
                conn, old_doc_id, pid, gold_evidence_text
            )
            for bd in page_bundles:
                bd["candidate_group_id"] = f"{iid}-g{len(bundles) + 1}"
                bundles.append(bd)
                if len(bundles) >= MAX_BUNDLES:
                    break
            if len(bundles) >= MAX_BUNDLES:
                break

        # 统计
        stats["total_bundles"] += len(bundles)
        non_empty_bundles = [b for b in bundles if b["reconstructed_text"]]
        stats["bundles_with_text"] += len(non_empty_bundles)

        if not bundles:
            stats["no_bundles_found"] += 1
            logger.warning("%s: NO bundles found", iid)
        else:
            stats["rebuilt_with_bundles"] += 1

        # 关键数字检查
        gold_numbers = extract_key_numbers(gold_evidence_text)
        best_coverage = max((b["reconstruction_coverage"] for b in bundles), default=0.0)
        best_numbers = []
        best_metric = "UNKNOWN"
        best_period = "UNKNOWN"
        best_unit = "UNKNOWN"
        if bundles:
            best = max(bundles, key=lambda b: b["reconstruction_coverage"])
            best_numbers = extract_key_numbers(best["reconstructed_text"])
            best_metric = best.get("metric_match", "UNKNOWN")
            best_period = best.get("period_match", "UNKNOWN")
            best_unit = best.get("unit_match", "UNKNOWN")

        # 构建 rebuilt item
        # 保留旧 item 的 claim_text / company / report_name / dataset
        # 不保留旧 candidate_groups（用新 bundles 替代）
        rebuilt_item = {
            "item_id": iid,
            "claim_id": cid,
            "claim_text": old_it.get("claim_text", ""),
            "company": old_it.get("company", ""),
            "report_name": old_it.get("report_name", "annual_report"),
            "dataset": old_it.get("dataset", ""),
            "gold_evidence_text": gold_evidence_text,
            "existing_page": existing_page,
            "candidate_bundles": bundles,  # 新字段：Candidate Bundle 列表
            "reviewer_choice": "",
            "selected_block_ids": [],
            "evidence_complete": "",
            "reviewer_note": "",
            "review_status": "PENDING",
        }
        rebuilt_items.append(rebuilt_item)

        # Candidate Recall 记录
        recall_items.append({
            "gold_evidence_id": iid,
            "claim_id": cid,
            "original_gold_evidence": gold_evidence_text,
            "candidate_bundle_count": len(bundles),
            "non_empty_bundle_count": len(non_empty_bundles),
            "best_reconstruction_coverage": round(best_coverage, 4),
            "key_numbers_found": [n for n in gold_numbers if any(n in (b["reconstructed_text"] or "") for b in bundles)],
            "key_numbers_total": gold_numbers,
            "metric_found": best_metric,
            "period_found": best_period,
            "unit_found": best_unit,
            "likely_source_recovered": best_coverage >= 0.3,
            "review_ready": len(non_empty_bundles) > 0,
            "failure_reason": "" if bundles else "no candidate blocks found on existing_page or adjacent pages",
        })

    conn.close()

    # 写 review_items_rebuilt.json
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rebuilt_data = {
        "phase": "23.11.6.2",
        "total": len(rebuilt_items),
        "description": "Candidate Evidence rebuilt with Candidate Bundle (no model call)",
        "rebuilt_at": datetime.now(timezone.utc).isoformat(),
        "items": rebuilt_items,
    }
    REBUILT_PATH.write_text(
        json.dumps(rebuilt_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("wrote rebuilt items: %s", REBUILT_PATH)

    # 写 candidate_recall.json
    recall_data = {
        "phase": "23.11.6.2",
        "total_evidence": stats["total_evidence"],
        "rebuilt_with_bundles": stats["rebuilt_with_bundles"],
        "no_bundles_found": stats["no_bundles_found"],
        "total_bundles": stats["total_bundles"],
        "recall_items": recall_items,
    }
    RECALL_PATH.write_text(
        json.dumps(recall_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("wrote candidate recall: %s", RECALL_PATH)

    # 打印统计
    logger.info("=" * 60)
    logger.info("候选 Evidence 重建统计:")
    logger.info("  total evidence: %d", stats["total_evidence"])
    logger.info("  rebuilt with bundles: %d", stats["rebuilt_with_bundles"])
    logger.info("  no bundles found: %d", stats["no_bundles_found"])
    logger.info("  total bundles: %d", stats["total_bundles"])
    logger.info("  bundles with text: %d", stats["bundles_with_text"])

    return stats


if __name__ == "__main__":
    rebuild_candidates()
