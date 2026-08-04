"""Phase 23.11 Financial Fact Index (Channel A source).

Builds structured FinancialFact records from DocumentBlock + TableContext.
Queries by company (hard filter) + metric_canonical + period + scope + unit
+ normalized_value proximity.

Forbidden: gold_page, gold_block_id, expected_verdict, claim_id-specific
weights, is-correct-answer labels, dev-set labels.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import Document, DocumentBlock, DocumentPage
from app.models.financial_fact import FinancialFact
from app.services.evidence_retrieval.table_context import build_table_contexts


# Unit normalization to base (元)
_UNIT_TO_BASE: dict[str, float] = {
    "亿元": 1e8, "万元": 1e4, "千元": 1e3, "元": 1.0,
    "百万": 1e6, "十亿": 1e9, "元/股": 1.0,
}


def _normalize_value_to_base(raw_value: str, unit: str) -> float | None:
    """Convert raw_value with unit to base value (元)."""
    if not raw_value:
        return None
    # Strip parentheses (negative) and commas
    clean = raw_value.replace("(", "").replace(")", "").replace(",", "")
    try:
        v = float(clean)
    except ValueError:
        return None
    scale = _UNIT_TO_BASE.get(unit, 1.0)
    return v * scale


def _period_type_of(period: str) -> str:
    """Extract period type: FY, H1, Q1-Q4."""
    p = str(period or "").upper()
    if p.endswith("FY"):
        return "FY"
    if p.endswith("H1"):
        return "H1"
    if re.match(r".*Q[1-4]$", p):
        return p[-2:]
    return "FY"


# Canonical metric mapping (row_header -> canonical code)
_METRIC_CANONICAL: dict[str, str] = {
    "营业收入": "revenue", "营业总收入": "revenue",
    "净利润": "net_profit", "归母净利润": "net_profit",
    "归属于上市公司股东的净利润": "net_profit",
    "经营活动产生的现金流量净额": "operating_cash_flow",
    "基本每股收益": "eps", "每股收益": "eps",
    "毛利率": "gross_margin", "销售毛利率": "gross_margin",
    "净利率": "net_margin", "销售净利率": "net_margin",
    "加权平均净资产收益率": "roe", "净资产收益率": "roe",
    "总资产": "total_assets", "净资产": "net_assets",
    "资产负债率": "debt_ratio",
}


def _canonical_metric(row_header: str) -> str:
    """Map row_header to canonical metric code."""
    h = re.sub(r"\s+", "", row_header).strip()
    if h in _METRIC_CANONICAL:
        return _METRIC_CANONICAL[h]
    for k, v in _METRIC_CANONICAL.items():
        if k in h or h in k:
            return v
    return ""


def rebuild_for_document(session: Session, doc_id: int) -> int:
    """Rebuild all FinancialFact rows for a document from TableContext.

    Returns count of facts inserted. Idempotent: deletes existing facts for
    doc_id before rebuilding.
    """
    doc = session.get(Document, doc_id)
    if doc is None:
        return 0
    company = doc.company or doc.name or ""
    document_type = getattr(doc, "doc_type", "annual_report") or "annual_report"

    # Delete existing facts for this doc (idempotent rebuild)
    session.query(FinancialFact).filter(
        FinancialFact.document_id == doc_id
    ).delete()

    pages = (
        session.query(DocumentPage)
        .filter(DocumentPage.document_id == doc_id)
        .order_by(DocumentPage.page_number)
        .all()
    )

    count = 0
    for page in pages:
        contexts = build_table_contexts(session, doc_id, page.page_number)
        for idx, ctx in enumerate(contexts):
            if not ctx.row_header and not ctx.value:
                continue  # skip empty rows
            fact_id = f"FF-{doc_id}-{page.page_number}-{idx}"
            unit = ctx.unit_header or ""
            # Try to extract unit from table_title if not in header
            if not unit and ctx.table_title:
                m = re.search(
                    r"[（(](万亿元|亿元|百万元|万元|千元|元)[）)]",
                    ctx.table_title,
                )
                if m:
                    unit = m.group(1)
            period = ctx.period_header or ""
            period_type = _period_type_of(period) if period else "FY"
            raw_val = ctx.value or ""
            norm_val = _normalize_value_to_base(raw_val, unit) if raw_val else None

            fact = FinancialFact(
                fact_id=fact_id,
                company=company,
                document_id=doc_id,
                document_type=document_type,
                page=page.page_number,
                table_id=ctx.table_id,
                section_title=ctx.section_title or "",
                table_title=ctx.table_title or "",
                row_header=ctx.row_header or "",
                parent_row_header=ctx.parent_row_header or "",
                column_header=ctx.column_header or "",
                period_header=period,
                metric=ctx.metric or ctx.row_header or "",
                metric_canonical=_canonical_metric(ctx.row_header or ""),
                period=period,
                period_type=period_type,
                unit=unit,
                currency="CNY",
                scope=ctx.scope or "",
                raw_value=raw_val,
                normalized_value=norm_val,
                source_block_ids=ctx.source_block_ids or [],
                neighboring_context={
                    "rows": ctx.neighboring_rows[:5],
                    "columns": ctx.neighboring_columns[:6],
                },
            )
            session.add(fact)
            count += 1

    session.commit()
    return count


def query_facts(
    session: Session,
    claim: dict,
    routing,
    top_k: int = 10,
) -> list[dict]:
    """Query FinancialFact by company + metric + period + scope + unit.

    Returns Channel A candidates with evidence_id, text, page, document_id,
    table_id, row_header, period_header, unit, scope, normalized_value.
    """
    company = str(
        claim.get("entity") or claim.get("entity_name") or ""
    ).strip()
    metric_code = str(claim.get("metric_code") or "").strip()
    period = str(claim.get("period") or "").strip()
    unit = str(claim.get("unit") or "").strip()
    scope = str(claim.get("scope") or "consolidated").strip()

    q = session.query(FinancialFact)

    # Hard filter: company (if specified)
    if company:
        q = q.filter(FinancialFact.company == company)

    # Soft filters with scoring: fetch broad set then rank
    facts = q.order_by(FinancialFact.page).limit(top_k * 5).all()

    scored = []
    for f in facts:
        score = 0.0
        # Metric canonical match
        if metric_code and f.metric_canonical == metric_code:
            score += 0.4
        elif metric_code and f.metric_canonical:
            score += 0.1  # different metric
        # Period match
        if period and f.period:
            if period in f.period or f.period in period:
                score += 0.3
        # Scope match
        if scope and f.scope:
            if scope == f.scope:
                score += 0.2
        # Unit match
        if unit and f.unit:
            if unit == f.unit:
                score += 0.1
        # Base score for having data
        score += 0.1
        scored.append((score, f))

    # Sort by score descending, take top_k
    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, f in scored[:top_k]:
        # Build evidence text from fact fields
        text_parts = []
        if f.row_header:
            text_parts.append(f.row_header)
        if f.raw_value:
            text_parts.append(f.raw_value)
        if f.unit:
            text_parts.append(f.unit)
        if f.period_header:
            text_parts.append(f.period_header)
        text = " ".join(text_parts)
        results.append({
            "evidence_id": f.fact_id,
            "text": text,
            "page": f.page,
            "document_id": f.document_id,
            "table_id": f.table_id,
            "row_header": f.row_header,
            "period_header": f.period_header,
            "unit": f.unit,
            "scope": f.scope,
            "normalized_value": f.normalized_value,
            "final_score": score,
        })
    return results


__all__ = ["rebuild_for_document", "query_facts"]
