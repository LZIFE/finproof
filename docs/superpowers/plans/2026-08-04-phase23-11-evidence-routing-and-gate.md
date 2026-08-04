# Phase 23.11 Evidence Routing, Precision Gate & Real E2E Recovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the frozen Oracle `core_verify` with a routed production main chain (Claim Router → dual-channel retrieval → Evidence Gate → Evidence Selector → `core_verify`), recover Phase 23.9→23.10 regressions, and lift Real E2E Accuracy ≥ 0.70.

**Architecture:** Single canonical entry `verify_evidence_set(claim, candidates, routing, ctx)` runs `Evidence Gate → Evidence Selector → core_verify`. CORE_ORACLE / NOISY_ORACLE / REAL_E2E all call it; they differ only in Evidence source. Old `verify_claim` becomes a thin adapter. Oracle 1.0 protected because the gate/selector path is shared, not bypassed.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0, pytest, FastAPI. Existing patterns: `app/services/<domain>/` modules, `app/models/<domain>.py` ORM, `dataclass` result types, `IntegrationTrace` audit trail.

## Global Constraints

- Oracle and Real E2E share the same `verify_evidence_set`, `EvidenceGate`, `EvidenceSelector`, `core_verify`, Verdict mapping, `VerificationResult`, Trace and Audit fields. They differ only in Evidence source.
- Gold Evidence must pass through Gate and Selector. If Gold is rejected by Gate, record `GATE_REJECTED_GOLD`; do NOT bypass to protect Oracle 1.0.
- Old `verify_claim` is a thin adapter only — no independent Verdict logic, no bypass of Gate/Selector, must ultimately call `verify_evidence_set`.
- Claim Router and Evidence Gate are pure functions (no DB, no I/O, no side effects).
- `FinancialFact` table stores ONLY structured facts. Forbidden fields: `gold_page`, `gold_block_id`, `expected_verdict`, `claim_id`-specific weights, is-correct-answer labels, dev-set labels.
- Production main chain: real API, Demo, Real E2E all call `verify_claim_production()`. Demo/API/E2E must NOT use different entry points.
- Tunable parameters (Gate thresholds, quality margin, channel weights, Top1/Top3, ambiguity threshold) are tuned ONLY via two-fold leave-one-company-out cross-validation (五粮液 ↔ 美的集团). No claim-specific params, no company-specific params, no Gold Page features, no block_id features, no repeated tuning on the validation set.
- Each fold must persist frozen parameters and first-validation results.
- Error classification is mutually exclusive: each error has exactly one `primary_root_cause` and optional `secondary_causes`. Never collapse all errors to `retrieval_failure`.
- Baseline commit: 3dada2c. Phase 23.10 must NOT be marked READY.

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `backend/app/models/financial_fact.py` | ORM `FinancialFact` table (structured fact store, Channel A source) |
| `backend/app/services/claim_router.py` | Pure router: claim dict → `ClaimRoutingResult` (8 routes) |
| `backend/app/services/financial_fact_index.py` | Build/query `FinancialFact` from `DocumentBlock` + `TableContext` |
| `backend/app/services/evidence_gate.py` | Pure gate: candidate + routing → `EvidenceQualityResult` |
| `backend/app/services/evidence_selector.py` | Pure selector: dedup + Top1/Top3/Top5 + ambiguity margin |
| `backend/app/services/verification_context.py` | `VerificationContext` dataclass (carries configs + trace) |
| `backend/scripts/phase23_11_acceptance.py` | Full acceptance: 5 strategies × 43 claims, all metrics |
| `backend/scripts/phase23_11_regression_diff.py` | Phase 23.9 vs 23.10 per-claim diff |
| `backend/scripts/phase23_11_evidence_gate_eval.py` | Gate precision/recall/accepted_noise_rate on labeled set |
| `backend/scripts/phase23_11_leave_one_company_out.py` | 2-fold leave-one-company-out tuning |
| `backend/tests/test_phase23_11_claim_router.py` | Router tests |
| `backend/tests/test_phase23_11_fact_index.py` | Fact index build/query tests |
| `backend/tests/test_phase23_11_evidence_gate.py` | Gate tests (incl. wrong-period, wrong-scope, causal) |
| `backend/tests/test_phase23_11_evidence_selector.py` | Selector tests (incl. ambiguity margin) |
| `backend/tests/test_phase23_11_regression_recovery.py` | Phase 23.10 regression recovery tests |
| `backend/tests/test_phase23_11_integration.py` | Real API → router → retrieval → gate → selector → core_verify |
| `backend/artifacts/phase23_11_acceptance.json` | Acceptance results |
| `backend/artifacts/e2e/phase23_11_regression_diff.json` | Regression diff |
| `backend/artifacts/e2e/phase23_11_development_e2e.json` | Real E2E results |
| `backend/artifacts/retrieval/phase23_11_structured_metrics.json` | Channel A metrics |
| `backend/artifacts/retrieval/phase23_11_narrative_metrics.json` | Channel B metrics |
| `backend/artifacts/evidence_gate/phase23_11_gate_metrics.json` | Gate metrics |
| `backend/artifacts/cross_validation/phase23_11_leave_one_company_out.json` | CV tuning results |
| `docs/phase23_11_evidence_routing_and_gate.md` | Phase 23.11 results document |

### Modified files

| File | Change |
|---|---|
| `backend/app/services/verification/verification_service.py` | Add `verify_evidence_set`, `verify_core_oracle`, `verify_noisy_oracle`, `verify_real_e2e`, `verify_claim_production`. Convert `verify_claim` to thin adapter. |
| `backend/app/models/__init__.py` | Register `FinancialFact` |
| `backend/app/services/evidence_retrieval/service.py` | Add `retrieve_via_channels` dispatch hook |
| `docs/phase23_10_table_aware_retrieval.md` | Note Phase 23.11 regression recovery |
| `docs/finproof_progress.md` | Phase 23.11 status |
| `README.md` | Phase 23.11 summary |

---

## Task 1: FinancialFact model + registration

**Files:**
- Create: `backend/app/models/financial_fact.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_phase23_11_fact_index.py` (created here, extended Task 4)

**Interfaces:**
- Produces: `FinancialFact` ORM class with fields `id, fact_id, company, document_id, document_type, page, table_id, section_title, table_title, row_header, parent_row_header, column_header, period_header, metric, metric_canonical, period, period_type, unit, currency, scope, raw_value, normalized_value, source_block_ids (JSON), neighboring_context (JSON), created_at`.

- [ ] **Step 1: Write the model file**

