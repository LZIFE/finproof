"""Phase 23.19 Task 2 — Evidence Window Reconstruction

把表格块按「同页 + 同表 + 近 y 坐标」合并邻居块，重建财务证据单元：

    FinancialEvidenceObject = {
        metric, current_value, previous_value, growth,
        unit, period, table_type, source_blocks
    }

合并逻辑：
1. 锚块（含指标名或含数值的块）
2. 同页相邻块（±WINDOW_RADIUS block_index）+ 同表近 y（±Y_TOLERANCE pt）
3. 拼接文本 → extract_financial_fact（复用 Phase 23.18 提取器）
4. 行标签块 + 数值块合并：如 page 135 的 4443（数值）+ 4444（"其中：营业收入"行标签）
   合成 metric="营业收入", current=456,451,731, previous=407,149,600

不删除原始 block 文本。
"""
from __future__ import annotations

import re

from app.models import DocumentBlock
from app.services.evidence_retrieval.financial_fact_extractor import extract_financial_fact

_WINDOW_RADIUS = 3
_Y_TOLERANCE = 60.0  # 同表行 y0 允许偏差（pt）——列头/行标签/数值行同属一表


def _values_series(text: str) -> list[float]:
    """提取块文本中的数值序列（千分位数字 + 百分比），去重保序。"""
    out: list[float] = []
    for m in re.finditer(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", text or ""):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            continue
    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d+)?)%(?!\d)", text or ""):
        try:
            out.append(float(m.group(1)))
        except ValueError:
            continue
    return out


def _growth_of(current: float, previous: float) -> float | None:
    """计算增长率（%）。previous=0 或无意义时返回 None。"""
    if previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100.0, 4)


def reconstruct_evidence_window(
    session,
    anchor_block: DocumentBlock,
    radius: int = _WINDOW_RADIUS,
    y_tolerance: float = _Y_TOLERANCE,
) -> dict:
    """以锚块为中心重建 FinancialEvidenceObject。

    返回：
        {
          "metric", "current_value", "previous_value", "growth",
          "unit", "period", "table_type",
          "source_blocks": [block_id...],   # 按 block_index 升序
          "merged_text": 拼接文本（含原始块文本）
        }
    """
    # 1) 同页邻居块（±radius block_index）+ 同表近 y
    rows = (
        session.query(DocumentBlock)
        .filter(DocumentBlock.document_id == anchor_block.document_id,
                DocumentBlock.page_id == anchor_block.page_id)
        .order_by(DocumentBlock.block_index)
        .all()
    )
    if not rows:
        return _empty_object(anchor_block)

    idx_list = [r.block_index or 0 for r in rows]
    try:
        pos = idx_list.index(anchor_block.block_index or 0)
    except ValueError:
        pos = None

    window_blocks: list[DocumentBlock] = []
    if pos is not None:
        lo, hi = max(0, pos - radius), min(len(rows), pos + radius + 1)
        window_blocks.extend(rows[lo:hi])
    # 同表近 y：与锚块 y0 接近的块（覆盖行标签/数值行分离的情形）
    if anchor_block.y0 is not None:
        for r in rows:
            if r.y0 is not None and abs((r.y0 or 0) - (anchor_block.y0 or 0)) <= y_tolerance:
                if r not in window_blocks:
                    window_blocks.append(r)
    window_blocks.sort(key=lambda b: (b.block_index or 0))

    # 2) 拼接文本（合并所有窗口块原始文本，不删除）
    merged_lines = [(b.text or "") for b in window_blocks if b.text]
    merged_text = "\n".join(merged_lines)

    # 3) 提取财务事实
    fact = extract_financial_fact(merged_text)

    # 3b) metric 优先取行标签块（短文本、含指标词、无大数字的小块，如"其中：营业收入"），
    #     避免 merged_text 最长别名把"营业收入"误判为"营业总收入"
    metric = fact["metric"]
    for b in window_blocks:
        btext = (b.text or "").strip()
        if not btext or len(btext) > 30:
            continue
        # 行标签块特征：含指标词、无千分位大数字、通常含"其中/："
        if re.search(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", btext):
            continue
        sub_fact = extract_financial_fact(btext)
        if sub_fact["metric"]:
            metric = sub_fact["metric"]
            fact["metric"] = metric
            fact["metric_code"] = sub_fact["metric_code"]
            break

    # 4) 数值序列：current（第 1 个非年份数值）/ previous（第 2 个）
    values = _values_series(merged_text)
    # 过滤年份（4 位 19xx/20xx）
    non_year = [v for v in values if not (1900 <= v <= 2100)]
    current_value = non_year[0] if non_year else None
    previous_value = non_year[1] if len(non_year) >= 2 else None
    growth = _growth_of(current_value, previous_value) if (current_value and previous_value) else None

    return {
        "metric": fact["metric"],
        "metric_code": fact["metric_code"],
        "current_value": current_value,
        "previous_value": previous_value,
        "growth": growth,
        "unit": fact["unit"],
        "periods": fact["periods"],
        "period": fact["periods"][0] if fact["periods"] else "",
        "table_type": fact["table_type"],
        "row_label": fact["row_label"],
        "source_blocks": [b.id for b in window_blocks],
        "merged_text": merged_text,
        "has_number": fact["has_number"],
    }


def _empty_object(anchor_block: DocumentBlock) -> dict:
    return {
        "metric": "", "metric_code": "", "current_value": None, "previous_value": None,
        "growth": None, "unit": "", "periods": [], "period": "", "table_type": "other",
        "row_label": "", "source_blocks": [anchor_block.id], "merged_text": anchor_block.text or "",
        "has_number": False,
    }
