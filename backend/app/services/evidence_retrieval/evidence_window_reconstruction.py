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


# Phase 23.21 Task 2：表格行图——块角色分类
_HEADER_BLOCK_KW = ("项目", "附注", "2025年度", "2024年度", "本期金额", "上期金额", "年初余额", "期末余额", "合并", "公司")
_UNIT_BLOCK_KW = ("千元", "万元", "亿元", "百万元", "元", "单位", "人民币")


def _classify_block_role(text: str) -> str:
    """表格块角色：row_label / numeric / header / unit / other。

    优先顺序：unit（含单位词+短文本）→ header（表头词+无财务大数字）→
    numeric（含千分位大数字）→ row_label（含指标词）→ other。
    """
    t = (text or "").strip()
    if not t:
        return "other"
    has_big_number = bool(re.search(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", t))
    # 单位块：短文本 + 含单位词（如"（除特别注明外，金额单位为人民币千元）"）
    if any(u in t for u in _UNIT_BLOCK_KW) and not has_big_number and len(t) < 60:
        return "unit"
    # 表头块：表头词 + 无财务大数字
    if any(h in t for h in _HEADER_BLOCK_KW) and not has_big_number:
        return "header"
    # 数值块：含千分位大数字
    if has_big_number:
        return "numeric"
    # 行标签块：含指标词（短文本）
    from app.services.evidence_retrieval.financial_fact_extractor import _metric_in
    if _metric_in(t) and len(t) < 60:
        return "row_label"
    return "other"


def reconstruct_evidence_window(
    session,
    anchor_block: DocumentBlock,
    radius: int = _WINDOW_RADIUS,
    y_tolerance: float = _Y_TOLERANCE,
) -> dict:
    """以锚块为中心重建 FinancialEvidenceObject（Phase 23.21：表格行图重建）。

    行图重建（table row graph）：
    1. 同页邻居块（±radius block_index）+ 同表近 y
    2. 按角色分类：row_label / numeric / header / unit
    3. 组合：numeric 块（数值）+ 最近的 row_label 块（指标名）
             + header 块（期间列头）+ unit 块（单位）
    4. 行标签优先提供 metric；数值序列提供 current/previous/growth

    返回：
        {
          "metric", "metric_code", "current_value", "previous_value", "growth",
          "unit", "period", "table_type", "row_label",
          "block_roles": {block_id: role},   # Phase 23.21 新增
          "source_blocks": [block_id...],
          "merged_text": 拼接文本
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

    # Phase 23.21 Task 2：角色分类
    block_roles: dict[int, str] = {}
    for b in window_blocks:
        block_roles[b.id] = _classify_block_role(b.text or "")

    # 2) 拼接文本（合并所有窗口块原始文本，不删除）
    merged_lines = [(b.text or "") for b in window_blocks if b.text]
    merged_text = "\n".join(merged_lines)

    # 3) 提取财务事实
    fact = extract_financial_fact(merged_text)

    # 3a) Phase 23.26：锚块自身文本含指标时优先采用（如 block 189 "营业收入（千元）456,451,731"）。
    #     修复窗口合并把 page 9 其他指标行（归母净利润）的 metric 误赋给营业收入块的问题。
    anchor_self = extract_financial_fact(anchor_block.text or "")
    metric = anchor_self["metric"] or fact["metric"]
    if anchor_self["metric"]:
        fact["metric"] = anchor_self["metric"]
        fact["metric_code"] = anchor_self["metric_code"]
        fact["row_label"] = anchor_self["metric"]

    # 3b) metric 兜底：锚块自身无指标时，取行标签块（Phase 23.21：行图组合）
    #     避免 merged_text 最长别名把"营业收入"误判为"营业总收入"
    if not anchor_self["metric"]:
        row_label_blocks = [b for b in window_blocks if block_roles.get(b.id) == "row_label"]
        for b in row_label_blocks:
            sub_fact = extract_financial_fact(b.text or "")
            if sub_fact["metric"]:
                metric = sub_fact["metric"]
                fact["metric"] = metric
                fact["metric_code"] = sub_fact["metric_code"]
                fact["row_label"] = sub_fact["metric"]
                break
        # 无 row_label 块时回退：短文本含指标词的小块
        if not row_label_blocks:
            for b in window_blocks:
                btext = (b.text or "").strip()
                if not btext or len(btext) > 30:
                    continue
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

    # 5) unit/period 优先取 unit/header 角色块（Phase 23.21：行图组合）
    unit = fact["unit"]
    if not unit:
        for b in window_blocks:
            if block_roles.get(b.id) == "unit":
                sub = extract_financial_fact(b.text or "")
                if sub["unit"]:
                    unit = sub["unit"]
                    break
    periods = fact["periods"]
    header_periods: list[str] = []
    for b in window_blocks:
        if block_roles.get(b.id) == "header":
            sub = extract_financial_fact(b.text or "")
            for p in sub["periods"]:
                if p not in header_periods:
                    header_periods.append(p)
    if not periods and header_periods:
        periods = header_periods

    return {
        "metric": fact["metric"],
        "metric_code": fact["metric_code"],
        "current_value": current_value,
        "previous_value": previous_value,
        "growth": growth,
        "unit": unit,
        "periods": periods,
        "period": periods[0] if periods else "",
        "table_type": fact["table_type"],
        "row_label": fact["row_label"],
        "block_roles": block_roles,          # Phase 23.21 新增：块角色图
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