```python
# backend/app/models/financial_fact.py
"""Structured financial fact store (Phase 23.11 Channel A source).

Stores ONLY structured facts extracted from DocumentBlock + TableContext.
Forbidden fields: gold_page, gold_block_id, expected_verdict,
claim_id-specific weights, is-correct-answer labels, dev-set labels.
"""
from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class FinancialFact(Base):
    __tablename__ = "financial_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    company: Mapped[str] = mapped_column(String(128), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(32), default="annual_report")
    page: Mapped[int] = mapped_column(Integer, index=True)
    table_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    section_title: Mapped[str] = mapped_column(String(256), default="")
    table_title: Mapped[str] = mapped_column(String(256), default="")
    row_header: Mapped[str] = mapped_column(String(256), index=True, default="")
    parent_row_header: Mapped[str] = mapped_column(String(256), default="")
    column_header: Mapped[str] = mapped_column(String(256), default="")
    period_header: Mapped[str] = mapped_column(String(128), default="")
    metric: Mapped[str] = mapped_column(String(128), index=True, default="")
    metric_canonical: Mapped[str] = mapped_column(String(64), index=True, default="")
    period: Mapped[str] = mapped_column(String(32), index=True, default="")
    period_type: Mapped[str] = mapped_column(String(16), default="")
    unit: Mapped[str] = mapped_column(String(16), index=True, default="")
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    scope: Mapped[str] = mapped_column(String(32), index=True, default="")
    raw_value: Mapped[str] = mapped_column(String(64), default="")
    normalized_value: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    source_block_ids: Mapped[list] = mapped_column(JSON, default=list)
    neighboring_context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def ensure_financial_fact_table(session) -> None:
    """Create financial_facts table if not exists (idempotent)."""
    from sqlalchemy import inspect
    inspector = inspect(session.bind)
    if "financial_facts" not in inspector.get_table_names():
        FinancialFact.__table__.create(session.bind, checkfirst=True)
```

- [ ] **Step 2: Register in models/__init__.py**

Add after the `evidence` import line:

```python
from app.models.financial_fact import FinancialFact  # noqa: F401
```

- [ ] **Step 3: Run a smoke test to verify table creation**

Run: `cd backend && python -c "from app.db import SessionLocal; from app.models.financial_fact import FinancialFact, ensure_financial_fact_table; s=SessionLocal(); ensure_financial_fact_table(s); print('OK', s.query(FinancialFact).count())"`

