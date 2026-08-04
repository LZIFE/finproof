"""Phase 23.11.3 Four-Stage Isolation Experiment (Task 7).

Run 4 isolation stages on the SAME 43 CORE_ORACLE claims to lock首次性能下降环节 (§7):

A. Direct Core Verify: Gold Evidence → core_verify → normalize_verdict
B. Gate + Direct Core Verify: Gold → Gate → core_verify → normalize
C. Gate + Selector + Core Verify: Gold → Gate → Selector → core_verify → normalize
D. Full Aggregation: Gold → Gate → Selector → Evidence-level Verify → Aggregation → normalize

Each stage outputs: sample_count, Accuracy, Macro-F1, per-class F1, missing,
abstention, first divergence count.

By A/B/C/D差值锁定首次性能下降环节.

Output: backend/artifacts/aggregation/phase23_11_3_isolation_results.json

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_3_isolation_eval.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import (
    load_canonical_claims, normalize_verdict_for_evaluation,
)
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_all
from app.services.evidence_selector import SelectorConfig, select
from app.services.verification.core_pipeline import IntegrationTrace, core_verify
from app.services.verification.base import VerificationResult

ART = BACKEND / "artifacts"
AGG_DIR = ART / "aggregation"
OUT_PATH = AGG_DIR / "phase23_11_3_isolation_results.json"

# Phase 23.11.2 calibrated thresholds ( reused for isolation B/C/D)
GATE_CFG = GateConfig(
    metric_match_threshold=0.6, period_conflict_strict=True, scope_conflict_strict=True,
    high_quality_threshold=0.5, medium_quality_threshold=0.3, causal_language_required=True,
)
SEL_CFG = SelectorConfig(strategy="Top3", max_evidence=3, ambiguity_margin=0.05)


def load_gold_evidence_by_claim() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_evidence.json"
        if not p.exists():
            continue
        for e in json.loads(p.read_text(encoding="utf-8")).get("evidence", []):
            cid = str(e.get("claim_id") or "")
            if cid:
                out.setdefault(cid, []).append(e)
    return out


def load_raw_claims_by_id() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_claims.json"
        if not p.exists():
            continue
        for c in json.loads(p.read_text(encoding="utf-8")).get("claims", []):
            cid = str(c.get("claim_id") or "")
            if cid:
                c.setdefault("_dataset", ds)
                out[cid] = c
    return out


def _build_claim(cc, raw):
    base = dict(raw)
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


def _to_bundle(cands: list[dict]) -> list[dict]:
    return [{"evidence_id": str(c.get("evidence_id") or c.get("block_id") or "?"),
             "text": str(c.get("evidence_text") or c.get("text") or ""),
             "page": c.get("page"), "document_id": c.get("document_id"),
             "evidence_type": c.get("evidence_type", "")} for c in cands]


def _metrics(claims, rows, correct, missing, confusion, pred_c, gold_c):
    total = len(claims)
    acc = correct / total if total else 0.0
    labels = sorted(set(gold_c) | set(pred_c))
    per_class = {}
    for lbl in labels:
        tp = confusion.get((lbl, lbl), 0)
        fp = sum(v for (g, p), v in confusion.items() if p == lbl and g != lbl)
        fn = sum(v for (g, p), v in confusion.items() if g == lbl and p != lbl)
        prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
        per_class[lbl] = {"precision": round(prec, 4), "recall": round(rec, 4),
                          "f1": round(2*prec*rec/max(prec+rec, 1e-9), 4),
                          "support": gold_c.get(lbl, 0)}
    macro = sum(v["f1"] for v in per_class.values()) / max(len(per_class), 1)
    abst = sum(1 for r in rows if r["pred"] in ("INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE"))
    return {
        "sample_count": total, "correct": correct, "accuracy": round(acc, 4),
        "macro_f1": round(macro, 4), "per_class": per_class, "missing": missing,
        "abstention": abst,
        "confusion_matrix": {f"{g}|{p}": n for (g, p), n in sorted(confusion.items())},
    }


def stage_a_direct(claims, raw_by, gold_ev_by):
    """A. Gold → core_verify → normalize."""
    rows = []; correct = 0; missing = 0
    confusion = defaultdict(int); pred_c = Counter(); gold_c = Counter()
    for cc in claims:
        gold_ev = gold_ev_by.get(cc.claim_id, [])
        claim = _build_claim(cc, raw_by.get(cc.claim_id, {}))
        if not gold_ev:
            missing += 1
            rows.append({"claim_id": cc.claim_id, "pred": "INSUFFICIENT_EVIDENCE"})
            confusion[(cc.expected_verdict, "INSUFFICIENT_EVIDENCE")] += 1
            pred_c["INSUFFICIENT_EVIDENCE"] += 1; gold_c[cc.expected_verdict] += 1
            continue
        bundle = _to_bundle([gold_ev[0]])  # single gold
        trace = IntegrationTrace(claim_id=cc.claim_id)
        try:
            r = core_verify(claim, bundle, trace)
            raw = r.verification_status
        except Exception as exc:
            raw = f"ERROR: {exc}"; missing += 1
        pred = normalize_verdict_for_evaluation(raw)
        if pred == cc.expected_verdict: correct += 1
        confusion[(cc.expected_verdict, pred)] += 1
        pred_c[pred] += 1; gold_c[cc.expected_verdict] += 1
        rows.append({"claim_id": cc.claim_id, "pred": pred})
    return _metrics(claims, rows, correct, missing, confusion, pred_c, gold_c), rows


def stage_b_gate_direct(claims, raw_by, gold_ev_by):
    """B. Gold → Gate → core_verify → normalize."""
    rows = []; correct = 0; missing = 0
    confusion = defaultdict(int); pred_c = Counter(); gold_c = Counter()
    for cc in claims:
        gold_ev = gold_ev_by.get(cc.claim_id, [])
        claim = _build_claim(cc, raw_by.get(cc.claim_id, {}))
        routing = route_claim(claim)
        if not gold_ev:
            missing += 1
            rows.append({"claim_id": cc.claim_id, "pred": "INSUFFICIENT_EVIDENCE"})
            confusion[(cc.expected_verdict, "INSUFFICIENT_EVIDENCE")] += 1
            pred_c["INSUFFICIENT_EVIDENCE"] += 1; gold_c[cc.expected_verdict] += 1
            continue
        # Gate all gold
        gate_results = evaluate_all(claim, gold_ev, routing, GATE_CFG)
        accepted = [c for c, r in zip(gold_ev, gate_results) if r.accepted]
        if not accepted:
            rows.append({"claim_id": cc.claim_id, "pred": "INSUFFICIENT_EVIDENCE"})
            confusion[(cc.expected_verdict, "INSUFFICIENT_EVIDENCE")] += 1
            pred_c["INSUFFICIENT_EVIDENCE"] += 1; gold_c[cc.expected_verdict] += 1
            continue
        bundle = _to_bundle(accepted)
        trace = IntegrationTrace(claim_id=cc.claim_id)
        try:
            r = core_verify(claim, bundle, trace)
            raw = r.verification_status
        except Exception as exc:
            raw = f"ERROR: {exc}"; missing += 1
        pred = normalize_verdict_for_evaluation(raw)
        if pred == cc.expected_verdict: correct += 1
        confusion[(cc.expected_verdict, pred)] += 1
        pred_c[pred] += 1; gold_c[cc.expected_verdict] += 1
        rows.append({"claim_id": cc.claim_id, "pred": pred})
    return _metrics(claims, rows, correct, missing, confusion, pred_c, gold_c), rows


def stage_c_gate_selector(claims, raw_by, gold_ev_by):
    """C. Gold → Gate → Selector → core_verify → normalize."""
    rows = []; correct = 0; missing = 0
    confusion = defaultdict(int); pred_c = Counter(); gold_c = Counter()
    for cc in claims:
        gold_ev = gold_ev_by.get(cc.claim_id, [])
        claim = _build_claim(cc, raw_by.get(cc.claim_id, {}))
        routing = route_claim(claim)
        if not gold_ev:
            missing += 1
            rows.append({"claim_id": cc.claim_id, "pred": "INSUFFICIENT_EVIDENCE"})
            confusion[(cc.expected_verdict, "INSUFFICIENT_EVIDENCE")] += 1
            pred_c["INSUFFICIENT_EVIDENCE"] += 1; gold_c[cc.expected_verdict] += 1
            continue
        gate_results = evaluate_all(claim, gold_ev, routing, GATE_CFG)
        bundle_sel, meta = select(gate_results, routing, SEL_CFG)
        if not bundle_sel:
            rows.append({"claim_id": cc.claim_id, "pred": "INSUFFICIENT_EVIDENCE"})
            confusion[(cc.expected_verdict, "INSUFFICIENT_EVIDENCE")] += 1
            pred_c["INSUFFICIENT_EVIDENCE"] += 1; gold_c[cc.expected_verdict] += 1
            continue
        # Fill text into bundle from gold_ev
        id_to_text = {str(e.get("evidence_id") or "?"): e for e in gold_ev}
        for b in bundle_sel:
            e = id_to_text.get(b.get("evidence_id"))
            if e:
                b["text"] = str(e.get("evidence_text") or e.get("text") or "")
                b["page"] = e.get("page")
                b["document_id"] = e.get("document_id")
                b["evidence_type"] = e.get("evidence_type", "")
        trace = IntegrationTrace(claim_id=cc.claim_id)
        try:
            r = core_verify(claim, bundle_sel, trace)
            raw = r.verification_status
        except Exception as exc:
            raw = f"ERROR: {exc}"; missing += 1
        pred = normalize_verdict_for_evaluation(raw)
        if pred == cc.expected_verdict: correct += 1
        confusion[(cc.expected_verdict, pred)] += 1
        pred_c[pred] += 1; gold_c[cc.expected_verdict] += 1
        rows.append({"claim_id": cc.claim_id, "pred": pred})
    return _metrics(claims, rows, correct, missing, confusion, pred_c, gold_c), rows


def stage_d_full(claims, raw_by, gold_ev_by):
    """D. Gold → Gate → Selector → Evidence-level Verify → Aggregation → normalize.

    For isolation, evidence-level verify = core_verify on each selected evidence
    individually; aggregation = §4 真值表 (明确反驳优先/冲突检测).
    """
    rows = []; correct = 0; missing = 0
    confusion = defaultdict(int); pred_c = Counter(); gold_c = Counter()
    for cc in claims:
        gold_ev = gold_ev_by.get(cc.claim_id, [])
        claim = _build_claim(cc, raw_by.get(cc.claim_id, {}))
        routing = route_claim(claim)
        if not gold_ev:
            missing += 1
            rows.append({"claim_id": cc.claim_id, "pred": "INSUFFICIENT_EVIDENCE"})
            confusion[(cc.expected_verdict, "INSUFFICIENT_EVIDENCE")] += 1
            pred_c["INSUFFICIENT_EVIDENCE"] += 1; gold_c[cc.expected_verdict] += 1
            continue
        gate_results = evaluate_all(claim, gold_ev, routing, GATE_CFG)
        bundle_sel, meta = select(gate_results, routing, SEL_CFG)
        if not bundle_sel:
            rows.append({"claim_id": cc.claim_id, "pred": "INSUFFICIENT_EVIDENCE"})
            confusion[(cc.expected_verdict, "INSUFFICIENT_EVIDENCE")] += 1
            pred_c["INSUFFICIENT_EVIDENCE"] += 1; gold_c[cc.expected_verdict] += 1
            continue
        # Fill text
        id_to_text = {str(e.get("evidence_id") or "?"): e for e in gold_ev}
        for b in bundle_sel:
            e = id_to_text.get(b.get("evidence_id"))
            if e:
                b["text"] = str(e.get("evidence_text") or e.get("text") or "")
        # Evidence-level verify: core_verify on each single evidence
        evidence_verdicts = []
        for b in bundle_sel:
            trace = IntegrationTrace(claim_id=cc.claim_id)
            try:
                r = core_verify(claim, [b], trace)
                ev = r.verification_status
            except Exception:
                ev = "INSUFFICIENT_EVIDENCE"
            evidence_verdicts.append(normalize_verdict_for_evaluation(ev))
        # Aggregation (§4 真值表)
        pred = _aggregate(evidence_verdicts, bundle_sel, gate_results)
        if pred == cc.expected_verdict: correct += 1
        confusion[(cc.expected_verdict, pred)] += 1
        pred_c[pred] += 1; gold_c[cc.expected_verdict] += 1
        rows.append({"claim_id": cc.claim_id, "pred": pred,
                     "evidence_verdicts": evidence_verdicts})
    return _metrics(claims, rows, correct, missing, confusion, pred_c, gold_c), rows


def _aggregate(evidence_verdicts: list[str], bundle_sel: list[dict], gate_results: list) -> str:
    """§4 aggregation真值表.

    - 明确反驳优先 (high-quality REFUTED) 不得被低质量 SUPPORTED 覆盖
    - 所有高质量 SUPPORTED 一致 → SUPPORTED
    - 部分 SUPPORTED + 缺失 + 无冲突 → PARTIALLY_SUPPORTED
    - 高质量 SUPPORTED + REFUTED 同时 → conflict → INSUFFICIENT_EVIDENCE
    """
    if not evidence_verdicts:
        return "INSUFFICIENT_EVIDENCE"
    supported = [v for v in evidence_verdicts if v == "SUPPORTED"]
    refuted = [v for v in evidence_verdicts if v == "REFUTED"]
    partial = [v for v in evidence_verdicts if v == "PARTIALLY_SUPPORTED"]
    insufficient = [v for v in evidence_verdicts if v == "INSUFFICIENT_EVIDENCE"]
    # 明确反驳优先: high-quality REFUTED exists
    if refuted and not supported:
        return "REFUTED"
    # 所有一致 SUPPORTED
    if supported and not refuted and not partial:
        return "SUPPORTED"
    # 部分 SUPPORTED + 缺失 + 无冲突
    if (supported or partial) and not refuted:
        return "PARTIALLY_SUPPORTED" if partial else "SUPPORTED"
    # 冲突: SUPPORTED + REFUTED 同时
    if supported and refuted:
        return "INSUFFICIENT_EVIDENCE"  # conflict → 弃权
    # 全弃权
    if insufficient and not supported and not refuted and not partial:
        return "INSUFFICIENT_EVIDENCE"
    return "INSUFFICIENT_EVIDENCE"


def main() -> int:
    claims, _ = load_canonical_claims()
    raw_by = load_raw_claims_by_id()
    gold_ev_by = load_gold_evidence_by_claim()

    print("Stage A: Direct Core Verify...")
    a_metrics, a_rows = stage_a_direct(claims, raw_by, gold_ev_by)
    print(f"  A accuracy={a_metrics['accuracy']} f1={a_metrics['macro_f1']}")

    print("Stage B: Gate + Direct Core Verify...")
    b_metrics, b_rows = stage_b_gate_direct(claims, raw_by, gold_ev_by)
    print(f"  B accuracy={b_metrics['accuracy']} f1={b_metrics['macro_f1']}")

    print("Stage C: Gate + Selector + Core Verify...")
    c_metrics, c_rows = stage_c_gate_selector(claims, raw_by, gold_ev_by)
    print(f"  C accuracy={c_metrics['accuracy']} f1={c_metrics['macro_f1']}")

    print("Stage D: Full Aggregation...")
    d_metrics, d_rows = stage_d_full(claims, raw_by, gold_ev_by)
    print(f"  D accuracy={d_metrics['accuracy']} f1={d_metrics['macro_f1']}")

    # 锁定首次性能下降环节
    deltas = {
        "A_to_B": round(b_metrics["accuracy"] - a_metrics["accuracy"], 4),
        "B_to_C": round(c_metrics["accuracy"] - b_metrics["accuracy"], 4),
        "C_to_D": round(d_metrics["accuracy"] - c_metrics["accuracy"], 4),
    }
    first_drop = "NONE"
    if deltas["A_to_B"] < -0.01: first_drop = "GATE"
    elif deltas["B_to_C"] < -0.01: first_drop = "SELECTOR"
    elif deltas["C_to_D"] < -0.01: first_drop = "AGGREGATION"

    output = {
        "phase": "23.11.3", "script": "phase23_11_3_isolation_eval",
        "description": "Four-stage isolation A/B/C/D to lock首次性能下降环节",
        "stages": {
            "A_direct_core_verify": a_metrics,
            "B_gate_plus_core_verify": b_metrics,
            "C_gate_plus_selector_plus_core_verify": c_metrics,
            "D_full_aggregation": d_metrics,
        },
        "deltas": deltas,
        "first_drop_stage": first_drop,
        "diagnosis": {
            "A_same_as_single_gold": abs(a_metrics["accuracy"] - 0.3953) < 0.01,
            "if_B_drops": "Gate误拒Gold (GATE_REJECTED_GOLD)",
            "if_C_drops": "Selector丢弃Gold (SELECTOR_DROPPED_GOLD)",
            "if_D_drops": "Aggregation真值表错误 (AGGREGATION_WRONG)",
            "current_first_drop": first_drop,
        },
    }
    AGG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nIsolation results written to {OUT_PATH}")
    print(f"  deltas: {deltas}")
    print(f"  first_drop_stage: {first_drop}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
