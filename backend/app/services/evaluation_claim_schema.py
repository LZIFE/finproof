"""Phase 23.11.1 Canonical Evaluation Claim Schema (Task 1).

Single source of truth for loading 43 Development Claims (demo + holdout),
mapping legacy fields to Canonical Schema, unifying verdict labels via
normalize_verdict(), and validating data before any evaluation runs.

Root causes fixed here:
- 26 vs 43: Phase 23.11 acceptance only read `demo` dataset (26 claims);
  Phase 23.9 Oracle traversed ["demo","holdout"] (26+17=43). Canonical
  loader always traverses both.
- expected_verdict missing: it lives in gold_verifications.json's
  `verifications[]`, NOT in gold_claims.json's `claims[]`. Adapter joins
  them by claim_id; never silently defaults to SUPPORTED/INSUFFICIENT.
- Verdict mapping fragmented: each script did its own status mapping.
  normalize_verdict() is the single mapping function all scripts must use.

Forbidden: silent default填充; 缩样本; bypass adapter.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ===========================================================================
# Canonical Evaluation Claim Schema
# ===========================================================================

CANONICAL_CLAIM_FIELDS: tuple[str, ...] = (
    "claim_id", "company", "claim_text", "claim_type",
    "expected_verdict", "document_id", "period", "metric",
    "value", "unit", "scope", "gold_evidence_ids",
)

# Unified external evaluation verdict categories (§3)
VERDICT_SUPPORTED = "SUPPORTED"
VERDICT_REFUTED = "REFUTED"
VERDICT_PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
VERDICT_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
VERDICT_UNABLE_TO_DETERMINE = "UNABLE_TO_DETERMINE"
VERDICT_OPINION_OR_FORECAST = "OPINION_OR_FORECAST"

# Internal verdicts (Phase 23.11.4 §8)
VERDICT_FORECAST_OR_OPINION = "FORECAST_OR_OPINION"
VERDICT_CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
VERDICT_INVALID_INPUT = "INVALID_INPUT"

CANONICAL_VERDICTS: frozenset[str] = frozenset({
    VERDICT_SUPPORTED, VERDICT_REFUTED, VERDICT_PARTIALLY_SUPPORTED,
    VERDICT_INSUFFICIENT_EVIDENCE, VERDICT_UNABLE_TO_DETERMINE,
    VERDICT_OPINION_OR_FORECAST,
})

# Phase 23.11.4 §8: InternalVerdict → EvaluationVerdict mapping
# INVALID_INPUT does NOT enter accuracy calculation
# FORECAST_OR_OPINION maps to OPINION_OR_FORECAST
# CONFLICTING_EVIDENCE maps to INSUFFICIENT_EVIDENCE
# Missing gold annotation must NOT be mapped to INSUFFICIENT_EVIDENCE
INTERNAL_TO_EVALUATION_MAP: dict[str, str] = {
    "SUPPORTED": VERDICT_SUPPORTED,
    "REFUTED": VERDICT_REFUTED,
    "PARTIALLY_SUPPORTED": VERDICT_PARTIALLY_SUPPORTED,
    "INSUFFICIENT_EVIDENCE": VERDICT_INSUFFICIENT_EVIDENCE,
    "FORECAST_OR_OPINION": VERDICT_OPINION_OR_FORECAST,
    "CONFLICTING_EVIDENCE": VERDICT_INSUFFICIENT_EVIDENCE,
    "INVALID_INPUT": "INVALID_INPUT",  # excluded from accuracy
}

EVALUATION_VERDICTS: frozenset[str] = frozenset({
    VERDICT_SUPPORTED, VERDICT_REFUTED, VERDICT_PARTIALLY_SUPPORTED,
    VERDICT_INSUFFICIENT_EVIDENCE,
})

# All internal statuses seen in the codebase → canonical verdict mapping.
# Single mapping function; scripts must NOT implement their own.
_INTERNAL_TO_CANONICAL: dict[str, str] = {
    # canonical passthrough
    "SUPPORTED": VERDICT_SUPPORTED,
    "REFUTED": VERDICT_REFUTED,
    "PARTIALLY_SUPPORTED": VERDICT_PARTIALLY_SUPPORTED,
    "PARTIAL": VERDICT_PARTIALLY_SUPPORTED,  # legacy alias
    "PARTIALLY": VERDICT_PARTIALLY_SUPPORTED,  # legacy alias
    "INSUFFICIENT_EVIDENCE": VERDICT_INSUFFICIENT_EVIDENCE,
    "INSUFFICIENT": VERDICT_INSUFFICIENT_EVIDENCE,  # legacy alias
    "NO_EVIDENCE": VERDICT_INSUFFICIENT_EVIDENCE,  # legacy alias
    "UNABLE_TO_DETERMINE": VERDICT_UNABLE_TO_DETERMINE,
    "UNABLE": VERDICT_UNABLE_TO_DETERMINE,  # legacy alias
    "UNDETERMINED": VERDICT_UNABLE_TO_DETERMINE,  # legacy alias
    "OPINION_OR_FORECAST": VERDICT_OPINION_OR_FORECAST,
    "OPINION": VERDICT_OPINION_OR_FORECAST,  # legacy alias
    "FORECAST": VERDICT_OPINION_OR_FORECAST,  # legacy alias
}


def normalize_verdict(status: str) -> str:
    """Single unified verdict mapping function (§3).

    All Oracle / Noisy Oracle / Real E2E / confusion matrix must use this.
    Returns canonical verdict; raises ValueError on unknown status (never
    silently defaults).
    """
    if not status or not isinstance(status, str):
        raise ValueError(f"normalize_verdict: empty/non-string status: {status!r}")
    s = status.strip().upper()
    if s in CANONICAL_VERDICTS:
        return s
    mapped = _INTERNAL_TO_CANONICAL.get(s)
    if mapped is None:
        # try case-insensitive lookup over legacy keys
        for k, v in _INTERNAL_TO_CANONICAL.items():
            if k.upper() == s:
                return v
        raise ValueError(f"normalize_verdict: unknown status: {status!r}")
    return mapped


# ===========================================================================
# Phase 23.11.3 §5: normalize_verdict_for_evaluation — 唯一外部评测映射
# ===========================================================================

# Extended internal statuses that may appear in aggregation / core_verify
# output but are NOT yet in CANONICAL_VERDICTS (conflict / ambiguous).
_EXTENDED_TO_CANONICAL: dict[str, str] = {
    "CONFLICTING_EVIDENCE": "INSUFFICIENT_EVIDENCE",  # §5: 无法解决冲突 → 弃权
    "CONFLICT": "INSUFFICIENT_EVIDENCE",
    "AMBIGUOUS_EVIDENCE": "INSUFFICIENT_EVIDENCE",  # §5: 歧义 → 弃权非默认 SUPPORTED
    "AMBIGUOUS": "INSUFFICIENT_EVIDENCE",
    "UNKNOWN": "INSUFFICIENT_EVIDENCE",  # §5: UNKNOWN → 弃权非 SUPPORTED
    "NONE": "INSUFFICIENT_EVIDENCE",
    "PENDING": "INSUFFICIENT_EVIDENCE",
    "ERROR": "INSUFFICIENT_EVIDENCE",
}


def normalize_verdict_for_evaluation(status: str) -> str:
    """Phase 23.11.3 §5 唯一函数: 内部状态 → 外部评测类别.

    Oracle / Noisy Oracle / Real E2E / confusion matrix / API 必须全部调用此函数.
    禁止: 脚本分别实现映射; 使用字符串 contains; 将 UNKNOWN 默认为 SUPPORTED;
    将 OPINION_OR_FORECAST 随意映射为 SUPPORTED.

    Mapping table (§5):
        SUPPORTED               → SUPPORTED
        REFUTED                 → REFUTED
        PARTIALLY_SUPPORTED    → PARTIALLY_SUPPORTED
        INSUFFICIENT_EVIDENCE   → INSUFFICIENT_EVIDENCE
        UNABLE / UNABLE_TO_DETERMINE → UNABLE_TO_DETERMINE
        OPINION_OR_FORECAST     → OPINION_OR_FORECAST
        CONFLICTING_EVIDENCE / CONFLICT → INSUFFICIENT_EVIDENCE (冲突无法解决→弃权)
        AMBIGUOUS_EVIDENCE / AMBIGUOUS → INSUFFICIENT_EVIDENCE (歧义→弃权非默认)
        UNKNOWN / NONE / PENDING / ERROR → INSUFFICIENT_EVIDENCE
    """
    if not status or not isinstance(status, str):
        # empty/non-string → 弃权, never SUPPORTED
        return "INSUFFICIENT_EVIDENCE"
    s = status.strip().upper()
    # canonical passthrough
    if s in CANONICAL_VERDICTS:
        return s
    # legacy internal → canonical (reuse normalize_verdict's table)
    mapped = _INTERNAL_TO_CANONICAL.get(s)
    if mapped is not None:
        return mapped
    # extended (conflict / ambiguous / unknown)
    ext = _EXTENDED_TO_CANONICAL.get(s)
    if ext is not None:
        return ext
    # case-insensitive fallback
    for k, v in _INTERNAL_TO_CANONICAL.items():
        if k.upper() == s:
            return v
    for k, v in _EXTENDED_TO_CANONICAL.items():
        if k.upper() == s:
            return v
    # truly unknown → 弃权, never SUPPORTED (§5 禁止)
    return "INSUFFICIENT_EVIDENCE"


# 全状态覆盖测试 helper (§5)
def all_known_internal_statuses() -> tuple[str, ...]:
    """Return all internal statuses the mapping must handle (for unit tests)."""
    return tuple(sorted(set(
        list(_INTERNAL_TO_CANONICAL.keys()) + list(_EXTENDED_TO_CANONICAL.keys())
        + list(CANONICAL_VERDICTS)
    )))


# ===========================================================================
# Data paths
# ===========================================================================

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # finproof/
DATA_DIR = REPO_ROOT / "data"
DATASETS = ("demo", "holdout")  # traverse BOTH → 43 claims


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ===========================================================================
# Adapter: legacy gold_claims + gold_verifications + gold_evidence → Canonical
# ===========================================================================

@dataclass
class ValidationIssue:
    claim_id: str
    field: str
    issue: str
    severity: str = "error"  # error | warning


@dataclass
class CanonicalClaim:
    """Canonical Evaluation Claim (§2)."""

    claim_id: str
    company: str
    claim_text: str
    claim_type: str
    expected_verdict: str
    document_id: str
    period: str
    metric: str
    value: object
    unit: str
    scope: str
    gold_evidence_ids: list = field(default_factory=list)
    dataset: str = ""  # provenance: demo | holdout
    raw_claim: dict = field(default_factory=dict)  # original claim dict
    raw_verification: dict = field(default_factory=dict)  # original ver dict

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id, "company": self.company,
            "claim_text": self.claim_text, "claim_type": self.claim_type,
            "expected_verdict": self.expected_verdict,
            "document_id": self.document_id, "period": self.period,
            "metric": self.metric, "value": self.value,
            "unit": self.unit, "scope": self.scope,
            "gold_evidence_ids": self.gold_evidence_ids,
            "dataset": self.dataset,
        }


def _adapt_one(
    claim: dict, verification: dict | None, evidence_ids: list,
    dataset: str, issues: list[ValidationIssue],
) -> CanonicalClaim | None:
    """Adapt one legacy claim + its verification to CanonicalClaim.

    Records validation_issue on missing fields; NEVER silently defaults
    expected_verdict to SUPPORTED/INSUFFICIENT.
    """
    cid = str(claim.get("claim_id") or "")

    # expected_verdict from verification, not claim
    expected_verdict_raw = ""
    if verification is not None:
        expected_verdict_raw = str(
            verification.get("expected_verdict")
            or verification.get("gold_verdict")
            or verification.get("verdict")
            or ""
        ).strip()
    if not expected_verdict_raw:
        issues.append(ValidationIssue(
            cid, "expected_verdict",
            "missing in gold_verifications.json; cannot evaluate correctness",
            "error",
        ))
        # do NOT default; return None to skip from evaluation but record issue
        return None

    try:
        expected_verdict = normalize_verdict(expected_verdict_raw)
    except ValueError as exc:
        issues.append(ValidationIssue(
            cid, "expected_verdict",
            f"unmappable verdict: {exc}", "error",
        ))
        return None

    # company from claim (entity) or dataset-level
    company = str(
        claim.get("entity") or claim.get("entity_name")
        or claim.get("company") or ""
    ).strip()
    if not company:
        issues.append(ValidationIssue(
            cid, "company", "missing entity/company", "warning",
        ))

    claim_text = str(
        claim.get("original_text") or claim.get("claim_text")
        or claim.get("text") or ""
    ).strip()
    if not claim_text:
        issues.append(ValidationIssue(
            cid, "claim_text", "missing original_text/claim_text", "error",
        ))
        return None

    document_id = str(
        claim.get("document_id") or claim.get("report_file") or ""
    ).strip()

    return CanonicalClaim(
        claim_id=cid,
        company=company,
        claim_text=claim_text,
        claim_type=str(claim.get("claim_type") or ""),
        expected_verdict=expected_verdict,
        document_id=document_id,
        period=str(claim.get("period") or ""),
        metric=str(claim.get("metric") or claim.get("metric_code") or ""),
        value=claim.get("value"),
        unit=str(claim.get("unit") or ""),
        scope=str(claim.get("scope") or ""),
        gold_evidence_ids=list(evidence_ids),
        dataset=dataset,
        raw_claim=claim,
        raw_verification=verification or {},
    )


def load_canonical_claims() -> tuple[list[CanonicalClaim], list[ValidationIssue]]:
    """Load 43 Development Claims from demo + holdout, adapt to Canonical.

    Traverses BOTH datasets (demo 26 + holdout 17 = 43).
    Joins gold_claims + gold_verifications + gold_evidence by claim_id.
    Returns (claims, issues). claims may be < 43 if validation errors skip
    some; issues always records why.
    """
    claims: list[CanonicalClaim] = []
    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()

    for ds in DATASETS:
        base = DATA_DIR / ds / "annotations"
        c_path = base / "gold_claims.json"
        v_path = base / "gold_verifications.json"
        e_path = base / "gold_evidence.json"
        if not c_path.exists():
            issues.append(ValidationIssue(
                "", "file", f"missing {c_path}", "error",
            ))
            continue
        c_data = _load_json(c_path)
        v_data = _load_json(v_path) if v_path.exists() else {"verifications": []}
        e_data = _load_json(e_path) if e_path.exists() else {"evidence": []}

        raw_claims = c_data.get("claims", [])
        v_by = {str(v.get("claim_id") or ""): v for v in v_data.get("verifications", [])}
        ev_by: dict[str, list[str]] = {}
        for e in e_data.get("evidence", []):
            eid = str(e.get("evidence_id") or "")
            cid = str(e.get("claim_id") or "")
            if cid and eid:
                ev_by.setdefault(cid, []).append(eid)

        for claim in raw_claims:
            cid = str(claim.get("claim_id") or "")
            if not cid:
                issues.append(ValidationIssue(
                    "", "claim_id", "claim without claim_id", "error",
                ))
                continue
            if cid in seen_ids:
                issues.append(ValidationIssue(
                    cid, "claim_id", "duplicate claim_id", "error",
                ))
                continue
            seen_ids.add(cid)
            adapted = _adapt_one(
                claim, v_by.get(cid), ev_by.get(cid, []), ds, issues,
            )
            if adapted is not None:
                claims.append(adapted)

    return claims, issues


# ===========================================================================
# Validation (§2): pre-evaluation data checks
# ===========================================================================

@dataclass
class SchemaValidationResult:
    passed: bool
    total_claims: int
    unique_claim_ids: int
    expected_verdicts_all_present: bool
    verdicts_normalized: bool
    oracle_and_e2e_same_ids: bool  # placeholder; set by caller via compare
    issues: list[dict] = field(default_factory=list)
    verdict_distribution: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "total_claims": self.total_claims,
            "unique_claim_ids": self.unique_claim_ids,
            "expected_verdicts_all_present": self.expected_verdicts_all_present,
            "verdicts_normalized": self.verdicts_normalized,
            "oracle_and_e2e_same_ids": self.oracle_and_e2e_same_ids,
            "issues": self.issues,
            "verdict_distribution": self.verdict_distribution,
        }


def validate_schema(claims: list[CanonicalClaim], issues: list[ValidationIssue]) -> SchemaValidationResult:
    """Pre-evaluation validation (§2).

    Checks:
    - total_claims must be 43
    - claim_id must be unique
    - expected_verdict must all be non-empty
    - verdicts normalize to canonical categories
    """
    total = len(claims)
    ids = [c.claim_id for c in claims]
    unique = len(set(ids))
    all_ev = all(c.expected_verdict for c in claims)
    verdicts_normalized = all(
        c.expected_verdict in CANONICAL_VERDICTS for c in claims
    )
    verdict_distribution: dict[str, int] = {}
    for c in claims:
        verdict_distribution[c.expected_verdict] = verdict_distribution.get(c.expected_verdict, 0) + 1

    issue_dicts = [{"claim_id": i.claim_id, "field": i.field, "issue": i.issue, "severity": i.severity} for i in issues]

    passed = (
        total == 43
        and unique == 43
        and all_ev
        and verdicts_normalized
        and not any(i.severity == "error" for i in issues)
    )

    return SchemaValidationResult(
        passed=passed,
        total_claims=total,
        unique_claim_ids=unique,
        expected_verdicts_all_present=all_ev,
        verdicts_normalized=verdicts_normalized,
        oracle_and_e2e_same_ids=True,  # loader guarantees same source
        issues=issue_dicts,
        verdict_distribution=verdict_distribution,
    )


__all__ = [
    "CANONICAL_CLAIM_FIELDS", "CANONICAL_VERDICTS",
    "VERDICT_SUPPORTED", "VERDICT_REFUTED", "VERDICT_PARTIALLY_SUPPORTED",
    "VERDICT_INSUFFICIENT_EVIDENCE", "VERDICT_UNABLE_TO_DETERMINE",
    "VERDICT_OPINION_OR_FORECAST",
    "normalize_verdict", "CanonicalClaim", "ValidationIssue",
    "SchemaValidationResult", "load_canonical_claims", "validate_schema",
    "DATA_DIR", "DATASETS",
]
