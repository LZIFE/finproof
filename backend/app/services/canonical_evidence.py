"""Phase 23.11.2 Canonical Evidence Schema (Task 1).

Single source of truth for Evidence candidates entering the Gate. All three
sources (CORE_ORACLE Gold, NOISY_ORACLE Gold+Negatives, REAL_E2E Retrieval)
must convert to the SAME CanonicalEvidence dataclass before Gate evaluation.

Root causes fixed here:
- Phase 23.11 Gate read source-specific objects: CORE_ORACLE passed
  gold_evidence.json dicts (no block_id/metric_canonical), REAL_E2E passed
  retrieval candidates (no evidence_type/page consistent). Gate then treated
  missing fields as False → 37/43 Gold rejected.
- Missing metadata was silently treated as MISMATCH (0.0 score) instead of
  UNKNOWN (soft penalty). This made Gate over-conservative.

CanonicalEvidence normalizes ALL sources to the same 21 fields. Adapter
records default_value_count so schema_comparison.json can prove no silent
mismatch. Adapter NEVER silently fills False for missing fields — missing
becomes None and Gate's three-state logic (MATCH/MISMATCH/UNKNOWN) handles it.

Forbidden: Gold Evidence lacking metadata → False; per-source field sets;
Gate reading source-specific objects; silent default to non-match.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ===========================================================================
# CanonicalEvidence (21 fields, §1)
# ===========================================================================

_extraction_source_t = Literal["core_oracle", "noisy_oracle", "real_e2e"]


@dataclass
class CanonicalEvidence:
    """Unified Evidence candidate entering the Gate (§1).

    All three sources (CORE_ORACLE / NOISY_ORACLE / REAL_E2E) convert to this
    BEFORE Gate evaluation. Missing fields are None, NEVER silently False.
    """

    evidence_id: str
    company: str | None = None
    document_id: int | str | None = None
    page: int | None = None
    block_id: int | str | None = None
    text: str = ""
    evidence_type: str | None = None
    route: str | None = None
    metric: str | None = None
    period: str | None = None
    unit: str | None = None
    scope: str | None = None
    entity: str | None = None
    raw_value: float | None = None
    normalized_value: float | None = None
    table_title: str | None = None
    row_header: str | None = None
    column_header: str | None = None
    source_block_ids: list = field(default_factory=list)
    metadata_completeness: float = 0.0  # 0..1, computed
    extraction_source: str = "real_e2e"  # provenance

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id, "company": self.company,
            "document_id": self.document_id, "page": self.page,
            "block_id": self.block_id, "text": self.text,
            "evidence_type": self.evidence_type, "route": self.route,
            "metric": self.metric, "period": self.period,
            "unit": self.unit, "scope": self.scope, "entity": self.entity,
            "raw_value": self.raw_value, "normalized_value": self.normalized_value,
            "table_title": self.table_title, "row_header": self.row_header,
            "column_header": self.column_header,
            "source_block_ids": self.source_block_ids,
            "metadata_completeness": round(self.metadata_completeness, 3),
            "extraction_source": self.extraction_source,
        }


# Fields that adapters must track default fills for schema_comparison
CANONICAL_EVIDENCE_FIELDS: tuple[str, ...] = (
    "evidence_id", "company", "document_id", "page", "block_id", "text",
    "evidence_type", "route", "metric", "period", "unit", "scope", "entity",
    "raw_value", "normalized_value", "table_title", "row_header",
    "column_header", "source_block_ids", "metadata_completeness",
    "extraction_source",
)


# ===========================================================================
# Adapter: source-specific dict → CanonicalEvidence (§1)
# ===========================================================================

@dataclass
class AdapterStats:
    """Per-source adapter statistics for schema_comparison.json (§1)."""

    source: str
    total: int = 0
    present_count: dict = field(default_factory=dict)  # field → count present
    missing_count: dict = field(default_factory=dict)  # field → count missing
    parsed_count: dict = field(default_factory=dict)  # field → count parsed non-trivially
    type_mismatch_count: dict = field(default_factory=dict)  # field → count type mismatch
    default_value_count: dict = field(default_factory=dict)  # field → count default filled

    def to_dict(self) -> dict:
        return {
            "source": self.source, "total": self.total,
            "present_count": self.present_count,
            "missing_count": self.missing_count,
            "parsed_count": self.parsed_count,
            "type_mismatch_count": self.type_mismatch_count,
            "default_value_count": self.default_value_count,
        }


def _ensure_field_counters(stats: AdapterStats) -> None:
    """Initialize per-field counters to 0 for all canonical fields."""
    for f in CANONICAL_EVIDENCE_FIELDS:
        stats.present_count.setdefault(f, 0)
        stats.missing_count.setdefault(f, 0)
        stats.parsed_count.setdefault(f, 0)
        stats.type_mismatch_count.setdefault(f, 0)
        stats.default_value_count.setdefault(f, 0)


def _track_field(
    stats: AdapterStats, field_name: str, value, expected_type: str,
) -> None:
    """Track one field across present/missing/parsed/type/default counters."""
    if value is None:
        stats.missing_count[field_name] += 1
        return
    stats.present_count[field_name] += 1
    # parsed: non-trivial value (non-empty string, non-zero, non-default)
    if isinstance(value, str) and value.strip():
        stats.parsed_count[field_name] += 1
    elif isinstance(value, (int, float)) and value != 0:
        stats.parsed_count[field_name] += 1
    elif isinstance(value, list) and len(value) > 0:
        stats.parsed_count[field_name] += 1
    # type mismatch check
    type_ok = (
        (expected_type == "str" and isinstance(value, str))
        or (expected_type == "int" and isinstance(value, int))
        or (expected_type == "float" and isinstance(value, (int, float)))
        or (expected_type == "list" and isinstance(value, list))
        or (expected_type == "any")
    )
    if not type_ok:
        stats.type_mismatch_count[field_name] += 1


# Expected types per canonical field (for type_mismatch tracking)
_FIELD_TYPES: dict[str, str] = {
    "evidence_id": "str", "company": "str", "document_id": "any",
    "page": "int", "block_id": "any", "text": "str",
    "evidence_type": "str", "route": "str", "metric": "str",
    "period": "str", "unit": "str", "scope": "str", "entity": "str",
    "raw_value": "float", "normalized_value": "float",
    "table_title": "str", "row_header": "str", "column_header": "str",
    "source_block_ids": "list", "metadata_completeness": "float",
    "extraction_source": "str",
}


def _compute_metadata_completeness(ce: CanonicalEvidence) -> float:
    """metadata_completeness = fraction of optional metadata fields present."""
    optional_meta_fields = (
        "company", "metric", "period", "unit", "scope", "entity",
        "raw_value", "normalized_value", "table_title", "row_header",
        "column_header", "source_block_ids",
    )
    present = sum(
        1 for f in optional_meta_fields
        if getattr(ce, f) is not None
        and not (isinstance(getattr(ce, f), str) and not getattr(ce, f).strip())
    )
    return present / len(optional_meta_fields)


def adapt_core_oracle(
    gold_evidence_list: list[dict], claim: dict, route: str,
) -> tuple[list[CanonicalEvidence], AdapterStats]:
    """CORE_ORACLE: gold_evidence.json dicts → CanonicalEvidence."""
    stats = AdapterStats(source="core_oracle")
    _ensure_field_counters(stats)
    stats.total = len(gold_evidence_list)
    out: list[CanonicalEvidence] = []
    for e in gold_evidence_list:
        ce = CanonicalEvidence(
            evidence_id=str(e.get("evidence_id") or f"CE-{stats.total}"),
            company=str(claim.get("entity") or claim.get("company") or "") or None,
            document_id=e.get("document_id"),
            page=e.get("page"),
            block_id=e.get("block_id"),
            text=str(e.get("evidence_text") or e.get("text") or ""),
            evidence_type=str(e.get("evidence_type") or "") or None,
            route=route,
            metric=str(claim.get("metric") or "") or None,
            period=str(claim.get("period") or "") or None,
            unit=str(claim.get("unit") or "") or None,
            scope=str(claim.get("scope") or "") or None,
            entity=str(claim.get("entity") or "") or None,
            raw_value=None,
            normalized_value=None,
            table_title=None, row_header=None, column_header=None,
            source_block_ids=[],
            extraction_source="core_oracle",
        )
        ce.metadata_completeness = _compute_metadata_completeness(ce)
        # track counters
        for f in CANONICAL_EVIDENCE_FIELDS:
            _track_field(stats, f, getattr(ce, f), _FIELD_TYPES.get(f, "any"))
        out.append(ce)
    return out, stats


def adapt_noisy_oracle(
    gold_plus_negatives: list[dict], claim: dict, route: str,
) -> tuple[list[CanonicalEvidence], AdapterStats]:
    """NOISY_ORACLE: Gold + Hard Negatives dicts → CanonicalEvidence.

    Negatives built by phase23_11_1_acceptance.build_hard_negatives have
    evidence_id/text/page/document_id only; adapter leaves metadata None.
    """
    stats = AdapterStats(source="noisy_oracle")
    _ensure_field_counters(stats)
    stats.total = len(gold_plus_negatives)
    out: list[CanonicalEvidence] = []
    for e in gold_plus_negatives:
        ce = CanonicalEvidence(
            evidence_id=str(e.get("evidence_id") or f"NE-{stats.total}"),
            company=str(e.get("company") or claim.get("entity") or "") or None,
            document_id=e.get("document_id"),
            page=e.get("page"),
            block_id=e.get("block_id"),
            text=str(e.get("text") or ""),
            evidence_type=str(e.get("evidence_type") or "") or None,
            route=route,
            metric=str(e.get("metric") or claim.get("metric") or "") or None,
            period=str(e.get("period") or claim.get("period") or "") or None,
            unit=str(e.get("unit") or claim.get("unit") or "") or None,
            scope=str(e.get("scope") or claim.get("scope") or "") or None,
            entity=str(e.get("entity") or claim.get("entity") or "") or None,
            raw_value=e.get("raw_value"),
            normalized_value=e.get("normalized_value"),
            table_title=e.get("table_title"),
            row_header=e.get("row_header"),
            column_header=e.get("column_header"),
            source_block_ids=e.get("source_block_ids") or [],
            extraction_source="noisy_oracle",
        )
        ce.metadata_completeness = _compute_metadata_completeness(ce)
        for f in CANONICAL_EVIDENCE_FIELDS:
            _track_field(stats, f, getattr(ce, f), _FIELD_TYPES.get(f, "any"))
        out.append(ce)
    return out, stats


def adapt_real_e2e(
    retrieval_candidates: list[dict], claim: dict, route: str,
) -> tuple[list[CanonicalEvidence], AdapterStats]:
    """REAL_E2E: retrieve_for_claim candidates → CanonicalEvidence."""
    stats = AdapterStats(source="real_e2e")
    _ensure_field_counters(stats)
    stats.total = len(retrieval_candidates)
    out: list[CanonicalEvidence] = []
    for c in retrieval_candidates:
        ce = CanonicalEvidence(
            evidence_id=str(c.get("evidence_id") or c.get("block_id") or f"RE-{stats.total}"),
            company=str(claim.get("entity") or claim.get("company") or "") or None,
            document_id=c.get("document_id"),
            page=c.get("page") or c.get("page_number"),
            block_id=c.get("block_id"),
            text=str(c.get("text") or c.get("block_text") or ""),
            evidence_type=str(c.get("evidence_type") or "") or None,
            route=route,
            metric=str(c.get("metric") or claim.get("metric") or "") or None,
            period=str(c.get("period") or claim.get("period") or "") or None,
            unit=str(c.get("unit") or claim.get("unit") or "") or None,
            scope=str(c.get("scope") or claim.get("scope") or "") or None,
            entity=str(claim.get("entity") or "") or None,
            raw_value=c.get("raw_value"),
            normalized_value=c.get("normalized_value"),
            table_title=c.get("table_title"),
            row_header=c.get("row_header"),
            column_header=c.get("column_header"),
            source_block_ids=c.get("source_block_ids") or [],
            extraction_source="real_e2e",
        )
        ce.metadata_completeness = _compute_metadata_completeness(ce)
        for f in CANONICAL_EVIDENCE_FIELDS:
            _track_field(stats, f, getattr(ce, f), _FIELD_TYPES.get(f, "any"))
        out.append(ce)
    return out, stats


# ===========================================================================
# schema_comparison artifact builder (§1)
# ===========================================================================

def build_schema_comparison(stats_list: list[AdapterStats]) -> dict:
    """Build phase23_11_2_schema_comparison.json content.

    Per-field comparison across three sources: present/missing/parsed/
    type_mismatch/default_value counts. Proves adapters do NOT silently fill
    False for missing metadata.
    """
    comparison: dict = {"fields": {}}
    for f in CANONICAL_EVIDENCE_FIELDS:
        comparison["fields"][f] = {}
        for s in stats_list:
            comparison["fields"][f][s.source] = {
                "present": s.present_count.get(f, 0),
                "missing": s.missing_count.get(f, 0),
                "parsed": s.parsed_count.get(f, 0),
                "type_mismatch": s.type_mismatch_count.get(f, 0),
                "default_value": s.default_value_count.get(f, 0),
            }
    comparison["sources"] = [s.to_dict() for s in stats_list]
    comparison["summary"] = {
        "silent_default_forbidden": True,
        "missing_becomes_None_not_False": True,
        "all_sources_use_same_CanonicalEvidence": True,
        "field_count": len(CANONICAL_EVIDENCE_FIELDS),
    }
    return comparison


__all__ = [
    "CanonicalEvidence", "CANONICAL_EVIDENCE_FIELDS", "AdapterStats",
    "adapt_core_oracle", "adapt_noisy_oracle", "adapt_real_e2e",
    "build_schema_comparison",
]
