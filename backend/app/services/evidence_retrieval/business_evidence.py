"""Business and narrative evidence retrieval.

This layer is intentionally separate from the Financial Evidence Index.  It
handles business disclosures whose evidence is usually split across narrative
or company-metadata blocks (strategy, listing information, publication date),
and refuses weak numeric coincidences for unsupported business comparisons.

The layer only produces candidates.  Every candidate still passes through the
existing Evidence Gate, Selector, and core verifier.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import DocumentBlock, DocumentPage
from app.services.claim_router import (
    STRUCTURED_METRIC_CODES,
    TABLE_METRIC_CODES,
    route_claim,
)
from app.services.evidence_retrieval.engine import (
    _text_keywords,
    entity_matches,
    period_matches,
    text_similarity,
)


_COMPARISON_TYPES = {"COMPARISON", "COMPARATIVE_CLAIM"}
_KNOWN_FINANCIAL_METRICS = STRUCTURED_METRIC_CODES | TABLE_METRIC_CODES | {
    "total_operating_revenue",
    "net_profit_attributable",
    "deducted_net_profit",
    "quarterly_revenue",
    "quarterly_net_profit_attributable",
}
_GENERIC_ANCHOR_STOPWORDS = {
    "公司", "集团", "股份有限公司", "报告", "年度报告", "根据公司", "报告期",
    "持续", "深化", "实现", "超过", "高于", "低于", "达到", "水平", "业务",
}
_DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_NUMBER_RE = re.compile(r"(?<![\d.])-?\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class _PageBlocks:
    document_id: int
    page_id: int
    page_number: int
    report_period: str | None
    blocks: tuple[DocumentBlock, ...]


def _base_metric_code(metric_code: str) -> str:
    code = str(metric_code or "").strip().lower()
    for prefix in ("yoy_growth_", "qoq_growth_", "growth_"):
        if code.startswith(prefix):
            return code[len(prefix):]
    return code


def is_business_evidence_claim(claim: dict) -> bool:
    """Return whether a claim belongs to the strict business-evidence path."""
    routing = route_claim(claim)
    if routing.route == "NARRATIVE_FACT":
        return True

    claim_type = str(claim.get("claim_type") or "").upper()
    metric_code = _base_metric_code(
        str(claim.get("metric_code") or claim.get("metric") or "")
    )
    return (
        claim_type in _COMPARISON_TYPES
        and metric_code not in _KNOWN_FINANCIAL_METRICS
    )


def _load_pages(session: Session, claim: dict) -> list[_PageBlocks]:
    # Imported lazily to avoid a module-import cycle with service.py.
    from app.services.evidence_retrieval.service import filter_documents

    pages: list[_PageBlocks] = []
    for doc in filter_documents(session, claim):
        rows = (
            session.query(DocumentBlock, DocumentPage.page_number)
            .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
            .filter(
                DocumentBlock.document_id == doc.id,
                DocumentBlock.text.isnot(None),
            )
            .order_by(DocumentPage.page_index, DocumentBlock.block_index)
            .all()
        )
        grouped: dict[tuple[int, int], list[DocumentBlock]] = {}
        for block, page_number in rows:
            if not (block.text or "").strip():
                continue
            grouped.setdefault((block.page_id, page_number), []).append(block)
        for (page_id, page_number), blocks in grouped.items():
            pages.append(
                _PageBlocks(
                    document_id=doc.id,
                    page_id=page_id,
                    page_number=page_number,
                    report_period=doc.report_period,
                    blocks=tuple(blocks),
                )
            )
    return pages


def _claim_text(claim: dict) -> str:
    return str(claim.get("original_text") or claim.get("claim_text") or "")


def _claim_value(claim: dict) -> float | None:
    value = claim.get("reported_value")
    if value is None:
        value = claim.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _stock_codes(claim: dict) -> list[str]:
    text = _claim_text(claim)
    values = re.findall(r"(?<!\d)\d{6}(?!\d)", text)
    explicit = str(claim.get("stock_code") or "").strip()
    if explicit and explicit not in values:
        values.append(explicit)
    return values


def _report_year(claim: dict) -> str | None:
    period = str(claim.get("period") or "")
    match = re.search(r"(?:19|20)\d{2}", period)
    if match:
        return match.group(0)
    years = re.findall(r"(?:19|20)\d{2}", _claim_text(claim))
    return years[-1] if years else None


def _smallest_span(
    blocks: tuple[DocumentBlock, ...],
    required_groups: list[tuple[str, ...]],
) -> tuple[DocumentBlock, ...]:
    """Find the shortest contiguous block span covering all term groups."""
    if not blocks or not required_groups:
        return ()
    best: tuple[DocumentBlock, ...] = ()
    for start in range(len(blocks)):
        joined = ""
        for end in range(start, len(blocks)):
            joined += "\n" + (blocks[end].text or "")
            normalized = _normalized_text(joined)
            if all(any(_normalized_text(term) in normalized for term in group) for group in required_groups):
                candidate = blocks[start:end + 1]
                if not best or len(candidate) < len(best):
                    best = candidate
                break
    return best


def _candidate(
    claim: dict,
    page: _PageBlocks,
    blocks: tuple[DocumentBlock, ...],
    score: float,
    matched_terms: list[str],
    kind: str,
) -> dict:
    text = "\n".join((block.text or "").strip() for block in blocks if (block.text or "").strip())
    anchor = blocks[0]
    entity = str(claim.get("entity_name") or claim.get("entity") or claim.get("company") or "")
    period_score = period_matches(claim.get("period"), text, page.report_period)
    entity_score = entity_matches(text, entity)
    semantic_score = text_similarity(_claim_text(claim), text)
    quality = min(1.0, max(score, 0.0))
    return {
        "document_id": page.document_id,
        "page_number": page.page_number,
        "block_id": anchor.id,
        "page_id": page.page_id,
        "y0": anchor.y0 or 0.0,
        "reading_order": anchor.reading_order or 0,
        "block_text": text,
        "evidence_text": text,
        "source_block_ids": [block.id for block in blocks],
        "business_match_score": round(quality, 4),
        "final_score": round(quality, 4),
        "metric_score": round(quality, 4),
        "value_score": 1.0 if _value_matches(claim, text) else 0.0,
        "period_score": round(period_score, 4),
        "entity_score": round(entity_score, 4),
        "text_score": round(semantic_score, 4),
        "matched_terms": matched_terms,
        "retrieval_method": "business_evidence",
        "evidence_type": "BUSINESS_DISCLOSURE",
        "evidence_tier": "primary",
        "evidence_quality_score": round(quality, 4),
        "evidence_rank_reason": f"business:{kind}; matched={','.join(matched_terms)}",
        "business_evidence_kind": kind,
        "financial_fact": None,
    }


def _listing_candidates(claim: dict, pages: list[_PageBlocks]) -> list[dict]:
    codes = _stock_codes(claim)
    if not codes:
        return []
    text = _claim_text(claim)
    exchange_terms: tuple[str, ...]
    if "深圳" in text or "深交所" in text:
        exchange_terms = ("深圳证券交易所", "深交所")
    elif "上海" in text or "上交所" in text:
        exchange_terms = ("上海证券交易所", "上交所")
    else:
        exchange_terms = ("证券交易所",)

    out: list[dict] = []
    for page in pages:
        span = _smallest_span(
            page.blocks,
            [tuple(codes), ("股票代码",), exchange_terms],
        )
        if not span:
            continue
        out.append(
            _candidate(
                claim,
                page,
                span,
                1.0,
                [codes[0], "股票代码", exchange_terms[0]],
                "listing_info",
            )
        )
    return out


def _publication_date_candidates(claim: dict, pages: list[_PageBlocks]) -> list[dict]:
    report_year = _report_year(claim)
    if not report_year:
        return []
    title_terms = (f"{report_year}年度报告", f"{report_year}年年度报告")
    out: list[dict] = []
    for page in pages:
        # Publication/signature dates are cover evidence, not arbitrary dates in notes.
        if page.page_number > 3:
            continue
        entity = str(claim.get("entity_name") or claim.get("entity") or claim.get("company") or "")
        entity_blocks = [
            block for block in page.blocks
            if entity and entity_matches(block.text or "", entity) > 0
        ]
        title_blocks = [
            block for block in page.blocks
            if any(_normalized_text(term) in _normalized_text(block.text or "") for term in title_terms)
        ]
        date_blocks = [block for block in page.blocks if _DATE_RE.search(block.text or "")]
        if not entity_blocks or not title_blocks or not date_blocks:
            continue
        selected: list[DocumentBlock] = []
        for block in page.blocks:
            block_text = block.text or ""
            if (
                block in entity_blocks
                or block in title_blocks
                or block in date_blocks
                or "董事长" in block_text
                or "签名" in block_text
            ):
                selected.append(block)
        if not selected:
            continue
        date_text = date_blocks[0].text or ""
        matched = [f"{report_year}年度报告", _DATE_RE.search(date_text).group(0)]
        out.append(
            _candidate(
                claim,
                page,
                tuple(selected),
                1.0,
                matched,
                "publication_date",
            )
        )
    return out


def _content_anchors(claim: dict) -> list[str]:
    text = _claim_text(claim)
    anchors = [
        anchor.strip()
        for anchor in _text_keywords(text, limit=12)
        if anchor.strip() and anchor.strip() not in _GENERIC_ANCHOR_STOPWORDS
    ]
    anchors.extend(
        token.upper()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text)
        if token.upper() not in {"FY", "H1", "Q1", "Q2", "Q3", "Q4"}
    )
    # Stable order and no anchors contained by a more specific anchor.
    unique: list[str] = []
    for anchor in sorted(set(anchors), key=lambda item: (-len(item), item)):
        if any(anchor in existing for existing in unique):
            continue
        unique.append(anchor)
    return unique


def _anchor_matches(anchor: str, text: str) -> bool:
    normalized_anchor = _normalized_text(anchor)
    normalized_text = _normalized_text(text)
    if normalized_anchor in normalized_text:
        return True
    if re.fullmatch(r"[a-z0-9_-]+", normalized_anchor):
        return False
    if len(normalized_anchor) >= 5:
        return any(
            normalized_anchor[index:index + 4] in normalized_text
            for index in range(len(normalized_anchor) - 3)
        )
    return False


def _number_values(text: str) -> list[float]:
    values: list[float] = []
    for raw in _NUMBER_RE.findall(text):
        try:
            values.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return values


def _unit_matches(claim: dict, text: str) -> bool:
    unit = str(claim.get("unit") or "").replace("人民币", "").strip()
    if not unit:
        return True
    normalized = _normalized_text(text)
    if unit in {"个百分点", "百分点"}:
        return any(token in normalized for token in ("个百分点", "百分点", "pp"))
    if unit in {"%", "％", "percent", "percentage"}:
        return "%" in normalized or "％" in normalized or "百分比" in normalized
    return _normalized_text(unit) in normalized


def _value_matches(claim: dict, text: str) -> bool:
    expected = _claim_value(claim)
    if expected is None:
        return False
    if not _unit_matches(claim, text):
        return False
    tolerance = max(abs(expected) * 0.001, 1e-6)
    return any(abs(value - expected) <= tolerance for value in _number_values(text))


def _generic_candidates(claim: dict, pages: list[_PageBlocks]) -> list[dict]:
    anchors = _content_anchors(claim)
    if len(anchors) < 2:
        return []
    numeric = _claim_value(claim) is not None
    out: list[dict] = []

    def consider(page: _PageBlocks, blocks: tuple[DocumentBlock, ...]) -> None:
        text = "\n".join(block.text or "" for block in blocks)
        if claim.get("period") and period_matches(claim.get("period"), text, page.report_period) <= 0:
            return
        matched = [anchor for anchor in anchors if _anchor_matches(anchor, text)]
        coverage = len(matched) / len(anchors)
        if len(matched) < 2 or coverage < 0.4:
            return
        if numeric and not _value_matches(claim, text):
            return
        semantic = text_similarity(_claim_text(claim), text)
        score = min(1.0, 0.55 * coverage + 0.35 * semantic + (0.10 if numeric else 0.05))
        out.append(_candidate(claim, page, blocks, score, matched, "semantic_business"))

    for page in pages:
        # Prefer a single disclosure block.  Only if needed, try small local spans;
        # wide page windows can introduce unrelated financial scope contradictions.
        page_before = len(out)
        for block in page.blocks:
            consider(page, (block,))
        if len(out) > page_before:
            continue
        for size in (2, 3):
            for start in range(0, len(page.blocks) - size + 1):
                consider(page, page.blocks[start:start + size])
            if len(out) > page_before:
                break
    return out


def retrieve_business_evidence(
    session: Session,
    claim: dict,
    top_k: int = 5,
) -> list[dict]:
    """Return strict business evidence candidates for one claim.

    If the business assertion cannot be fully grounded, the function returns
    an empty list instead of falling back to coincidental financial numbers.
    """
    if not is_business_evidence_claim(claim):
        return []
    pages = _load_pages(session, claim)
    if not pages:
        return []

    metric_code = str(claim.get("metric_code") or claim.get("metric") or "").lower()
    if metric_code == "listing_info":
        candidates = _listing_candidates(claim, pages)
    elif metric_code == "publication_date":
        candidates = _publication_date_candidates(claim, pages)
    else:
        candidates = _generic_candidates(claim, pages)

    # Deduplicate the same reconstructed span and keep the strongest version.
    deduped: dict[tuple[int, ...], dict] = {}
    for candidate in candidates:
        key = tuple(candidate.get("source_block_ids") or [candidate["block_id"]])
        if key not in deduped or candidate["business_match_score"] > deduped[key]["business_match_score"]:
            deduped[key] = candidate
    ranked = sorted(
        deduped.values(),
        key=lambda item: (-item["business_match_score"], item["document_id"], item["page_number"]),
    )[:top_k]
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
    return ranked


__all__ = ["is_business_evidence_claim", "retrieve_business_evidence"]
