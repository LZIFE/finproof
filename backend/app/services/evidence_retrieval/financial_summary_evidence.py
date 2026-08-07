"""Strict primary-summary recovery for attributable-profit evidence.

The Financial Fact Index can identify the right fact while leaving the
retrieval candidate anchored on a label-only or adjacent unrelated block.  The
official adapter then sees incomplete text.  This module reconstructs a small
verification window for the two profit metrics whose scope is intrinsic to the
metric name, without changing general reranker weights.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import DocumentBlock, DocumentPage
from app.services.evidence_retrieval.engine import (
    entity_matches,
    period_matches,
    text_similarity,
)


_TARGET_MARKERS: dict[str, tuple[str, ...]] = {
    "net_profit_attributable": (
        "归属于上市公司股东的净利润",
        "归属于母公司股东的净利润",
        "归母净利润",
    ),
    "deducted_net_profit": (
        "归属于上市公司股东的扣除非经常性损益的净利润",
        "扣除非经常性损益的净利润",
        "扣非归母净利润",
    ),
}
_ADJUSTED_MARKERS = ("扣非", "扣除非经常性损益")
_NUMBER_RE = re.compile(r"(?<![\d.])-?\d[\d,]*(?:\.\d+)?")
_UNIT_TO_YUAN = {"元": 1.0, "千元": 1_000.0, "万元": 10_000.0, "亿元": 100_000_000.0}


@dataclass(frozen=True)
class _SummaryPage:
    document_id: int
    page_id: int
    page_number: int
    report_period: str
    blocks: tuple[DocumentBlock, ...]


def _metric_code(claim: dict) -> str:
    return str(claim.get("metric_code") or claim.get("metric") or "").strip().lower()


def _claim_text(claim: dict) -> str:
    return str(claim.get("original_text") or claim.get("claim_text") or "")


def _claim_value(claim: dict) -> float | None:
    value = claim.get("reported_value")
    if value is None:
        value = claim.get("value")
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _claim_decimals(claim: dict, expected: float) -> int:
    for match in _NUMBER_RE.finditer(_claim_text(claim)):
        raw = match.group(0).replace(",", "")
        try:
            if abs(float(raw) - expected) <= 1e-9:
                return len(raw.split(".", 1)[1]) if "." in raw else 0
        except ValueError:
            continue
    rendered = f"{expected:.8f}".rstrip("0").rstrip(".")
    return len(rendered.split(".", 1)[1]) if "." in rendered else 0


def _join_split_chinese(text: str) -> str:
    """Join PDF line breaks inside Chinese metric labels, not between values."""
    result = str(text or "")
    pattern = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
    while pattern.search(result):
        result = pattern.sub("", result)
    return result.strip()


def _source_unit(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text)
    for unit in ("亿元", "万元", "千元"):
        if unit in compact:
            return unit
    if "元" in compact and "元/股" not in compact:
        return "元"
    return None


def _value_matches(
    claim: dict,
    metric_text: str,
    markers: tuple[str, ...],
) -> bool:
    expected = _claim_value(claim)
    claim_unit = str(claim.get("unit") or "").strip()
    if expected is None or claim_unit not in _UNIT_TO_YUAN:
        return False
    normalized = _join_split_chinese(metric_text)
    marker_positions = [normalized.find(marker) for marker in markers if marker in normalized]
    if not marker_positions:
        return False
    tail = normalized[min(marker_positions):]
    source_unit = _source_unit(tail)
    if source_unit is None:
        return False
    for number_match in _NUMBER_RE.finditer(tail):
        raw = number_match.group(0)
        following = tail[number_match.end():number_match.end() + 2]
        if "%" in following or "％" in following:
            continue
        try:
            source_value = float(raw.replace(",", ""))
        except ValueError:
            continue
        converted = source_value * _UNIT_TO_YUAN[source_unit] / _UNIT_TO_YUAN[claim_unit]
        decimals = _claim_decimals(claim, expected)
        return round(converted, decimals) == round(expected, decimals)
    return False


def _load_summary_pages(session: Session, claim: dict) -> list[_SummaryPage]:
    # Lazy import avoids the service -> summary -> service import cycle.
    from app.services.evidence_retrieval.service import filter_documents

    claim_period = str(claim.get("period") or "").upper().replace(" ", "")
    pages: list[_SummaryPage] = []
    for doc in filter_documents(session, claim):
        doc_period = str(doc.report_period or "").upper().replace(" ", "")
        if not claim_period or doc_period != claim_period:
            continue
        rows = (
            session.query(DocumentBlock, DocumentPage.page_number)
            .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
            .filter(
                DocumentBlock.document_id == doc.id,
                DocumentBlock.text.isnot(None),
                DocumentPage.page_number <= 20,
            )
            .order_by(DocumentPage.page_index, DocumentBlock.block_index)
            .all()
        )
        grouped: dict[tuple[int, int], list[DocumentBlock]] = {}
        for block, page_number in rows:
            if (block.text or "").strip():
                grouped.setdefault((block.page_id, page_number), []).append(block)
        for (page_id, page_number), blocks in grouped.items():
            pages.append(
                _SummaryPage(
                    document_id=doc.id,
                    page_id=page_id,
                    page_number=page_number,
                    report_period=str(doc.report_period or ""),
                    blocks=tuple(blocks),
                )
            )
    return pages


def _candidate(
    claim: dict,
    page: _SummaryPage,
    selected: tuple[DocumentBlock, ...],
    metric_block: DocumentBlock,
    row_blocks: tuple[DocumentBlock, ...],
) -> dict:
    rendered: list[str] = []
    row_ids = {block.id for block in row_blocks}
    for block in selected:
        text = block.text or ""
        rendered.append(_join_split_chinese(text) if block.id in row_ids else text.strip())
    evidence_text = "\n".join(text for text in rendered if text)
    entity = str(claim.get("entity_name") or claim.get("entity") or claim.get("company") or "")
    return {
        "document_id": page.document_id,
        "page_number": page.page_number,
        "block_id": metric_block.id,
        "page_id": page.page_id,
        "y0": metric_block.y0 or 0.0,
        "reading_order": metric_block.reading_order or 0,
        "block_text": evidence_text,
        "evidence_text": evidence_text,
        "source_block_ids": [block.id for block in selected],
        "final_score": 1.0,
        "rerank_score": 1.0,
        "metric_score": 1.0,
        "value_score": 1.0,
        "period_score": round(period_matches(claim.get("period"), evidence_text, page.report_period), 4),
        "entity_score": round(entity_matches(evidence_text, entity), 4),
        "text_score": round(text_similarity(_claim_text(claim), evidence_text), 4),
        "matched_terms": list(_TARGET_MARKERS[_metric_code(claim)]),
        "retrieval_method": "financial_summary_evidence",
        "evidence_type": "PRIMARY_DISCLOSURE",
        "evidence_tier": "primary",
        "evidence_quality_score": 1.0,
        "evidence_rank_reason": "strict metric/period/current-value summary match",
        "financial_fact": None,
    }


def retrieve_financial_summary_evidence(session: Session, claim: dict) -> list[dict]:
    """Return complete exact-value summary rows for intrinsic-scope metrics."""
    metric_code = _metric_code(claim)
    markers = _TARGET_MARKERS.get(metric_code)
    if markers is None or _claim_value(claim) is None:
        return []

    entity = str(claim.get("entity_name") or claim.get("entity") or claim.get("company") or "")
    claim_year_match = re.search(r"20\d{2}", str(claim.get("period") or ""))
    claim_year = claim_year_match.group(0) if claim_year_match else ""
    candidates: list[dict] = []
    for page in _load_summary_pages(session, claim):
        for index, block in enumerate(page.blocks):
            block_text = _join_split_chinese(block.text or "")
            if not any(marker in block_text for marker in markers):
                continue
            if metric_code == "net_profit_attributable" and any(
                marker in block_text for marker in _ADJUSTED_MARKERS
            ):
                continue

            row_blocks = (block,)
            for end in range(index, min(index + 3, len(page.blocks))):
                row_blocks = page.blocks[index:end + 1]
                row_text = "\n".join(_join_split_chinese(item.text or "") for item in row_blocks)
                if _value_matches(claim, row_text, markers):
                    break
            else:
                continue

            title = next(
                (
                    item for item in page.blocks
                    if entity
                    and entity_matches(item.text or "", entity) > 0
                    and (not claim_year or claim_year in (item.text or ""))
                ),
                None,
            )
            if title is None:
                continue
            header = next(
                (
                    item for item in reversed(page.blocks[max(0, index - 12):index])
                    if (
                        (claim_year and claim_year in (item.text or ""))
                        or "本报告期" in (item.text or "")
                    )
                    and any(token in (item.text or "") for token in ("上年", "增减", "2024"))
                ),
                None,
            )
            selected_by_id = {title.id: title}
            if header is not None:
                selected_by_id[header.id] = header
            for row_block in row_blocks:
                selected_by_id[row_block.id] = row_block
            selected = tuple(
                sorted(selected_by_id.values(), key=lambda item: item.block_index)
            )
            candidates.append(_candidate(claim, page, selected, block, row_blocks))

    candidates.sort(key=lambda item: (item["page_number"], item["block_id"]))
    return candidates[:2]


__all__ = ["retrieve_financial_summary_evidence"]