Expected: `OK 0`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/financial_fact.py backend/app/models/__init__.py
git commit -m "feat(phase23.11): add FinancialFact ORM model for structured fact index"
```

---

## Task 2: ClaimRouter (pure function, 8 routes)

**Files:**
- Create: `backend/app/services/claim_router.py`
- Test: `backend/tests/test_phase23_11_claim_router.py`

**Interfaces:**
- Consumes: `claim` dict with fields `claim_id/claim_uid, entity/entity_name, metric, metric_code, claim_type, period, unit, scope, value, original_text/source_text`.
- Produces: `route_claim(claim: dict) -> ClaimRoutingResult`. `ClaimRoutingResult` dataclass with fields: `claim_id, claim_type, entity, metric, metric_code, value, period, unit, scope, direction, route, route_confidence, required_evidence_fields`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_phase23_11_claim_router.py
from app.services.claim_router import route_claim, ClaimRoutingResult


def test_structured_numeric_route():
    claim = {"claim_id": "CLM-001", "entity": "五粮液", "metric": "营业收入",
             "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "value": 931.8, "original_text": "五粮液2025年营业收入931.8亿元"}
    r = route_claim(claim)
    assert isinstance(r, ClaimRoutingResult)
    assert r.entity == "五粮液"
    assert r.route_confidence >= 0.7
    assert "metric" in r.required_evidence_fields or "value" in r.required_evidence_fields


def test_period_comparison_route():
    claim = {"claim_id": "CLM-002", "metric_code": "revenue_growth",
             "claim_type": "GROWTH_RATE", "period": "2025FY",
             "original_text": "2025年营业收入同比增长12%"}
    r = route_claim(claim)
    assert r.route == "PERIOD_COMPARISON"


def test_causality_route():
    claim = {"claim_id": "CLM-003", "claim_type": "BUSINESS_FACT",
             "original_text": "毛利率下降主要由于原材料成本上升"}
    r = route_claim(claim)
    assert r.route == "CAUSALITY"
    assert "causal_language" in r.required_evidence_fields


def test_forecast_route():
    claim = {"claim_id": "CLM-004", "claim_type": "BUSINESS_FACT",
             "original_text": "公司预计2026年营收将增长15%"}
    r = route_claim(claim)
    assert r.route == "FORECAST"


def test_narrative_fact_route():
    claim = {"claim_id": "CLM-005", "claim_type": "BUSINESS_FACT",
             "metric_code": "overseas_obm_strategy",
             "original_text": "公司持续推进海外OBM战略"}
    r = route_claim(claim)
    assert r.route == "NARRATIVE_FACT"


def test_scope_validation_route():
    claim = {"claim_id": "CLM-006", "claim_type": "NUMERIC_VALUE",
             "scope": "parent_attributable", "metric_code": "net_profit",
             "period": "2025FY", "unit": "亿元", "value": 317.9,
             "original_text": "归母净利润317.9亿元"}
    r = route_claim(claim)
    assert r.route == "SCOPE_VALIDATION"


def test_insufficiently_parsed_route():
    claim = {"claim_id": "CLM-008", "claim_type": "",
             "original_text": "公司表现良好"}
    r = route_claim(claim)
    assert r.route == "INSUFFICIENTLY_PARSED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_phase23_11_claim_router.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.claim_router'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/claim_router.py
"""Phase 23.11 Claim Router (pure function).

Routes claims to one of 8 evidence retrieval paths:
STRUCTURED_NUMERIC | TABLE_METRIC | PERIOD_COMPARISON | SCOPE_VALIDATION
| NARRATIVE_FACT | CAUSALITY | FORECAST | INSUFFICIENTLY_PARSED

Pure: no DB, no I/O, no side effects.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Literal

RouteType = Literal[
    "STRUCTURED_NUMERIC", "TABLE_METRIC", "PERIOD_COMPARISON",
    "SCOPE_VALIDATION", "NARRATIVE_FACT", "CAUSALITY", "FORECAST",
    "INSUFFICIENTLY_PARSED",
]

CAUSAL_MARKERS = ("导致", "推动", "主要由于", "主要系", "得益于", "带动",
                  "attributable to", "driven by", "resulted from")
FORECAST_MARKERS = ("预计", "指引", "目标", "管理层判断", "计划",
                    "forecast", "guidance", "expect", "aim")
PERIOD_COMPARISON_MARKERS = ("同比", "环比", "较上年", "较去年同期", "上年同期")
SCOPE_MARKERS = ("归母", "归属于上市公司股东", "扣非", "扣除非经常性损益",
                 "少数股东", "合并")

STRUCTURED_METRIC_CODES = frozenset({
    "revenue", "net_profit", "operating_cash_flow", "eps", "gross_margin",
    "net_margin", "total_assets", "net_assets", "roe", "roa", "debt_ratio",
})
TABLE_METRIC_CODES = frozenset({
    "eps", "bps", "gross_margin", "net_margin", "roe", "roa", "debt_ratio",
})


@dataclass
class ClaimRoutingResult:
    claim_id: str
    claim_type: str
    entity: str
    metric: str
    metric_code: str
    value: float | None
    period: str
    unit: str
    scope: str
    direction: str
    route: RouteType
    route_confidence: float
    required_evidence_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id, "claim_type": self.claim_type,
            "entity": self.entity, "metric": self.metric,
            "metric_code": self.metric_code, "value": self.value,
            "period": self.period, "unit": self.unit, "scope": self.scope,
            "direction": self.direction, "route": self.route,
            "route_confidence": round(self.route_confidence, 3),
            "required_evidence_fields": self.required_evidence_fields,
        }


def _direction_of(text: str) -> str:
    if any(k in text for k in ("超过", "高于", "大于", "突破", "以上")):
        return ">="
    if any(k in text for k in ("低于", "小于", "以下", "不超过")):
        return "<="
    return "=="


def route_claim(claim: dict) -> ClaimRoutingResult:
    """Pure routing: claim dict -> ClaimRoutingResult (8 routes)."""
    cid = str(claim.get("claim_id") or claim.get("claim_uid") or "?")
    claim_type = str(claim.get("claim_type") or "").upper()
    entity = str(claim.get("entity") or claim.get("entity_name") or "").strip()
    metric = str(claim.get("metric") or "").strip()
    metric_code = str(claim.get("metric_code") or metric or "").strip()
    period = str(claim.get("period") or "").strip()
    unit = str(claim.get("unit") or "").strip()
    scope = str(claim.get("scope") or "consolidated").strip()
    value = claim.get("value") if isinstance(claim.get("value"), (int, float)) else None
    text = str(claim.get("original_text") or claim.get("source_text") or "").strip()
    direction = _direction_of(text)

    # CAUSALITY: causal language present
    has_causal = any(m in text for m in CAUSAL_MARKERS)
    if has_causal:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "CAUSALITY", 0.85,
            ["causal_language", "metric", "entity"],
        )

    # FORECAST: forecast language present
    has_forecast = any(m in text for m in FORECAST_MARKERS)
    if has_forecast:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "FORECAST", 0.85,
            ["forecast_marker", "metric", "period"],
        )

    # PERIOD_COMPARISON: comparison markers or growth_rate claim
    has_comparison = any(m in text for m in PERIOD_COMPARISON_MARKERS)
    is_growth = claim_type in ("GROWTH_RATE", "GROWTH_RATE_CHECK")
    if has_comparison or is_growth:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "PERIOD_COMPARISON", 0.8,
            ["current_period", "comparison_period", "metric", "unit"],
        )

    # SCOPE_VALIDATION: scope markers present or non-default scope
    has_scope = any(m in text for m in SCOPE_MARKERS)
    if has_scope or scope in ("parent_attributable", "adjusted",
                              "non_controlling_interest"):
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "SCOPE_VALIDATION", 0.8,
            ["scope", "metric", "period", "unit"],
        )

    # TABLE_METRIC: metric prefers table cell extraction
    if metric_code in TABLE_METRIC_CODES:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "TABLE_METRIC", 0.8,
            ["row_header", "column_header", "period_header", "unit_header",
             "cell_value"],
        )

    # STRUCTURED_NUMERIC: structured metric codes with numeric value
    if metric_code in STRUCTURED_METRIC_CODES and value is not None:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "STRUCTURED_NUMERIC", 0.85,
            ["metric", "value", "period", "unit", "scope"],
        )

    # NARRATIVE_FACT: business fact / strategy without structured metric
    if claim_type in ("BUSINESS_FACT", "STRATEGY", "SEMANTIC_CHECK"):
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "NARRATIVE_FACT", 0.75,
            ["entity", "keywords", "section"],
        )

    # Fallback: STRUCTURED_NUMERIC if numeric value present
    if value is not None and metric_code:
        return ClaimRoutingResult(
            cid, claim_type, entity, metric, metric_code, value, period, unit,
            scope, direction, "STRUCTURED_NUMERIC", 0.6,
            ["metric", "value", "period", "unit"],
        )

    # INSUFFICIENTLY_PARSED: nothing matched
    return ClaimRoutingResult(
        cid, claim_type, entity, metric, metric_code, value, period, unit,
        scope, direction, "INSUFFICIENTLY_PARSED", 0.3,
        ["entity", "keywords"],
    )


__all__ = ["route_claim", "ClaimRoutingResult", "RouteType"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_phase23_11_claim_router.py -v`

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/claim_router.py backend/tests/test_phase23_11_claim_router.py
git commit -m "feat(phase23.11): add pure-function ClaimRouter with 8 route types"
```

---

## Task 3: EvidenceGate (pure function, per-route thresholds)

**Files:**
- Create: `backend/app/services/evidence_gate.py`
- Test: `backend/tests/test_phase23_11_evidence_gate.py`

**Interfaces:**
- Consumes: `claim: dict`, `candidate: dict` (with `text/evidence_id/block_id/page/document_id`), `routing: ClaimRoutingResult`, `gate_config: GateConfig`.
- Produces: `evaluate_one(...) -> EvidenceQualityResult`; `evaluate_all(...) -> list[EvidenceQualityResult]`. `EvidenceQualityResult` dataclass with fields: `evidence_id, entity_match, metric_match, period_match, unit_match, scope_match, numeric_match, source_quality, route_match, contradiction_signal, completeness_score, final_quality_score, accepted, rejection_reason`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_phase23_11_evidence_gate.py
from app.services.claim_router import route_claim
from app.services.evidence_gate import (
    evaluate_one, evaluate_all, GateConfig, EvidenceQualityResult,
)


def test_numeric_gate_accepts_correct_evidence():
    claim = {"claim_id": "CLM-001", "entity": "五粮液", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY", "unit": "亿元",
             "scope": "consolidated", "value": 931.8,
             "original_text": "五粮液2025年营业收入931.8亿元"}
    routing = route_claim(claim)
    candidate = {"evidence_id": "B1", "text": "营业收入 931.8 亿元 2025年",
                 "page": 5, "document_id": 1}
    cfg = GateConfig()
    r = evaluate_one(claim, candidate, routing, cfg)
    assert isinstance(r, EvidenceQualityResult)
    assert r.accepted is True
    assert r.final_quality_score >= cfg.medium_quality_threshold


def test_gate_rejects_wrong_period():
    claim = {"claim_id": "CLM-002", "entity": "五粮液", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY", "unit": "亿元",
             "scope": "consolidated", "value": 931.8,
             "original_text": "2025年营收931.8亿"}
    routing = route_claim(claim)
    candidate = {"evidence_id": "B2", "text": "营业收入 800 亿元 2023年",
                 "page": 5, "document_id": 1}
    cfg = GateConfig()
    r = evaluate_one(claim, candidate, routing, cfg)
    assert r.accepted is False
    assert "period" in r.rejection_reason.lower() or r.period_match == 0.0


def test_gate_rejects_wrong_scope():
    claim = {"claim_id": "CLM-003", "entity": "五粮液", "metric_code": "net_profit",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY", "unit": "亿元",
             "scope": "parent_attributable", "value": 317.9,
             "original_text": "归母净利润317.9亿元"}
    routing = route_claim(claim)
    candidate = {"evidence_id": "B3", "text": "少数股东损益 50 万元",
                 "page": 10, "document_id": 1}
    cfg = GateConfig()
    r = evaluate_one(claim, candidate, routing, cfg)
    assert r.accepted is False


def test_causal_gate_requires_causal_language():
    claim = {"claim_id": "CLM-004", "claim_type": "BUSINESS_FACT",
             "original_text": "毛利率下降主要由于原材料成本上升"}
    routing = route_claim(claim)
    candidate_no_causal = {"evidence_id": "B4", "text": "毛利率30% 营收100亿",
                           "page": 5, "document_id": 1}
    cfg = GateConfig()
    r = evaluate_one(claim, candidate_no_causal, routing, cfg)
    assert r.accepted is False
    assert "causal" in r.rejection_reason.lower()


def test_causal_gate_accepts_causal_language():
    claim = {"claim_id": "CLM-005", "claim_type": "BUSINESS_FACT",
             "original_text": "毛利率下降主要由于原材料成本上升"}
    routing = route_claim(claim)
    candidate_causal = {"evidence_id": "B5",
                        "text": "毛利率下降主要由于原材料成本上升",
                        "page": 5, "document_id": 1}
    cfg = GateConfig()
    r = evaluate_one(claim, candidate_causal, routing, cfg)
    assert r.accepted is True


def test_evaluate_all_returns_list():
    claim = {"claim_id": "CLM-006", "entity": "美的", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY", "unit": "亿元",
             "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    candidates = [
        {"evidence_id": "B1", "text": "营业收入 100 亿元", "page": 1, "document_id": 1},
        {"evidence_id": "B2", "text": "无关文本", "page": 2, "document_id": 1},
    ]
    cfg = GateConfig()
    results = evaluate_all(claim, candidates, routing, cfg)
    assert isinstance(results, list)
    assert len(results) == 2
    assert all(isinstance(r, EvidenceQualityResult) for r in results)


def test_gate_rejects_pure_coincidence_two_facts():
    """CAUSALITY gate rejects evidence with two facts but no causal language."""
    claim = {"claim_id": "CLM-007", "claim_type": "BUSINESS_FACT",
             "original_text": "毛利率下降主要由于原材料成本上升"}
    routing = route_claim(claim)
    candidate = {"evidence_id": "B6",
                 "text": "毛利率30% 原材料成本50亿元",  # two facts, no causal
                 "page": 5, "document_id": 1}
    cfg = GateConfig()
    r = evaluate_one(claim, candidate, routing, cfg)
    assert r.accepted is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_phase23_11_evidence_gate.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/evidence_gate.py
"""Phase 23.11 Evidence Precision Gate (pure function).

Per-route thresholds. CAUSALITY requires explicit causal language;
FORECAST requires forecast markers; numeric routes require
entity+metric+period+scope+unit consistency. Pure: no DB, no I/O.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from app.services.claim_router import (
    ClaimRoutingResult, CAUSAL_MARKERS, FORECAST_MARKERS,
)


@dataclass
class GateConfig:
    metric_match_threshold: float = 0.6
    period_conflict_strict: bool = True
    scope_conflict_strict: bool = True
    unit_convertible: bool = True
    high_quality_threshold: float = 0.7
    medium_quality_threshold: float = 0.4
    route_match_weight: float = 0.2
    causal_language_required: bool = True


@dataclass
class EvidenceQualityResult:
    evidence_id: str
    entity_match: bool
    metric_match: float
    period_match: float
    unit_match: float
    scope_match: float
    numeric_match: float
    source_quality: float
    route_match: float
    contradiction_signal: float
    completeness_score: float
    final_quality_score: float
    accepted: bool
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


def _entity_match(claim: dict, candidate: dict) -> bool:
    entity = str(claim.get("entity") or claim.get("entity_name") or "").strip()
    if not entity:
        return True
    text = candidate.get("text", "") or ""
    if entity in text:
        return True
    # Short-form check (first 2 chars)
    if len(entity) >= 2 and entity[:2] in text:
        return True
    return False


def _metric_match(claim: dict, candidate: dict) -> float:
    from app.services.evidence_retrieval.engine import metric_aliases, metric_hits
    aliases = metric_aliases(claim.get("metric_code"), claim.get("metric"))
    if not aliases:
        return 0.3  # unknown metric, partial credit
    text = candidate.get("text", "") or ""
    hits = metric_hits(text, aliases)
    if hits:
        return 1.0
    for a in aliases:
        if a and a in text:
            return 0.8
    return 0.0


def _period_match(claim: dict, candidate: dict) -> float:
    claim_period = str(claim.get("period") or "").upper()
    text = candidate.get("text", "") or ""
    if not claim_period:
        return 0.5
    year_match = re.search(r"(20\d{2})", claim_period)
    if not year_match:
        return 0.5
    claim_year = year_match.group(1)
    candidate_years = set(re.findall(r"20\d{2}", text))
    if claim_year in candidate_years:
        return 1.0
    if candidate_years:
        return 0.0  # Different year → conflict
    return 0.3  # no year info


def _scope_match(claim: dict, candidate: dict) -> float:
    scope = str(claim.get("scope") or "consolidated").strip()
    text = candidate.get("text", "") or ""
    if scope == "consolidated":
        return 0.8
    scope_markers = {
        "parent_attributable": ["归母", "归属于上市公司股东", "parent_attributable"],
        "adjusted": ["扣非", "扣除非经常性损益", "adjusted"],
        "non_controlling_interest": ["少数股东", "non_controlling"],
    }
    markers = scope_markers.get(scope, [])
    if any(m in text for m in markers):
        return 1.0
    all_markers = [m for ms in scope_markers.values() for m in ms]
    if any(m in text for m in all_markers):
        return 0.0  # different scope present
    return 0.5


def _unit_match(claim: dict, candidate: dict) -> float:
    claim_unit = str(claim.get("unit") or "").strip()
    text = candidate.get("text", "") or ""
    if not claim_unit:
        return 0.5
    unit_patterns = {
        "亿元": ["亿元", "亿"],
        "万元": ["万元", "万"],
        "%": ["%", "％"],
        "元/股": ["元/股", "每股"],
    }
    claim_patterns = unit_patterns.get(claim_unit, [claim_unit])
    if any(p in text for p in claim_patterns):
        return 1.0
    if any(p in text for ps in unit_patterns.values() for p in ps):
        return 0.3
    return 0.5


def _numeric_match(claim: dict, candidate: dict) -> float:
    value = claim.get("value")
    if not isinstance(value, (int, float)):
        return 0.5
    text = candidate.get("text", "") or ""
    from app.services.evidence_retrieval.engine import _block_value_hits
    ok, _ = _block_value_hits(text, value, claim.get("unit"))
    return 1.0 if ok else 0.0


def _route_match(routing: ClaimRoutingResult, candidate: dict) -> float:
    route = routing.route
    text = candidate.get("text", "") or ""
    if route in ("STRUCTURED_NUMERIC", "TABLE_METRIC", "PERIOD_COMPARISON"):
        return 1.0 if re.search(r"\d", text) else 0.2
    if route == "CAUSALITY":
        return 1.0 if any(m in text for m in CAUSAL_MARKERS) else 0.0
    if route == "FORECAST":
        return 1.0 if any(m in text for m in FORECAST_MARKERS) else 0.2
    if route == "NARRATIVE_FACT":
        return 0.8
    return 0.5


def evaluate_one(claim: dict, candidate: dict, routing: ClaimRoutingResult,
                 gate_config: GateConfig) -> EvidenceQualityResult:
    """Pure gate evaluation: candidate + routing -> EvidenceQualityResult."""
    eid = str(candidate.get("evidence_id") or candidate.get("block_id") or "?")

    entity_ok = _entity_match(claim, candidate)
    metric_score = _metric_match(claim, candidate)
    period_score = _period_match(claim, candidate)
    unit_score = _unit_match(claim, candidate)
    scope_score = _scope_match(claim, candidate)
    numeric_score = _numeric_match(claim, candidate)
    route_score = _route_match(routing, candidate)

    has_numbers = bool(re.search(r"\d", candidate.get("text", "") or ""))
    source_quality = 0.8 if has_numbers else 0.4

    completeness = (
        0.25 * metric_score + 0.20 * period_score + 0.15 * scope_score
        + 0.15 * unit_score + 0.15 * numeric_score + 0.10 * route_score
    )

    contradiction = 0.0
    if period_score == 0.0:
        contradiction = max(contradiction, 0.8)
    if scope_score == 0.0:
        contradiction = max(contradiction, 0.7)

    # CAUSALITY: must have causal language
    if routing.route == "CAUSALITY" and gate_config.causal_language_required:
        if route_score == 0.0:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.0, False,
                "CAUSALITY gate: no causal language found"
            )

    # Numeric routes: entity + metric + period + scope conditions
    if routing.route in ("STRUCTURED_NUMERIC", "TABLE_METRIC",
                         "PERIOD_COMPARISON", "SCOPE_VALIDATION"):
        if not entity_ok:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.0, False,
                "entity mismatch: candidate does not mention claim entity"
            )
        if metric_score < gate_config.metric_match_threshold:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.2, False,
                f"metric match {metric_score:.2f} below threshold "
                f"{gate_config.metric_match_threshold}"
            )
        if gate_config.period_conflict_strict and period_score == 0.0:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.1, False,
                "period conflict: candidate mentions different period"
            )
        if gate_config.scope_conflict_strict and scope_score == 0.0:
            return EvidenceQualityResult(
                eid, entity_ok, metric_score, period_score, unit_score,
                scope_score, numeric_score, source_quality, route_score,
                contradiction, completeness, 0.1, False,
                "scope conflict: candidate mentions different scope"
            )

    final_score = completeness * (1.0 - contradiction * 0.5)

    if final_score >= gate_config.high_quality_threshold:
        accepted = True
        rejection = ""
    elif final_score >= gate_config.medium_quality_threshold:
        accepted = True
        rejection = ""
    else:
        accepted = False
        rejection = f"quality score {final_score:.3f} below medium threshold"

    return EvidenceQualityResult(
        eid, entity_ok, metric_score, period_score, unit_score, scope_score,
        numeric_score, source_quality, route_score, contradiction,
        completeness, final_score, accepted, rejection,
    )


def evaluate_all(claim: dict, candidates: list[dict],
                 routing: ClaimRoutingResult,
                 gate_config: GateConfig) -> list[EvidenceQualityResult]:
    """Evaluate all candidates through the gate (pure)."""
    return [evaluate_one(claim, c, routing, gate_config) for c in candidates]


__all__ = ["EvidenceQualityResult", "GateConfig", "evaluate_one", "evaluate_all"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_phase23_11_evidence_gate.py -v`

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/evidence_gate.py backend/tests/test_phase23_11_evidence_gate.py
git commit -m "feat(phase23.11): add pure-function EvidenceGate with per-route thresholds"
```

---

## Task 4: FinancialFactIndex (build + query) + tests

**Files:**
- Create: `backend/app/services/financial_fact_index.py`
- Test: `backend/tests/test_phase23_11_fact_index.py`

**Interfaces:**
- Consumes: `session: Session`, `doc_id: int`, `claim: dict`, `routing: ClaimRoutingResult`.
- Produces: `rebuild_for_document(session, doc_id) -> int`; `query_facts(session, claim, routing, top_k=10) -> list[dict]` (Channel A candidates).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_phase23_11_fact_index.py
import pytest
from app.db import SessionLocal
from app.models.financial_fact import FinancialFact, ensure_financial_fact_table
from app.services.financial_fact_index import rebuild_for_document, query_facts


@pytest.fixture
def session():
    s = SessionLocal()
    ensure_financial_fact_table(s)
    yield s
    s.query(FinancialFact).delete()
    s.commit()
    s.close()


def test_fact_insert(session):
    fact = FinancialFact(
        fact_id="FF-1-5-0", company="五粮液", document_id=1,
        document_type="annual_report", page=5, table_id="T-1-5-0",
        section_title="主要会计数据", table_title="营业收入",
        row_header="营业收入", parent_row_header="",
        column_header="2025年", period_header="2025年",
        metric="营业收入", metric_canonical="revenue",
        period="2025FY", period_type="FY", unit="亿元", currency="CNY",
        scope="consolidated", raw_value="931.8", normalized_value=931.8,
        source_block_ids=[1, 2], neighboring_context={},
    )
    session.add(fact)
    session.commit()
    assert session.query(FinancialFact).count() == 1


def test_query_facts_by_company_metric(session):
    session.add(FinancialFact(
        fact_id="FF-1-5-0", company="五粮液", document_id=1,
        document_type="annual_report", page=5, table_id="T-1-5-0",
        section_title="", table_title="", row_header="营业收入",
        parent_row_header="", column_header="2025年", period_header="2025年",
        metric="营业收入", metric_canonical="revenue",
        period="2025FY", period_type="FY", unit="亿元", currency="CNY",
        scope="consolidated", raw_value="931.8", normalized_value=931.8,
        source_block_ids=[1], neighboring_context={},
    ))
    session.commit()
    claim = {"entity": "五粮液", "metric_code": "revenue", "period": "2025FY",
             "unit": "亿元", "scope": "consolidated"}
    from app.services.claim_router import route_claim
    routing = route_claim(claim)
    facts = query_facts(session, claim, routing, top_k=5)
    assert len(facts) >= 1
    assert any(f["page"] == 5 for f in facts)


def test_query_facts_filters_wrong_company(session):
    session.add(FinancialFact(
        fact_id="FF-2-5-0", company="美的集团", document_id=2,
        document_type="annual_report", page=5, table_id="T-2-5-0",
        section_title="", table_title="", row_header="营业收入",
        parent_row_header="", column_header="", period_header="2025年",
        metric="营业收入", metric_canonical="revenue",
        period="2025FY", period_type="FY", unit="亿元", currency="CNY",
        scope="consolidated", raw_value="1000", normalized_value=1000.0,
        source_block_ids=[1], neighboring_context={},
    ))
    session.commit()
    claim = {"entity": "五粮液", "metric_code": "revenue", "period": "2025FY"}
    from app.services.claim_router import route_claim
    routing = route_claim(claim)
    facts = query_facts(session, claim, routing, top_k=5)
    assert all(f.get("company", "") != "美的集团" for f in facts)


def test_fact_index_has_no_gold_fields(session):
    """FinancialFact must NOT have gold_page, gold_block_id, expected_verdict."""
    cols = [c.name for c in FinancialFact.__table__.columns]
    forbidden = ["gold_page", "gold_block_id", "expected_verdict",
                 "is_correct_answer", "dev_set_label"]
    for f in forbidden:
        assert f not in cols, f"forbidden field {f} present in FinancialFact"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_phase23_11_fact_index.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/financial_fact_index.py
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


_UNIT_TO_BASE: dict[str, float] = {
    "亿元": 1e8, "万元": 1e4, "千元": 1e3, "元": 1.0,
    "百万": 1e6, "十亿": 1e9, "元/股": 1.0,
}


def _normalize_value_to_base(raw_value: str, unit: str) -> float | None:
    if not raw_value:
        return None
    clean = raw_value.replace("(", "").replace(")", "").replace(",", "")
    try:
        v = float(clean)
    except ValueError:
        return None
    scale = _UNIT_TO_BASE.get(unit, 1.0)
    return v * scale


def _period_type_of(period: str) -> str:
    p = str(period or "").upper()
    if p.endswith("FY"):
        return "FY"
    if p.endswith("H1"):
        return "H1"
    if re.match(r".*Q[1-4]$", p):
        return p[-2:]
    return "FY"


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
                continue
            fact_id = f"FF-{doc_id}-{page.page_number}-{idx}"
            unit = ctx.unit_header or ""
            if not unit and ctx.table_title:
                m = re.search(r"[（(](万亿元|亿元|百万元|万元|千元|元)[）)]", ctx.table_title)
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


def query_facts(session: Session, claim: dict, routing,
                 top_k: int = 10) -> list[dict]:
    """Query FinancialFact by company + metric + period + scope + unit.

    Returns Channel A candidates.
    """
    company = str(claim.get("entity") or claim.get("entity_name") or "").strip()
    metric_code = str(claim.get("metric_code") or "").strip()
    period = str(claim.get("period") or "").strip()
    unit = str(claim.get("unit") or "").strip()
    scope = str(claim.get("scope") or "consolidated").strip()

    q = session.query(FinancialFact)

    if company:
        q = q.filter(FinancialFact.company == company)

    facts = q.order_by(FinancialFact.page).limit(top_k * 5).all()

    scored = []
    for f in facts:
        score = 0.0
        if metric_code and f.metric_canonical == metric_code:
            score += 0.4
        elif metric_code and f.metric_canonical:
            score += 0.1
        if period and f.period:
            if period in f.period or f.period in period:
                score += 0.3
        if scope and f.scope:
            if scope == f.scope:
                score += 0.2
        if unit and f.unit:
            if unit == f.unit:
                score += 0.1
        score += 0.1
        scored.append((score, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, f in scored[:top_k]:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_phase23_11_fact_index.py -v`

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/financial_fact_index.py backend/tests/test_phase23_11_fact_index.py
git commit -m "feat(phase23.11): add FinancialFactIndex with build + query (Channel A)"
```

---

## Task 5: EvidenceSelector (pure function, Top1/Top3/Top5 + ambiguity)

**Files:**
- Create: `backend/app/services/evidence_selector.py`
- Test: `backend/tests/test_phase23_11_evidence_selector.py`

**Interfaces:**
- Consumes: `gate_results: list[EvidenceQualityResult]`, `routing: ClaimRoutingResult`, `selector_config: SelectorConfig`.
- Produces: `select(...) -> tuple[list[dict], SelectionResult]`. `SelectionResult` dataclass with fields: `selected_evidence_ids, rejected_evidence_ids, candidates_before_gate, candidates_after_gate, evidence_bundle, selection_reason, top1_quality, top2_quality, quality_margin, ambiguity_flag, ambiguity_reason`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_phase23_11_evidence_selector.py
from app.services.evidence_selector import (
    select, SelectorConfig, SelectionResult,
)
from app.services.evidence_gate import EvidenceQualityResult
from app.services.claim_router import route_claim


def _qr(eid, score, accepted=True):
    return EvidenceQualityResult(
        evidence_id=eid, entity_match=True, metric_match=score,
        period_match=score, unit_match=score, scope_match=score,
        numeric_match=score, source_quality=score, route_match=score,
        contradiction_signal=0.0, completeness_score=score,
        final_quality_score=score, accepted=accepted, rejection_reason="",
    )


def test_selector_top3_returns_max_3():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [_qr(f"B{i}", 0.8) for i in range(5)]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    selected, meta = select(gate_results, routing, cfg)
    assert isinstance(meta, SelectionResult)
    assert len(selected) <= 3
    assert meta.candidates_after_gate == 5


def test_selector_top1_strategy():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [_qr(f"B{i}", 0.9 - i * 0.1) for i in range(3)]
    cfg = SelectorConfig(strategy="Top1", max_evidence=1)
    selected, meta = select(gate_results, routing, cfg)
    assert len(selected) == 1
    assert meta.top1_quality >= 0.8


def test_selector_flags_ambiguity_margin():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [
        _qr("B1", 0.80),
        _qr("B2", 0.79),  # very close quality
    ]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3,
                         ambiguity_margin=0.05)
    selected, meta = select(gate_results, routing, cfg)
    assert meta.ambiguity_flag is True or meta.quality_margin >= 0.05


def test_selector_no_accepted_evidence_returns_empty():
    claim = {"claim_id": "CLM-1", "metric_code": "revenue",
             "claim_type": "NUMERIC_VALUE", "period": "2025FY",
             "unit": "亿元", "value": 100, "original_text": "营收100亿"}
    routing = route_claim(claim)
    gate_results = [_qr(f"B{i}", 0.1, accepted=False) for i in range(3)]
    cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    selected, meta = select(gate_results, routing, cfg)
    assert len(selected) == 0
    assert meta.selection_reason != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_phase23_11_evidence_selector.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/evidence_selector.py
"""Phase 23.11 Evidence Selector (pure function).

Dedup near-duplicates, cap at max_evidence (default 3), support Top1/Top3/
Top5 strategies, detect ambiguity margin when top1 ≈ top2 but metric/period/
scope differ.

Pure: no DB, no I/O. Tunable thresholds only via leave-one-company-out CV.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

from app.services.claim_router import ClaimRoutingResult
from app.services.evidence_gate import EvidenceQualityResult


@dataclass
class SelectorConfig:
    strategy: Literal["Top1", "Top3", "Top5"] = "Top3"
    max_evidence: int = 3
    ambiguity_margin: float = 0.05
    duplicate_page_threshold: float = 0.9


@dataclass
class SelectionResult:
    selected_evidence_ids: list = field(default_factory=list)
    rejected_evidence_ids: list = field(default_factory=list)
    candidates_before_gate: int = 0
    candidates_after_gate: int = 0
    evidence_bundle: list = field(default_factory=list)
    selection_reason: str = ""
    top1_quality: float = 0.0
    top2_quality: float = 0.0
    quality_margin: float = 0.0
    ambiguity_flag: bool = False
    ambiguity_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "selected_evidence_ids": self.selected_evidence_ids,
            "rejected_evidence_ids": self.rejected_evidence_ids,
            "candidates_before_gate": self.candidates_before_gate,
            "candidates_after_gate": self.candidates_after_gate,
            "evidence_bundle": self.evidence_bundle,
            "selection_reason": self.selection_reason,
            "top1_quality": round(self.top1_quality, 4),
            "top2_quality": round(self.top2_quality, 4),
            "quality_margin": round(self.quality_margin, 4),
            "ambiguity_flag": self.ambiguity_flag,
            "ambiguity_reason": self.ambiguity_reason,
        }


def select(gate_results: list[EvidenceQualityResult],
           routing: ClaimRoutingResult,
           config: SelectorConfig) -> tuple[list[dict], SelectionResult]:
    """Pure selection: gate results -> final evidence bundle + metadata."""
    before = len(gate_results)
    accepted = [r for r in gate_results if r.accepted]
    rejected = [r for r in gate_results if not r.accepted]
    after = len(accepted)

    accepted.sort(key=lambda r: r.final_quality_score, reverse=True)

    if config.strategy == "Top1":
        max_count = 1
    elif config.strategy == "Top3":
        max_count = min(3, config.max_evidence)
    elif config.strategy == "Top5":
        max_count = min(5, config.max_evidence)
    else:
        max_count = config.max_evidence

    top_accepted = accepted[:max_count]

    top1_q = top_accepted[0].final_quality_score if len(top_accepted) >= 1 else 0.0
    top2_q = top_accepted[1].final_quality_score if len(top_accepted) >= 2 else 0.0
    margin = abs(top1_q - top2_q)

    ambiguity = False
    ambiguity_reason = ""
    if len(top_accepted) >= 2 and margin < config.ambiguity_margin:
        r1, r2 = top_accepted[0], top_accepted[1]
        if (r1.metric_match != r2.metric_match or
                r1.period_match != r2.period_match or
                r1.scope_match != r2.scope_match):
            ambiguity = True
            ambiguity_reason = (
                f"top1 quality {top1_q:.3f} ≈ top2 quality {top2_q:.3f} "
                f"but metric/period/scope signals differ"
            )

    evidence_bundle = []
    for r in top_accepted:
        evidence_bundle.append({
            "evidence_id": r.evidence_id,
            "text": "",  # filled by retrieve_via_channels
            "final_quality_score": r.final_quality_score,
        })

    if not top_accepted:
        reason = "no evidence accepted by gate"
    elif ambiguity:
        reason = f"ambiguity detected: {ambiguity_reason}"
    else:
        reason = f"selected {len(top_accepted)} evidence via {config.strategy}"

    meta = SelectionResult(
        selected_evidence_ids=[r.evidence_id for r in top_accepted],
        rejected_evidence_ids=[r.evidence_id for r in rejected],
        candidates_before_gate=before,
        candidates_after_gate=after,
        evidence_bundle=evidence_bundle,
        selection_reason=reason,
        top1_quality=top1_q,
        top2_quality=top2_q,
        quality_margin=margin,
        ambiguity_flag=ambiguity,
        ambiguity_reason=ambiguity_reason,
    )
    return evidence_bundle, meta


__all__ = ["SelectorConfig", "SelectionResult", "select"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_phase23_11_evidence_selector.py -v`

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/evidence_selector.py backend/tests/test_phase23_11_evidence_selector.py
git commit -m "feat(phase23.11): add pure-function EvidenceSelector with Top1/Top3/Top5 + ambiguity"
```

---

## Task 6: VerificationContext + verify_evidence_set canonical entry

**Files:**
- Create: `backend/app/services/verification_context.py`
- Modify: `backend/app/services/verification/verification_service.py` — add `verify_evidence_set`, `verify_core_oracle`, `verify_noisy_oracle`, `verify_real_e2e`, `verify_claim_production`; convert `verify_claim` to thin adapter.
- Test: `backend/tests/test_phase23_11_integration.py`

**Interfaces:**
- Produces: `verify_evidence_set(claim, evidence_candidates, routing_result, verification_context) -> VerificationResult`. `VerificationContext` dataclass with fields: `evidence_source (Literal), gate_config: GateConfig, selector_config: SelectorConfig, trace: IntegrationTrace | None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_phase23_11_integration.py
from app.services.verification_context import VerificationContext
from app.services.evidence_gate import GateConfig
from app.services.evidence_selector import SelectorConfig
from app.services.claim_router import route_claim
from app.services.verification.verification_service import (
    verify_evidence_set, verify_core_oracle, verify_noisy_oracle,
    verify_real_e2e, verify_claim_production,
)
from app.services.verification.core_pipeline import IntegrationTrace


