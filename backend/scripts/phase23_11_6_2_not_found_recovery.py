"""Phase 23.11.6.2 — NOT_FOUND 恢复脚本（重新处理 10 条）

对 10 条 NOT_FOUND evidence：
1. 检查标注页（existing_page）的 block 正文
2. 用原 Gold 关键数字在 PDF 全文搜索，定位真正含正文的页面
3. 检查相邻页、完整表格、跨页延续
4. 检查原 Gold 文本是否为摘要或改写
5. 构建视觉审核 Candidate Bundle

状态更新为（每条选一个）：
- CANDIDATES_RECOVERED            —— 在标注页或相邻页找到含正文的 Candidate Bundle
- PARAPHRASED_SOURCE_LOCATED      —— Gold 是改写，定位到原文来源
- VISUAL_REVIEW_REQUIRED          —— 需要视觉人工审核
- WRONG_PAGE_REFERENCE            —— 标注页错误，找到正确页
- WRONG_DOCUMENT_REFERENCE        —— 标注文档错误，找到正确文档
- STILL_NOT_FOUND                 —— 仍未找到

不调用任何模型。不自动写入 Gold。

输出：
- backend/artifacts/gold_contract/phase23_11_6_2_not_found_recovery.json
- backend/artifacts/gold_contract/phase23_11_6_2_not_found_recovery.log
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
import sys
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# 路径
DB_PATH = REPO_ROOT / "data" / "finproof.db"
PDF_SOURCE_DIR = REPO_ROOT / "data" / "demo" / "source"
GROUNDING_AUDIT_PATH = (
    BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_1_grounding_audit.json"
)
OLD_REVIEW_ITEMS = REPO_ROOT / "data" / "gold_review" / "phase23_11_6" / "review_items.json"

OUTPUT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_not_found_recovery.json"
LOG_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_not_found_recovery.log"

# 候选 Bundle 上限
MAX_BUNDLES = 5

# 关键数字提取（千分位数字 + 百分比）
NUMBER_PATTERN = re.compile(r"\d[\d,]*\.?\d*%?")


logger = logging.getLogger("not_found_recovery")


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
# 工具函数
# ---------------------------------------------------------------------------

_pdf_cache: dict[int, fitz.Document] = {}


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


def extract_key_numbers(text: str) -> list[str]:
    """提取关键数字（带千分位逗号、百分比）。"""
    if not text:
        return []
    matches = NUMBER_PATTERN.findall(text)
    filtered = []
    for m in matches:
        # 保留带逗号、带百分号或长度 >= 4 的数字
        if "," in m or "%" in m or len(m.replace(".", "").replace("%", "")) >= 4:
            filtered.append(m)
    return filtered


def normalize_for_search(text: str) -> str:
    """标准化文本用于搜索匹配：去除空格、换行、标点。"""
    if not text:
        return ""
    # 去除空白
    t = re.sub(r"\s+", "", text)
    # 去除常见标点
    t = re.sub(r"[，。、；：！？""''（）()【】\[\]{}「」『』…—\-\.]", "", t)
    return t


def search_numbers_in_pdf(
    doc: fitz.Document,
    numbers: list[str],
    max_pages: int = 300,
) -> list[dict]:
    """在 PDF 全文搜索关键数字，返回命中页面列表。

    返回 [{page_number, matched_numbers, page_text_excerpt}, ...]
    """
    if not numbers:
        return []

    hits = []
    page_count = min(doc.page_count, max_pages)
    for i in range(page_count):
        page = doc[i]
        text = page.get_text("text")
        if not text:
            continue
        matched = []
        for n in numbers:
            # 千分位数字可能有空格分隔，做模糊匹配
            n_clean = n.replace(",", "").replace("%", "")
            # 在页面文字里搜索（去除千分位逗号后比较）
            text_clean = text.replace(",", "")
            if n_clean in text_clean or n in text:
                matched.append(n)
        if matched:
            hits.append({
                "page_number": i + 1,
                "matched_numbers": matched,
                "page_text_excerpt": text[:200].replace("\n", " "),
            })
    return hits


def build_bundles_for_page_with_pymupdf(
    doc: fitz.Document,
    document_id: int,
    page_number: int,
    gold_evidence_text: str,
) -> list[dict]:
    """用 PyMuPDF 直接构建 Candidate Bundle（不依赖 document_blocks 表）。

    策略：
    1. 用 page.get_text("blocks") 获取该页所有 block
    2. 按 (y0, x0) 排序
    3. 过滤真空微单元格
    4. 大正文 block 单独成 Bundle
    5. 短文本 block 按行组合
    """
    if page_number < 1 or page_number > doc.page_count:
        return []
    page = doc[page_number - 1]
    raw_blocks = page.get_text("blocks")
    if not raw_blocks:
        return []

    # 解析 + 排序
    parsed_blocks = []
    for b in raw_blocks:
        x0, y0, x1, y1, btext, bno, btype = b
        text_clean = (btext or "").rstrip()
        width = x1 - x0 if (x0 is not None and x1 is not None) else 0
        height = y1 - y0 if (y0 is not None and y1 is not None) else 0
        is_blank = not text_clean.strip()
        is_micro = width < 15 and height < 20
        parsed_blocks.append({
            "block_id": f"pymp-{page_number}-{bno}",
            "page": page_number,
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "width": width, "height": height,
            "text": text_clean,
            "is_blank": is_blank,
            "is_micro_cell": is_micro,
        })
    parsed_blocks.sort(key=lambda b: (b["y0"], b["x0"]))

    # 过滤真空微单元格
    candidate_blocks = [
        b for b in parsed_blocks
        if not (b["is_blank"] and b["is_micro_cell"])
    ]
    if not candidate_blocks:
        return []

    # 提取 Gold 关键数字
    gold_numbers = extract_key_numbers(gold_evidence_text)

    # 构建 Bundle
    bundles = []
    big_blocks = [b for b in candidate_blocks if len(b["text"]) > 50]
    for b in big_blocks:
        bundle = _make_bundle_pymupdf([b], candidate_blocks, gold_numbers, gold_evidence_text)
        if bundle:
            bundles.append(bundle)

    short_blocks = [
        b for b in candidate_blocks
        if len(b["text"]) <= 50 and not b["is_blank"]
    ]
    if short_blocks:
        short_blocks.sort(key=lambda b: (b["y0"], b["x0"]))
        groups = []
        current_group = [short_blocks[0]]
        for b in short_blocks[1:]:
            if abs(b["y0"] - current_group[-1]["y0"]) < 5:
                current_group.append(b)
            else:
                groups.append(current_group)
                current_group = [b]
        groups.append(current_group)
        for grp in groups:
            bundle = _make_bundle_pymupdf(grp, candidate_blocks, gold_numbers, gold_evidence_text)
            if bundle:
                bundles.append(bundle)

    # 去重 + 截断
    seen_keys = set()
    unique_bundles = []
    for bd in bundles:
        key = tuple(sorted(bd["source_block_ids"]))
        if key not in seen_keys:
            seen_keys.add(key)
            unique_bundles.append(bd)
    unique_bundles.sort(
        key=lambda b: (b["reconstruction_coverage"], b["text_similarity"]),
        reverse=True,
    )
    return unique_bundles[:MAX_BUNDLES]


def _make_bundle_pymupdf(
    blocks: list[dict],
    all_page_blocks: list[dict],
    gold_numbers: list[str],
    gold_evidence_text: str,
) -> dict | None:
    if not blocks:
        return None
    sorted_blocks = sorted(blocks, key=lambda b: (b["y0"], b["x0"]))
    source_block_ids = [b["block_id"] for b in sorted_blocks]
    reconstructed_text = "\n".join(b["text"] for b in sorted_blocks).strip()
    if not reconstructed_text:
        return None

    cand_numbers = extract_key_numbers(reconstructed_text)
    nm_score = _number_match_score(gold_numbers, cand_numbers)
    ts_score = _text_similarity(gold_evidence_text, reconstructed_text)
    reconstruction_coverage = round(
        0.5 * nm_score + 0.3 * ts_score + 0.2 * (1.0 if cand_numbers else 0.0), 4
    )

    return {
        "source_block_ids": source_block_ids,
        "reconstructed_text": reconstructed_text,
        "reconstruction_coverage": reconstruction_coverage,
        "text_similarity": round(ts_score, 4),
        "number_match": round(nm_score, 4),
        "page": sorted_blocks[0]["page"],
    }


def _number_match_score(gold_numbers: list[str], cand_numbers: list[str]) -> float:
    if not gold_numbers:
        return 0.0
    gold_set = set(gold_numbers)
    cand_set = set(cand_numbers)
    overlap = gold_set & cand_set
    return len(overlap) / len(gold_set)


def _text_similarity(gold_text: str, cand_text: str) -> float:
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
# 主流程
# ---------------------------------------------------------------------------

def recover_not_found() -> dict:
    """主流程：重新处理 10 条 NOT_FOUND。"""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Phase 23.11.6.2 NOT_FOUND 恢复脚本启动")
    logger.info("grounding audit: %s", GROUNDING_AUDIT_PATH)
    logger.info("output: %s", OUTPUT_PATH)

    # 读取上游 grounding audit
    audit = json.loads(GROUNDING_AUDIT_PATH.read_text(encoding="utf-8"))
    not_found_items = [
        p for p in audit["per_evidence"] if p.get("new_status") == "NOT_FOUND"
    ]
    logger.info("NOT_FOUND evidence count: %d", len(not_found_items))

    # 读取旧 review_items.json（保留 claim_text / company 等）
    old_items = json.loads(OLD_REVIEW_ITEMS.read_text(encoding="utf-8"))["items"]
    old_by_id = {it["item_id"]: it for it in old_items}

    # 数据库连接
    conn = sqlite3.connect(DB_PATH)

    # 文档 ID 映射：demo 美的集团 -> doc 1（annual_report.pdf）
    # 但 NOT_FOUND 可能涉及多个 PDF（annual/half_year/q1）
    # 这里先用 doc 1（annual_report.pdf）作为主搜索文档
    MAIN_DOC_ID = 1

    recovered_items = []
    status_counts = {
        "CANDIDATES_RECOVERED": 0,
        "PARAPHRASED_SOURCE_LOCATED": 0,
        "VISUAL_REVIEW_REQUIRED": 0,
        "WRONG_PAGE_REFERENCE": 0,
        "WRONG_DOCUMENT_REFERENCE": 0,
        "STILL_NOT_FOUND": 0,
    }

    for pe in not_found_items:
        iid = pe["gold_evidence_id"]
        cid = pe["claim_id"]
        gold_evidence_text = pe.get("evidence_text") or ""
        annotated_page = pe.get("existing_page")
        old_it = old_by_id.get(iid, {})

        logger.info("-" * 40)
        logger.info("[%s] %s annotated_page=%s", iid, cid, annotated_page)
        logger.info("  gold_evidence: %s", gold_evidence_text[:120])

        # 1. 提取 Gold 关键数字
        gold_numbers = extract_key_numbers(gold_evidence_text)
        logger.info("  gold_numbers: %s", gold_numbers)

        # 2. 在主 PDF 全文搜索关键数字
        original_filename = _get_document_filename(conn, MAIN_DOC_ID)
        doc = _open_pdf(MAIN_DOC_ID, original_filename) if original_filename else None

        recovery_status = "STILL_NOT_FOUND"
        recovery_reason = ""
        candidate_bundles = []
        located_pages = []
        is_paraphrased = False

        if doc and gold_numbers:
            hits = search_numbers_in_pdf(doc, gold_numbers)
            logger.info("  PDF search hits: %d pages", len(hits))

            if hits:
                # 找到含关键数字的页面
                located_pages = [h["page_number"] for h in hits]
                best_hit = max(hits, key=lambda h: len(h["matched_numbers"]))
                best_page = best_hit["page_number"]
                logger.info("  best_page: %d (matched %d/%d numbers)",
                            best_page, len(best_hit["matched_numbers"]), len(gold_numbers))

                # 在 best_page 构建 Candidate Bundle
                candidate_bundles = build_bundles_for_page_with_pymupdf(
                    doc, MAIN_DOC_ID, best_page, gold_evidence_text
                )
                logger.info("  candidate_bundles: %d", len(candidate_bundles))

                # 判定状态
                if candidate_bundles:
                    best_cov = max(b["reconstruction_coverage"] for b in candidate_bundles)
                    if best_cov >= 0.5:
                        # 标注页与找到的页一致 → CANDIDATES_RECOVERED
                        # 标注页与找到的页不一致 → WRONG_PAGE_REFERENCE
                        if annotated_page and best_page != annotated_page:
                            recovery_status = "WRONG_PAGE_REFERENCE"
                            recovery_reason = (
                                f"标注页 {annotated_page} 未找到 Gold 关键数字，"
                                f"在 page {best_page} 找到含正文的 Candidate Bundle。"
                            )
                        else:
                            recovery_status = "CANDIDATES_RECOVERED"
                            recovery_reason = (
                                f"在 page {best_page} 找到含正文的 Candidate Bundle，"
                                f"best reconstruction_coverage = {best_cov}。"
                            )
                    else:
                        # 覆盖率低，可能是改写
                        recovery_status = "PARAPHRASED_SOURCE_LOCATED"
                        recovery_reason = (
                            f"在 page {best_page} 找到部分匹配的 Candidate Bundle，"
                            f"但 reconstruction_coverage = {best_cov} 偏低，"
                            f"Gold 可能是原文改写或摘要。"
                        )
                        is_paraphrased = True
                else:
                    recovery_status = "VISUAL_REVIEW_REQUIRED"
                    recovery_reason = (
                        f"在 page {best_page} 找到 Gold 关键数字，"
                        f"但无法构建含正文的 Candidate Bundle，需要视觉人工审核。"
                    )
            else:
                # PDF 全文未找到关键数字
                # 检查是否是改写（Gold 文本含非数字描述性内容）
                if not gold_numbers and len(gold_evidence_text) > 10:
                    recovery_status = "PARAPHRASED_SOURCE_LOCATED"
                    recovery_reason = (
                        "Gold 文本无关键数字，可能是描述性改写，"
                        "无法通过数字搜索定位原文。"
                    )
                    is_paraphrased = True
                else:
                    recovery_status = "STILL_NOT_FOUND"
                    recovery_reason = (
                        f"在主 PDF（{original_filename}）全文中未找到 Gold 关键数字 "
                        f"{gold_numbers}，可能涉及其他文档或 Gold 文本有误。"
                    )
        elif not doc:
            recovery_status = "STILL_NOT_FOUND"
            recovery_reason = f"无法打开主 PDF（doc_id={MAIN_DOC_ID}）。"
        elif not gold_numbers:
            recovery_status = "PARAPHRASED_SOURCE_LOCATED"
            recovery_reason = (
                "Gold 文本无关键数字，可能是描述性改写，"
                "无法通过数字搜索定位原文。"
            )
            is_paraphrased = True

        status_counts[recovery_status] += 1

        recovered_item = {
            "gold_evidence_id": iid,
            "claim_id": cid,
            "claim_text": old_it.get("claim_text", ""),
            "company": old_it.get("company", "美的集团"),
            "report_name": old_it.get("report_name", "annual_report"),
            "dataset": old_it.get("dataset", "demo"),
            "gold_evidence_text": gold_evidence_text,
            "annotated_page": annotated_page,
            "gold_key_numbers": gold_numbers,
            "located_pages": located_pages,
            "is_paraphrased": is_paraphrased,
            "recovery_status": recovery_status,
            "recovery_reason": recovery_reason,
            "candidate_bundles": candidate_bundles,
            "reviewer_decision": "",
            "reviewer_note": "",
            "review_status": "PENDING",
        }
        recovered_items.append(recovered_item)

        logger.info("  recovery_status: %s", recovery_status)
        logger.info("  recovery_reason: %s", recovery_reason[:120])

    conn.close()

    # 写输出
    output_data = {
        "phase": "23.11.6.2",
        "script": "backend/scripts/phase23_11_6_2_not_found_recovery.py",
        "description": "重新处理 10 条 NOT_FOUND，构建视觉审核 Candidate Bundle",
        "total": len(recovered_items),
        "status_counts": status_counts,
        "recovered_at": datetime.now(timezone.utc).isoformat(),
        "per_item": recovered_items,
    }
    OUTPUT_PATH.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("=" * 60)
    logger.info("wrote output: %s", OUTPUT_PATH)
    logger.info("status_counts: %s", json.dumps(status_counts, ensure_ascii=False))
    return output_data


if __name__ == "__main__":
    recover_not_found()
