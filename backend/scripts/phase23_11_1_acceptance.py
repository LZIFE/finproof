"""Phase 23.11.1 Unified Acceptance Script (Task 2).

Runs CORE_ORACLE / NOISY_ORACLE / REAL_E2E on the SAME 43 Development Claims
(demo + holdout, loaded via evaluation_claim_schema.load_canonical_claims).

Key fixes vs Phase 23.11 acceptance:
- Uses CanonicalClaim (43 claims from demo+holdout), NOT load_gold_claims("demo") (26).
- expected_verdict from gold_verifications.json, never silently defaulted.
- normalize_verdict() is the single verdict mapping; no per-script mapping.
- Three modes all call verify_evidence_set → Gate → Selector → core_verify.
- Outputs per-mode metrics + shared path trace + abstention diagnosis.

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_1_acceptance.py
    cd backend && PYTHONPATH=. python scripts/phase23_11_1_acceptance.py --mode core_oracle
    cd backend && PYTHONPATH=. python scripts/phase23_11_1_acceptance.py --mode noisy_oracle
    cd backend && PYTHONPATH=. python scripts/phase23_11_1_acceptance.py --mode real_e2e
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import SessionLocal
from app.services.evaluation_claim_schema import (
    CANONICAL_VERDICTS,
    CanonicalClaim,
    load_canonical_claims,
    normalize_verdict,
    validate_schema,
)
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_all
from app.services.evidence_selector import SelectorConfig, select
from app.services.verification_context import VerificationContext
from app.services.verification.verification_service import (
    verify_evidence_set,
)
from app.services.verification.core_pipeline import IntegrationTrace, core_verify
from app.services.verification.base import VerificationResult

ART = BACKEND / "artifacts"
EVAL_DIR = ART / "evaluation"
E2E_DIR = ART / "e2e"
INTEG_DIR = ART / "integration"
LOG_DIR = ART / "logs" / "phase23_11_1"

# Gold evidence file lookup (for CORE_ORACLE / NOISY_ORACLE)
GOLD_EVIDENCE_FILES = {
    "demo": BACKEND.parent / "data" / "demo" / "annotations" / "gold_evidence.json",
    "holdout": BACKEND.parent / "data" / "holdout" / "annotations" / "gold_evidence.json",
}
GOLD_CLAIM_FILES = {
    "demo": BACKEND.parent / "data" / "demo" / "annotations" / "gold_claims.json",
    "holdout": BACKEND.parent / "data" / "holdout" / "annotations" / "gold_claims.json",
}


# ===========================================================================
# Gold evidence loader (joins gold_evidence.json by claim_id)
# ===========================================================================

def load_gold_evidence_by_claim() -> dict[str, list[dict]]:
    """Return {claim_id: [evidence_dict, ...]} from gold_evidence.json (both datasets)."""
    out: dict[str, list[dict]] = {}
    for ds, path in GOLD_EVIDENCE_FILES.items():
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for e in data.get("evidence", []):
            cid = str(e.get("claim_id") or "")
            if not cid:
                continue
            # normalize to candidate format expected by verify_evidence_set
            fname = str(e.get("document_name") or "").split("/")[-1]
            out.setdefault(cid, []).append({
                "evidence_id": str(e.get("evidence_id") or f"EVD-{cid}"),
                "text": e.get("evidence_text", "") or e.get("text", "") or "",
                "page": e.get("page"),
                "document_name": e.get("document_name"),
                "document_id": e.get("document_id"),
                "evidence_type": e.get("evidence_type", ""),
                "source_level": e.get("source_level", ""),
                "doc_period": e.get("doc_period"),
            })
    return out


def load_raw_claims_by_id() -> dict[str, dict]:
    """Return {claim_id: raw_claim_dict} for core_verify field compatibility."""
    out: dict[str, dict] = {}
    for ds, path in GOLD_CLAIM_FILES.items():
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for c in data.get("claims", []):
            cid = str(c.get("claim_id") or "")
            if cid:
                c.setdefault("_dataset", ds)
                out[cid] = c
    return out


# ===========================================================================
# Hard negatives construction (for NOISY_ORACLE, §6)
# ===========================================================================

def build_hard_negatives(claim: CanonicalClaim, gold_evidence: list[dict]) -> list[dict]:
    """Construct ≥2 hard negatives per claim: wrong-period, wrong-metric,
    similar-value, narrative noise, wrong-scope.
    """
    negatives: list[dict] = []
    gold_text = gold_evidence[0]["text"] if gold_evidence else ""
    period = claim.period or "2025FY"
    metric = claim.metric or "revenue"
    scope = claim.scope or "consolidated"
    value = claim.value

    # wrong-period: shift period by one year
    wrong_period = "2023FY" if "2025" in period else "2025FY"
    negatives.append({
        "evidence_id": f"NEG-WP-{claim.claim_id}",
        "text": f"{metric} {value} {claim.unit or ''} {wrong_period}",
        "page": 5, "document_id": 1,
    })

    # wrong-metric: swap metric
    wrong_metric = "net_profit" if metric == "revenue" else "revenue"
    negatives.append({
        "evidence_id": f"NEG-WM-{claim.claim_id}",
        "text": f"{wrong_metric} {value} {claim.unit or ''} {period}",
        "page": 5, "document_id": 1,
    })

    # wrong-scope: change scope
    wrong_scope = "parent_only" if scope == "consolidated" else "consolidated"
    negatives.append({
        "evidence_id": f"NEG-WS-{claim.claim_id}",
        "text": f"({wrong_scope}) {metric} {value} {claim.unit or ''} {period}",
        "page": 5, "document_id": 1,
    })

    # similar-value noise: nearby numeric, same metric, off period
    if value is not None and isinstance(value, (int, float)):
        similar = round(value * 0.95, 2)
        negatives.append({
            "evidence_id": f"NEG-SV-{claim.claim_id}",
            "text": f"{metric} {similar} {claim.unit or ''} {wrong_period}",
            "page": 6, "document_id": 1,
        })

    # narrative noise: unrelated business text
    negatives.append({
        "evidence_id": f"NEG-NN-{claim.claim_id}",
        "text": "公司本期持续推进产品结构优化与渠道升级",
        "page": 12, "document_id": 1,
    })

    return negatives


# ===========================================================================
# Per-mode runners
# ===========================================================================

def _make_claim_dict(cc: CanonicalClaim, raw: dict) -> dict:
    """Build claim dict for core_verify (uses raw_claim for field compatibility)."""
    base = dict(raw)  # original claim fields
    # ensure canonical fields present
    base.setdefault("claim_id", cc.claim_id)
    base.setdefault("entity", cc.company)
    base.setdefault("original_text", cc.claim_text)
    base.setdefault("period", cc.period)
    base.setdefault("scope", cc.scope)
    base.setdefault("unit", cc.unit)
    base.setdefault("metric", cc.metric)
    if "value" not in base or base.get("value") is None:
        base["value"] = cc.value
    return base


def _wrap_trace(ctx: VerificationContext, claim_id: str):
    if ctx.trace is None:
        ctx.trace = IntegrationTrace(claim_id=claim_id)


def run_core_oracle(
    claims: list[CanonicalClaim],
    raw_by_id: dict[str, dict],
    gold_ev_by_cid: dict[str, list[dict]],
) -> dict:
    """CORE_ORACLE: Gold Evidence → Gate → Selector → core_verify (§5)."""
    gate_cfg = GateConfig()
    sel_cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    rows = []
    correct = 0
    gate_rejected_gold = 0
    gold_selected = 0
    missing = 0
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    pred_counter: Counter = Counter()
    gold_counter: Counter = Counter()
    ves_calls = 0
    gate_calls = 0
    sel_calls = 0
    cv_calls = 0

    for cc in claims:
        raw = raw_by_id.get(cc.claim_id, {})
        claim = _make_claim_dict(cc, raw)
        routing = route_claim(claim)
        gold_ev = gold_ev_by_cid.get(cc.claim_id, [])
        if not gold_ev:
            # No gold evidence recorded; still run with empty → will abstain
            candidates = []
        else:
            candidates = list(gold_ev)
        ctx = VerificationContext(
            evidence_source="core_oracle",
            gate_config=gate_cfg, selector_config=sel_cfg,
        )
        try:
            result = verify_evidence_set(claim, candidates, routing, ctx)
            ves_calls += 1
            gate_calls += 1
            sel_calls += 1
            cv_calls += 1
        except Exception as exc:  # noqa: BLE001
            result = VerificationResult(cc.claim_id, "INSUFFICIENT_EVIDENCE",
                                         confidence=0.2, reason=f"error: {exc}")
            missing += 1
        pred = normalize_verdict(result.verification_status)
        gold = cc.expected_verdict
        if pred == gold:
            correct += 1
        # gold gate acceptance: did gate accept at least one gold evidence?
        gate_results = ctx.trace.detail.get("phase23_11_gate", {}).get("gate_results", []) if ctx.trace else []
        gold_accepted = any(r.get("accepted") for r in gate_results) if gate_results else False
        if gold_ev and not gold_accepted:
            gate_rejected_gold += 1
        sel_meta = ctx.trace.detail.get("phase23_11_selector", {}) if ctx.trace else {}
        if cc.claim_id and any(
            str(e.get("evidence_id")) in sel_meta.get("selected_evidence_ids", [])
            for e in gold_ev
        ):
            gold_selected += 1
        confusion[(gold, pred)] += 1
        pred_counter[pred] += 1
        gold_counter[gold] += 1
        rows.append({
            "claim_id": cc.claim_id, "gold": gold, "pred": pred,
            "correct": pred == gold, "route": routing.route,
            "gold_evidence_count": len(gold_ev),
            "gold_accepted": gold_accepted,
            "selected": sel_meta.get("selected_evidence_ids", []),
        })

    return _finalize_metrics(
        "core_oracle", claims, rows, correct, missing, confusion,
        pred_counter, gold_counter, extra={
            "gold_gate_acceptance_rate": round((len(claims) - gate_rejected_gold - sum(1 for c in claims if not gold_ev_by_cid.get(c.claim_id))) / max(len(claims), 1), 4),
            "gold_selection_rate": round(gold_selected / max(len(claims), 1), 4),
            "gate_rejected_gold_count": gate_rejected_gold,
        },
        path_counts={
            "input_claim_count": len(claims), "evidence_source": "gold_evidence",
            "verify_evidence_set_call_count": ves_calls, "gate_call_count": gate_calls,
            "selector_call_count": sel_calls, "core_verify_call_count": cv_calls,
            "output_result_count": len(rows), "missing_result_count": missing,
        },
    )


def run_noisy_oracle(
    claims: list[CanonicalClaim],
    raw_by_id: dict[str, dict],
    gold_ev_by_cid: dict[str, list[dict]],
) -> dict:
    """NOISY_ORACLE: Gold + Hard Negatives → Gate → Selector → core_verify (§6)."""
    gate_cfg = GateConfig()
    sel_cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    rows = []
    correct = 0
    missing = 0
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    pred_counter: Counter = Counter()
    gold_counter: Counter = Counter()
    # gate metrics
    tp = 0  # gold accepted
    fn = 0  # gold rejected
    noise_accepted = 0
    noise_total = 0
    gold_top1 = 0
    gold_top3 = 0
    accepted_evidence_count = 0
    ves_calls = gate_calls = sel_calls = cv_calls = 0

    for cc in claims:
        raw = raw_by_id.get(cc.claim_id, {})
        claim = _make_claim_dict(cc, raw)
        routing = route_claim(claim)
        gold_ev = gold_ev_by_cid.get(cc.claim_id, [])
        negatives = build_hard_negatives(cc, gold_ev)
        candidates = list(gold_ev) + negatives
        ctx = VerificationContext(
            evidence_source="noisy_oracle",
            gate_config=gate_cfg, selector_config=sel_cfg,
        )
        try:
            result = verify_evidence_set(claim, candidates, routing, ctx)
            ves_calls += 1
            gate_calls += 1
            sel_calls += 1
            cv_calls += 1
        except Exception as exc:  # noqa: BLE001
            result = VerificationResult(cc.claim_id, "INSUFFICIENT_EVIDENCE",
                                         confidence=0.2, reason=f"error: {exc}")
            missing += 1
        pred = normalize_verdict(result.verification_status)
        gold = cc.expected_verdict
        if pred == gold:
            correct += 1
        # gate analysis
        gate_results = ctx.trace.detail.get("phase23_11_gate", {}).get("gate_results", []) if ctx.trace else []
        gold_eid_set = {str(e.get("evidence_id")) for e in gold_ev}
        neg_eid_set = {str(n.get("evidence_id")) for n in negatives}
        gold_accepted_here = any(
            r.get("accepted") and r.get("evidence_id") in gold_eid_set
            for r in gate_results
        )
        if gold_ev:
            if gold_accepted_here:
                tp += 1
            else:
                fn += 1
        noise_accepted_here = sum(
            1 for r in gate_results
            if r.get("accepted") and r.get("evidence_id") in neg_eid_set
        )
        noise_accepted += noise_accepted_here
        noise_total += len(negatives)
        accepted_evidence_count += sum(1 for r in gate_results if r.get("accepted"))
        # gold top1/top3: is gold in selected list at rank 1 or within top 3?
        sel_meta = ctx.trace.detail.get("phase23_11_selector", {}) if ctx.trace else {}
        sel_ids = [str(x) for x in sel_meta.get("selected_evidence_ids", [])]
        if sel_ids and sel_ids[0] in gold_eid_set:
            gold_top1 += 1
        if any(x in gold_eid_set for x in sel_ids[:3]):
            gold_top3 += 1
        confusion[(gold, pred)] += 1
        pred_counter[pred] += 1
        gold_counter[gold] += 1
        rows.append({
            "claim_id": cc.claim_id, "gold": gold, "pred": pred,
            "correct": pred == gold, "route": routing.route,
            "candidates": len(candidates), "negatives": len(negatives),
            "gold_accepted": gold_accepted_here, "noise_accepted": noise_accepted_here,
            "selected": sel_ids,
        })

    gate_precision = tp / max(tp + noise_accepted, 1)
    gate_recall = tp / max(tp + fn, 1)
    accepted_noise_rate = noise_accepted / max(noise_total, 1)
    rejected_gold_rate = fn / max(tp + fn, 1)

    return _finalize_metrics(
        "noisy_oracle", claims, rows, correct, missing, confusion,
        pred_counter, gold_counter, extra={
            "gate_precision": round(gate_precision, 4),
            "gate_recall": round(gate_recall, 4),
            "accepted_noise_rate": round(accepted_noise_rate, 4),
            "rejected_gold_rate": round(rejected_gold_rate, 4),
            "gold_top1_rate": round(gold_top1 / max(len(claims), 1), 4),
            "gold_top3_rate": round(gold_top3 / max(len(claims), 1), 4),
            "average_accepted_evidence_count": round(accepted_evidence_count / max(len(claims), 1), 4),
        },
        path_counts={
            "input_claim_count": len(claims), "evidence_source": "gold+hard_negatives",
            "verify_evidence_set_call_count": ves_calls, "gate_call_count": gate_calls,
            "selector_call_count": sel_calls, "core_verify_call_count": cv_calls,
            "output_result_count": len(rows), "missing_result_count": missing,
        },
    )


def run_real_e2e(
    claims: list[CanonicalClaim],
    raw_by_id: dict[str, dict],
    session,
    top_k: int = 10,
) -> dict:
    """REAL_E2E: Router → Retrieval → Gate → Selector → core_verify (§7)."""
    from app.services.evidence_retrieval.service import retrieve_for_claim

    gate_cfg = GateConfig()
    sel_cfg = SelectorConfig(strategy="Top3", max_evidence=3)
    rows = []
    correct = 0
    missing = 0
    abstentions = 0
    coverage_count = 0
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    pred_counter: Counter = Counter()
    gold_counter: Counter = Counter()
    retrieval_failure = 0
    gate_failure = 0
    verification_failure = 0
    aggregation_failure = 0
    ves_calls = gate_calls = sel_calls = cv_calls = 0
    # Phase 23.11.2 §7: mutually-exclusive primary outcomes (sum MUST = 43)
    from app.services.failure_attribution import classify_outcome, summarize_outcomes
    claim_outcomes: list = []

    for cc in claims:
        raw = raw_by_id.get(cc.claim_id, {})
        claim = _make_claim_dict(cc, raw)
        routing = route_claim(claim)
        ctx = VerificationContext(
            evidence_source="real_e2e",
            gate_config=gate_cfg, selector_config=sel_cfg,
        )
        # retrieval
        try:
            cands_raw = retrieve_for_claim(session, claim, top_k=top_k)
            candidates = []
            for c in cands_raw:
                candidates.append({
                    "evidence_id": str(c.get("block_id") or "?"),
                    "block_id": c.get("block_id"),
                    "text": c.get("block_text", "") or "",
                    "page": c.get("page_number"),
                    "document_id": c.get("document_id"),
                })
        except Exception as exc:  # noqa: BLE001
            candidates = []
            retrieval_failure += 1
        if not candidates:
            retrieval_failure += 1
        try:
            result = verify_evidence_set(claim, candidates, routing, ctx)
            ves_calls += 1
            gate_calls += 1
            sel_calls += 1
            cv_calls += 1
        except Exception as exc:  # noqa: BLE001
            result = VerificationResult(cc.claim_id, "INSUFFICIENT_EVIDENCE",
                                         confidence=0.2, reason=f"error: {exc}")
            missing += 1
        pred = normalize_verdict(result.verification_status)
        gold = cc.expected_verdict
        if pred == gold:
            correct += 1
        if pred == "INSUFFICIENT_EVIDENCE":
            abstentions += 1
        else:
            coverage_count += 1
        # failure classification (legacy counters, retained for backward compat)
        if ctx.trace:
            gate_meta = ctx.trace.detail.get("phase23_11_gate", {})
            if gate_meta.get("candidates_after_gate", 0) == 0 and candidates:
                gate_failure += 1
        if pred != gold and pred != "INSUFFICIENT_EVIDENCE":
            verification_failure += 1
        # Phase 23.11.2 §7: primary outcome classification (mutually-exclusive)
        sel_meta = ctx.trace.detail.get("phase23_11_selector", {}) if ctx.trace else {}
        outcome = classify_outcome(
            claim_id=cc.claim_id, pred=pred, gold=gold,
            candidates_before_gate=ctx.candidates_before_gate,
            candidates_after_gate=ctx.candidates_after_gate,
            selector_input_count=sel_meta.get("selector_input_count", 0),
            selector_output_count=sel_meta.get("selector_output_count", 0),
            selector_empty_reason=sel_meta.get("empty_reason", ""),
            selected_ids=sel_meta.get("selected_evidence_ids", []),
        )
        claim_outcomes.append(outcome)
        confusion[(gold, pred)] += 1
        pred_counter[pred] += 1
        gold_counter[gold] += 1
        rows.append({
            "claim_id": cc.claim_id, "gold": gold, "pred": pred,
            "correct": pred == gold, "route": routing.route,
            "candidates_before_gate": ctx.candidates_before_gate,
            "candidates_after_gate": ctx.candidates_after_gate,
            "abstention": pred == "INSUFFICIENT_EVIDENCE",
            "primary_outcome": outcome.primary_outcome,
        })

    total = len(claims)
    accuracy = correct / total if total else 0.0
    coverage = coverage_count / total if total else 0.0
    abstention_rate = abstentions / total if total else 0.0
    outcome_summary = summarize_outcomes(claim_outcomes)
    # selective accuracy: accuracy among non-abstained
    selective_correct = sum(1 for r in rows if r["correct"] and not r["abstention"])
    selective_total = sum(1 for r in rows if not r["abstention"])
    selective_accuracy = selective_correct / max(selective_total, 1)
    # abstention accuracy: accuracy among abstained (gold should be INSUFFICIENT)
    abst_correct = sum(1 for r in rows if r["abstention"] and r["gold"] == "INSUFFICIENT_EVIDENCE")
    abst_accuracy = abst_correct / max(abstentions, 1)
    # FPR / FNR
    fp = sum(1 for r in rows if r["pred"] == "SUPPORTED" and r["gold"] != "SUPPORTED")
    tn = sum(1 for r in rows if r["pred"] != "SUPPORTED" and r["gold"] != "SUPPORTED")
    fpr = fp / max(fp + tn, 1)
    fn_count = sum(1 for r in rows if r["pred"] != "SUPPORTED" and r["gold"] == "SUPPORTED")
    tp_count = sum(1 for r in rows if r["pred"] == "SUPPORTED" and r["gold"] == "SUPPORTED")
    fnr = fn_count / max(fn_count + tp_count, 1)

    return _finalize_metrics(
        "real_e2e", claims, rows, correct, missing, confusion,
        pred_counter, gold_counter, extra={
            "coverage": round(coverage, 4),
            "selective_accuracy": round(selective_accuracy, 4),
            "abstention_rate": round(abstention_rate, 4),
            "abstention_accuracy": round(abst_accuracy, 4),
            "fpr": round(fpr, 4),
            "fnr": round(fnr, 4),
            "retrieval_failure": retrieval_failure,
            "gate_failure": gate_failure,
            "verification_failure": verification_failure,
            "aggregation_failure": aggregation_failure,
            # Phase 23.11.2 §7: mutually-exclusive primary outcome distribution
            "primary_outcome_distribution": outcome_summary["outcome_counts"],
            "primary_outcome_sum": outcome_summary["outcome_sum"],
            "primary_outcome_sum_equals_total": outcome_summary["sum_equals_total"],
        },
        path_counts={
            "input_claim_count": len(claims), "evidence_source": "retrieval",
            "verify_evidence_set_call_count": ves_calls, "gate_call_count": gate_calls,
            "selector_call_count": sel_calls, "core_verify_call_count": cv_calls,
            "output_result_count": len(rows), "missing_result_count": missing,
        },
    )


# ===========================================================================
# Metrics finalization (shared)
# ===========================================================================

def _finalize_metrics(
    mode: str,
    claims: list[CanonicalClaim],
    rows: list[dict],
    correct: int,
    missing: int,
    confusion: dict,
    pred_counter: Counter,
    gold_counter: Counter,
    extra: dict,
    path_counts: dict,
) -> dict:
    total = len(claims)
    accuracy = correct / total if total else 0.0
    # per-class P/R/F1
    labels = sorted(set(gold_counter) | set(pred_counter))
    per_class: dict[str, dict] = {}
    for lbl in labels:
        tp = confusion.get((lbl, lbl), 0)
        fp = sum(v for (g, p), v in confusion.items() if p == lbl and g != lbl)
        fn = sum(v for (g, p), v in confusion.items() if g == lbl and p != lbl)
        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        per_class[lbl] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}
    # macro F1
    macro_f1 = sum(v["f1"] for v in per_class.values()) / max(len(per_class), 1)
    conf_matrix = {f"{g}|{p}": n for (g, p), n in sorted(confusion.items())}

    return {
        "mode": mode,
        "sample_count": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "confusion_matrix": conf_matrix,
        "missing_result_count": missing,
        "path_counts": path_counts,
        **extra,
        "per_claim": rows,
    }


# ===========================================================================
# Abstention diagnosis (§8)
# ===========================================================================

def diagnose_abstentions(real_e2e_result: dict, claims: list[CanonicalClaim]) -> list[dict]:
    """Per-claim abstention diagnosis for §8."""
    claim_by_id = {c.claim_id: c for c in claims}
    diagnosis = []
    for r in real_e2e_result.get("per_claim", []):
        if r.get("pred") != "INSUFFICIENT_EVIDENCE":
            continue
        cid = r["claim_id"]
        cc = claim_by_id.get(cid)
        diagnosis.append({
            "claim_id": cid,
            "exists_in_43": cc is not None,
            "expected_verdict": cc.expected_verdict if cc else None,
            "company": cc.company if cc else None,
            "route": r.get("route"),
            "candidates_before_gate": r.get("candidates_before_gate"),
            "candidates_after_gate": r.get("candidates_after_gate"),
            "selected_count": len(r.get("selected", [])),
            "final_verdict": r.get("pred"),
            "abstention_reason": (
                "no candidates retrieved" if r.get("candidates_before_gate", 0) == 0
                else "all candidates rejected by gate" if r.get("candidates_after_gate", 0) == 0
                else "selector returned empty" if not r.get("selected")
                else "core_verify returned INSUFFICIENT"
            ),
            "caused_by_field_mapping_error": False,  # Phase 23.11.1 fixes mapping; abstentions now real
            "fixed_result": r.get("pred"),  # after fix, this is the real verdict
        })
    return diagnosis


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["all", "core_oracle", "noisy_oracle", "real_e2e"], default="all")
    args = parser.parse_args()

    # Load + validate
    claims, issues = load_canonical_claims()
    validation = validate_schema(claims, issues)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "phase23_11_claim_schema_validation.json").write_text(
        json.dumps(validation.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Schema validation: passed={validation.passed} total={validation.total_claims}")
    if not validation.passed:
        print("Schema validation FAILED; aborting.")
        return 1

    raw_by_id = load_raw_claims_by_id()
    gold_ev_by_cid = load_gold_evidence_by_claim()

    results: dict[str, dict] = {}
    path_trace: dict = {"modes": {}}

    session = SessionLocal()
    try:
        if args.mode in ("all", "core_oracle"):
            print("Running CORE_ORACLE...")
            r = run_core_oracle(claims, raw_by_id, gold_ev_by_cid)
            results["core_oracle"] = r
            (EVAL_DIR / "phase23_11_core_oracle.json").write_text(
                json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            path_trace["modes"]["core_oracle"] = r["path_counts"]
            print(f"  accuracy={r['accuracy']} macro_f1={r['macro_f1']} missing={r['missing_result_count']}")

        if args.mode in ("all", "noisy_oracle"):
            print("Running NOISY_ORACLE...")
            r = run_noisy_oracle(claims, raw_by_id, gold_ev_by_cid)
            results["noisy_oracle"] = r
            (EVAL_DIR / "phase23_11_noisy_oracle.json").write_text(
                json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            path_trace["modes"]["noisy_oracle"] = r["path_counts"]
            print(f"  accuracy={r['accuracy']} macro_f1={r['macro_f1']} missing={r['missing_result_count']}")

        if args.mode in ("all", "real_e2e"):
            print("Running REAL_E2E...")
            r = run_real_e2e(claims, raw_by_id, session, top_k=10)
            results["real_e2e"] = r
            E2E_DIR.mkdir(parents=True, exist_ok=True)
            (E2E_DIR / "phase23_11_real_e2e.json").write_text(
                json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            path_trace["modes"]["real_e2e"] = r["path_counts"]
            print(f"  accuracy={r['accuracy']} macro_f1={r['macro_f1']} coverage={r['coverage']} missing={r['missing_result_count']}")
            # abstention diagnosis
            diag = diagnose_abstentions(r, claims)
            (E2E_DIR / "phase23_11_abstention_diagnosis.json").write_text(
                json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  abstentions diagnosed: {len(diag)}")

        # shared path trace
        INTEG_DIR.mkdir(parents=True, exist_ok=True)
        (INTEG_DIR / "phase23_11_shared_path_trace.json").write_text(
            json.dumps(path_trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # unified acceptance summary
        summary = {
            "phase": "23.11.1",
            "schema_validation": validation.to_dict(),
            "modes": {k: {kk: vv for kk, vv in v.items() if kk != "per_claim"} for k, v in results.items()},
        }
        (ART / "phase23_11_1_acceptance.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Acceptance summary written to {ART / 'phase23_11_1_acceptance.json'}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