def test_verify_evidence_set_runs_full_pipeline():
    claim = {"claim_id": "CLM-TEST", "entity": "五粮液",
             "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "scope": "consolidated",
             "value": 931.8, "original_text": "五粮液2025年营收931.8亿"}
    routing = route_claim(claim)
    candidates = [
        {"evidence_id": "B1", "text": "营业收入 931.8 亿元 2025年 五粮液",
         "page": 5, "document_id": 1},
    ]
    ctx = VerificationContext(
        evidence_source="real_e2e",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_evidence_set(claim, candidates, routing, ctx)
    assert result.claim_id == "CLM-TEST"
    assert result.verification_status in (
        "SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE",
        "UNABLE_TO_DETERMINE",
    )


def test_core_oracle_calls_verify_evidence_set():
    """CORE_ORACLE must route through verify_evidence_set, not bypass."""
    claim = {"claim_id": "CLM-ORACLE", "entity": "五粮液",
             "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "value": 931.8,
             "scope": "consolidated",
             "original_text": "五粮液2025年营收931.8亿"}
    routing = route_claim(claim)
    gold_evidence = {"evidence_id": "GOLD-B1",
                     "text": "营业收入 931.8 亿元 2025年",
                     "page": 5, "document_id": 1}
    ctx = VerificationContext(
        evidence_source="core_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_core_oracle(claim, gold_evidence, routing, ctx)
    assert result.claim_id == "CLM-ORACLE"


def test_gold_evidence_rejected_by_gate_makes_oracle_fail():
    """If Gold is rejected by Gate, Oracle must NOT bypass; result is INSUFFICIENT."""
    claim = {"claim_id": "CLM-GOLD-REJECT", "entity": "五粮液",
             "metric_code": "revenue", "claim_type": "NUMERIC_VALUE",
             "period": "2025FY", "unit": "亿元", "value": 931.8,
             "scope": "consolidated",
             "original_text": "五粮液2025年营收931.8亿"}
    routing = route_claim(claim)
    # Gold evidence with wrong period (will fail period gate)
    gold_evidence = {"evidence_id": "GOLD-BAD",
                     "text": "营业收入 100 亿元 2023年",  # wrong period
                     "page": 5, "document_id": 1}
    ctx = VerificationContext(
        evidence_source="core_oracle",
        gate_config=GateConfig(),
        selector_config=SelectorConfig(strategy="Top3"),
    )
    result = verify_core_oracle(claim, gold_evidence, routing, ctx)
    # Oracle should NOT bypass the gate; should get INSUFFICIENT
    assert result.verification_status in (
        "INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE",
    )


def test_verify_claim_is_thin_adapter():
    """Old verify_claim must be a thin adapter, no independent Verdict logic."""
    from app.services.verification.verification_service import verify_claim
    # verify_claim should still work and delegate to verify_evidence_set
    # (smoke test: it doesn't raise)
    import inspect
    src = inspect.getsource(verify_claim)
    # Should contain call to verify_evidence_set or routing
    assert "verify_evidence_set" in src or "route_claim" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_phase23_11_integration.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write VerificationContext**

```python
# backend/app/services/verification_context.py
"""Phase 23.11 VerificationContext.

Carries gate_config, selector_config, evidence_source, and trace.
Shared by CORE_ORACLE, NOISY_ORACLE, REAL_E2E.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

from app.services.evidence_gate import GateConfig
from app.services.evidence_selector import SelectorConfig


@dataclass
class VerificationContext:
    evidence_source: Literal["core_oracle", "noisy_oracle", "real_e2e"]
    gate_config: GateConfig = field(default_factory=GateConfig)
    selector_config: SelectorConfig = field(default_factory=SelectorConfig)
    trace: object | None = None  # IntegrationTrace, set by verify_evidence_set
    candidates_before_gate: int = 0
    candidates_after_gate: int = 0


__all__ = ["VerificationContext"]
```

- [ ] **Step 4: Modify verification_service.py to add canonical entry**

Append to `backend/app/services/verification/verification_service.py`:

```python
# ===== Phase 23.11: Canonical verify_evidence_set entry =====

from app.services.claim_router import route_claim, ClaimRoutingResult
from app.services.evidence_gate import evaluate_all, GateConfig
from app.services.evidence_selector import select, SelectorConfig
from app.services.verification.core_pipeline import IntegrationTrace, core_verify


def verify_evidence_set(claim: dict, evidence_candidates: list[dict],
                        routing_result: ClaimRoutingResult,
                        verification_context) -> "VerificationResult":
    """Canonical verification entry (Phase 23.11).

    Runs: Evidence Gate -> Evidence Selector -> core_verify.
    Shared by CORE_ORACLE, NOISY_ORACLE, REAL_E2E.
    Gold Evidence must pass through Gate and Selector; if Gold is rejected,
    record GATE_REJECTED_GOLD, do NOT bypass to protect Oracle 1.0.
    """
    # Initialize trace if not provided
    if verification_context.trace is None:
        verification_context.trace = IntegrationTrace(
            claim_id=str(claim.get("claim_id") or claim.get("claim_uid") or "?")
        )
    trace = verification_context.trace

    # Record candidates before gate
    verification_context.candidates_before_gate = len(evidence_candidates)

    # Step 1: Evidence Gate (pure)
    gate_results = evaluate_all(
        claim, evidence_candidates, routing_result,
        verification_context.gate_config,
    )
    verification_context.candidates_after_gate = sum(1 for r in gate_results if r.accepted)

    # Record gate step in trace
    trace.detail["phase23_11_gate"] = {
        "evidence_source": verification_context.evidence_source,
        "candidates_before_gate": verification_context.candidates_before_gate,
        "candidates_after_gate": verification_context.candidates_after_gate,
        "gate_results": [r.to_dict() for r in gate_results],
    }

    # Step 2: Evidence Selector (pure)
    evidence_bundle, selection_meta = select(
        gate_results, routing_result, verification_context.selector_config,
    )

    trace.detail["phase23_11_selector"] = selection_meta.to_dict()

    # Step 3: core_verify (UNCHANGED) with gated evidence
    final = core_verify(claim, evidence_bundle, trace)

    # Attach routing + selection metadata to trace
    trace.detail["phase23_11_routing"] = routing_result.to_dict()
    trace.detail["phase23_11_final"] = {
        "verification_status": final.verification_status,
        "confidence": final.confidence,
    }

    return final


def verify_core_oracle(claim: dict, gold_evidence: dict,
                       routing: ClaimRoutingResult, ctx) -> "VerificationResult":
    """CORE_ORACLE: Gold Evidence -> Gate -> Selector -> core_verify.

    If Gold is rejected by Gate, result is INSUFFICIENT_EVIDENCE
    (GATE_REJECTED_GOLD), do NOT bypass.
    """
    return verify_evidence_set(claim, [gold_evidence], routing, ctx)


def verify_noisy_oracle(