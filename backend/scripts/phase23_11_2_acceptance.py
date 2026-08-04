"""Phase 23.11.2 Unified Acceptance (Task 9).

Runs CORE_ORACLE / NOISY_ORACLE / REAL_E2E on the SAME 43 claims with the
Phase 23.11.2 calibrated thresholds (§8 chosen: medium=0.3 / high=0.5 /
ambiguity_margin=0.05) and the three-state Gate + fixed Selector.

Outputs:
- backend/artifacts/phase23_11_2_acceptance.json
- backend/artifacts/e2e/phase23_11_2_real_e2e.json
- backend/artifacts/evidence_gate/phase23_11_2_gate_metrics.json (refreshed)

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_2_acceptance.py --mode all
    cd backend && PYTHONPATH=. python scripts/phase23_11_2_acceptance.py --mode core_oracle
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
    load_canonical_claims, normalize_verdict, validate_schema,
)
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_all
from app.services.evidence_selector import SelectorConfig, select
from app.services.verification_context import VerificationContext
from app.services.verification.verification_service import verify_evidence_set
from app.services.verification.base import VerificationResult
from app.services.failure_attribution import classify_outcome, summarize_outcomes

ART = BACKEND / "artifacts"
EVAL_DIR = ART / "evaluation"
E2E_DIR = ART / "e2e"
GATE_DIR = ART / "evidence_gate"

# Phase 23.11.2 §8 calibrated thresholds (leave-one-company-out Pareto)
CALIBRATED = GateConfig(
    metric_match_threshold=0.6,       # retained (unused under three-state)
    period_conflict_strict=True,
    scope_conflict_strict=True,
    high_quality_threshold=0.5,       # §8 chosen
    medium_quality_threshold=0.3,     # §8 chosen (lowered from 0.4)
    causal_language_required=True,
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


def _make_claim(cc, raw):
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


def _hard_negs(claim, gold_ev):
    negs = []
    period = claim.get("period") or "2025FY"
    metric = claim.get("metric") or "revenue"
    scope = claim.get("scope") or "consolidated"
    value = claim.get("value")
    wp = "2023FY" if "2025" in period else "2025FY"
    negs.append({"evidence_id": f"NEG-WP-{claim['claim_id']}", "text": f"{metric} {value} {wp}", "page": 5, "document_id": 1})
    wm = "net_profit" if metric == "revenue" else "revenue"
    negs.append({"evidence_id": f"NEG-WM-{claim['claim_id']}", "text": f"{wm} {value} {period}", "page": 5, "document_id": 1})
    ws = "parent_attributable" if scope == "consolidated" else "consolidated"
    negs.append({"evidence_id": f"NEG-WS-{claim['claim_id']}", "text": f"({ws}) {metric} {value} {period}", "page": 5, "document_id": 1})
    return negs


def _finalize(mode, claims, rows, correct, missing, confusion, pred_c, gold_c, extra, path):
    total = len(claims)
    acc = correct / total if total else 0.0
    labels = sorted(set(gold_c) | set(pred_c))
    per_class = {}
    for lbl in labels:
        tp = confusion.get((lbl, lbl), 0)
        fp = sum(v for (g, p), v in confusion.items() if p == lbl and g != lbl)
        fn = sum(v for (g, p), v in confusion.items() if g == lbl and p != lbl)
        prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
        per_class[lbl] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(2*prec*rec/max(prec+rec,1e-9), 4)}
    macro = sum(v["f1"] for v in per_class.values()) / max(len(per_class), 1)
    return {
        "mode": mode, "sample_count": total, "correct": correct,
        "accuracy": round(acc, 4), "macro_f1": round(macro, 4),
        "per_class": per_class,
        "confusion_matrix": {f"{g}|{p}": n for (g, p), n in sorted(confusion.items())},
        "missing_result_count": missing, "path_counts": path, **extra,
        "per_claim": rows,
    }


def run_core_oracle(claims, raw_by, gold_ev_by):
    rows = []; correct = 0; missing = 0
    confusion = defaultdict(int); pred_c = Counter(); gold_c = Counter()
    gate_rejected_gold = 0; gold_selected = 0; selector_empty = 0
    ves = gate = sel = cv = 0
    for cc in claims:
        claim = _make_claim(cc, raw_by.get(cc.claim_id, {}))
        routing = route_claim(claim)
        gold_ev = gold_ev_by.get(cc.claim_id, [])
        ctx = VerificationContext("core_oracle", CALIBRATED, SEL_CFG)
        try:
            r = verify_evidence_set(claim, list(gold_ev), routing, ctx)
            ves += 1; gate += 1; sel += 1; cv += 1
        except Exception as exc:
            r = VerificationResult(cc.claim_id, "INSUFFICIENT_EVIDENCE", 0.2, f"error: {exc}")
            missing += 1
        pred = normalize_verdict(r.verification_status); gold = cc.expected_verdict
        if pred == gold: correct += 1
        gr = ctx.trace.detail.get("phase23_11_gate", {}).get("gate_results", []) if ctx.trace else []
        gold_acc = any(x.get("accepted") for x in gr) if gr else False
        if gold_ev and not gold_acc: gate_rejected_gold += 1
        sm = ctx.trace.detail.get("phase23_11_selector", {}) if ctx.trace else {}
        if sm.get("selector_output_count", 0) == 0 and sm.get("selector_input_count", 0) > 0: selector_empty += 1
        if any(str(x) in [str(e.get("evidence_id")) for e in gold_ev] for x in sm.get("selected_evidence_ids", [])): gold_selected += 1
        confusion[(gold, pred)] += 1; pred_c[pred] += 1; gold_c[gold] += 1
        rows.append({"claim_id": cc.claim_id, "gold": gold, "pred": pred, "correct": pred == gold, "gold_accepted": gold_acc, "selected": sm.get("selected_evidence_ids", [])})
    total = len(claims)
    return _finalize("core_oracle", claims, rows, correct, missing, confusion, pred_c, gold_c, {
        "gold_gate_acceptance_rate": round((total - gate_rejected_gold) / max(total, 1), 4),
        "gold_selection_rate": round(gold_selected / max(total, 1), 4),
        "rejected_gold_rate": round(gate_rejected_gold / max(total, 1), 4),
        "selector_empty_rate": round(selector_empty / max(total, 1), 4),
        "gate_rejected_gold_count": gate_rejected_gold,
    }, {"input_claim_count": total, "evidence_source": "gold", "verify_evidence_set_call_count": ves, "gate_call_count": gate, "selector_call_count": sel, "core_verify_call_count": cv, "output_result_count": len(rows), "missing_result_count": missing})


def run_noisy_oracle(claims, raw_by, gold_ev_by):
    rows = []; correct = 0; missing = 0
    confusion = defaultdict(int); pred_c = Counter(); gold_c = Counter()
    tp = fn = noise_acc = noise_tot = 0; gold_top1 = gold_top3 = 0; acc_count = 0
    ves = gate = sel = cv = 0
    for cc in claims:
        claim = _make_claim(cc, raw_by.get(cc.claim_id, {}))
        routing = route_claim(claim)
        gold_ev = gold_ev_by.get(cc.claim_id, [])
        negs = _hard_negs(claim, gold_ev)
        cands = list(gold_ev) + negs; noise_tot += len(negs)
        ctx = VerificationContext("noisy_oracle", CALIBRATED, SEL_CFG)
        try:
            r = verify_evidence_set(claim, cands, routing, ctx)
            ves += 1; gate += 1; sel += 1; cv += 1
        except Exception as exc:
            r = VerificationResult(cc.claim_id, "INSUFFICIENT_EVIDENCE", 0.2, f"error: {exc}")
            missing += 1
        pred = normalize_verdict(r.verification_status); gold = cc.expected_verdict
        if pred == gold: correct += 1
        gr = ctx.trace.detail.get("phase23_11_gate", {}).get("gate_results", []) if ctx.trace else []
        geids = {str(e.get("evidence_id")) for e in gold_ev}; neids = {str(n.get("evidence_id")) for n in negs}
        gold_acc = any(x.get("accepted") and x.get("evidence_id") in geids for x in gr)
        if gold_ev:
            if gold_acc: tp += 1
            else: fn += 1
        noise_acc += sum(1 for x in gr if x.get("accepted") and x.get("evidence_id") in neids)
        acc_count += sum(1 for x in gr if x.get("accepted"))
        sm = ctx.trace.detail.get("phase23_11_selector", {}) if ctx.trace else {}
        sids = [str(x) for x in sm.get("selected_evidence_ids", [])]
        if sids and sids[0] in geids: gold_top1 += 1
        if any(x in geids for x in sids[:3]): gold_top3 += 1
        confusion[(gold, pred)] += 1; pred_c[pred] += 1; gold_c[gold] += 1
        rows.append({"claim_id": cc.claim_id, "gold": gold, "pred": pred, "correct": pred == gold, "gold_accepted": gold_acc, "noise_accepted": sum(1 for x in gr if x.get("accepted") and x.get("evidence_id") in neids), "selected": sids})
    total = len(claims)
    return _finalize("noisy_oracle", claims, rows, correct, missing, confusion, pred_c, gold_c, {
        "gate_precision": round(tp / max(tp + noise_acc, 1), 4),
        "gate_recall": round(tp / max(tp + fn, 1), 4),
        "accepted_noise_rate": round(noise_acc / max(noise_tot, 1), 4),
        "rejected_gold_rate": round(fn / max(tp + fn, 1), 4),
        "gold_top1_rate": round(gold_top1 / max(total, 1), 4),
        "gold_top3_rate": round(gold_top3 / max(total, 1), 4),
        "average_accepted_evidence_count": round(acc_count / max(total, 1), 4),
    }, {"input_claim_count": total, "evidence_source": "gold+negatives", "verify_evidence_set_call_count": ves, "gate_call_count": gate, "selector_call_count": sel, "core_verify_call_count": cv, "output_result_count": len(rows), "missing_result_count": missing})


def run_real_e2e(claims, raw_by, session, top_k=10):
    rows = []; correct = 0; missing = 0; abst = 0; cov = 0
    confusion = defaultdict(int); pred_c = Counter(); gold_c = Counter()
    rf = gf = vf = af = 0; outcomes = []
    ves = gate = sel = cv = 0
    from app.services.evidence_retrieval.service import retrieve_for_claim
    for cc in claims:
        claim = _make_claim(cc, raw_by.get(cc.claim_id, {}))
        routing = route_claim(claim)
        ctx = VerificationContext("real_e2e", CALIBRATED, SEL_CFG)
        try:
            cands_raw = retrieve_for_claim(session, claim, top_k=top_k)
            cands = [{"evidence_id": str(c.get("block_id") or "?"), "block_id": c.get("block_id"), "text": c.get("block_text", "") or "", "page": c.get("page_number"), "document_id": c.get("document_id")} for c in cands_raw]
        except Exception:
            cands = []; rf += 1
        if not cands: rf += 1
        try:
            r = verify_evidence_set(claim, cands, routing, ctx)
            ves += 1; gate += 1; sel += 1; cv += 1
        except Exception as exc:
            r = VerificationResult(cc.claim_id, "INSUFFICIENT_EVIDENCE", 0.2, f"error: {exc}")
            missing += 1
        pred = normalize_verdict(r.verification_status); gold = cc.expected_verdict
        if pred == gold: correct += 1
        if pred == "INSUFFICIENT_EVIDENCE": abst += 1
        else: cov += 1
        sm = ctx.trace.detail.get("phase23_11_selector", {}) if ctx.trace else {}
        if ctx.trace and ctx.trace.detail.get("phase23_11_gate", {}).get("candidates_after_gate", 0) == 0 and cands: gf += 1
        if pred != gold and pred != "INSUFFICIENT_EVIDENCE": vf += 1
        outcome = classify_outcome(cc.claim_id, pred, gold, ctx.candidates_before_gate, ctx.candidates_after_gate, sm.get("selector_input_count", 0), sm.get("selector_output_count", 0), sm.get("empty_reason", ""), selected_ids=sm.get("selected_evidence_ids", []))
        outcomes.append(outcome)
        confusion[(gold, pred)] += 1; pred_c[pred] += 1; gold_c[gold] += 1
        rows.append({"claim_id": cc.claim_id, "gold": gold, "pred": pred, "correct": pred == gold, "abstention": pred == "INSUFFICIENT_EVIDENCE", "candidates_before_gate": ctx.candidates_before_gate, "candidates_after_gate": ctx.candidates_after_gate, "primary_outcome": outcome.primary_outcome})
    total = len(claims)
    acc = correct / total if total else 0.0
    coverage = cov / total if total else 0.0
    abst_rate = abst / total if total else 0.0
    sel_correct = sum(1 for r in rows if r["correct"] and not r["abstention"])
    sel_total = sum(1 for r in rows if not r["abstention"])
    abst_correct = sum(1 for r in rows if r["abstention"] and r["gold"] == "INSUFFICIENT_EVIDENCE")
    fp = sum(1 for r in rows if r["pred"] == "SUPPORTED" and r["gold"] != "SUPPORTED")
    tn = sum(1 for r in rows if r["pred"] != "SUPPORTED" and r["gold"] != "SUPPORTED")
    fn_c = sum(1 for r in rows if r["pred"] != "SUPPORTED" and r["gold"] == "SUPPORTED")
    tp_c = sum(1 for r in rows if r["pred"] == "SUPPORTED" and r["gold"] == "SUPPORTED")
    outcome_sum = summarize_outcomes(outcomes)
    return _finalize("real_e2e", claims, rows, correct, missing, confusion, pred_c, gold_c, {
        "coverage": round(coverage, 4), "selective_accuracy": round(sel_correct / max(sel_total, 1), 4),
        "abstention_rate": round(abst_rate, 4), "abstention_accuracy": round(abst_correct / max(abst, 1), 4),
        "fpr": round(fp / max(fp + tn, 1), 4), "fnr": round(fn_c / max(fn_c + tp_c, 1), 4),
        "retrieval_failure": rf, "gate_failure": gf, "verification_failure": vf, "aggregation_failure": af,
        "primary_outcome_distribution": outcome_sum["outcome_counts"],
        "primary_outcome_sum": outcome_sum["outcome_sum"],
        "primary_outcome_sum_equals_total": outcome_sum["sum_equals_total"],
    }, {"input_claim_count": total, "evidence_source": "retrieval", "verify_evidence_set_call_count": ves, "gate_call_count": gate, "selector_call_count": sel, "core_verify_call_count": cv, "output_result_count": len(rows), "missing_result_count": missing})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["all", "core_oracle", "noisy_oracle", "real_e2e"], default="all")
    args = parser.parse_args()
    claims, issues = load_canonical_claims()
    val = validate_schema(claims, issues)
    if not val.passed:
        print("Schema FAILED"); return 1
    raw_by = load_raw_claims_by_id(); gold_ev_by = load_gold_evidence_by_claim()
    results = {}; session = SessionLocal()
    try:
        if args.mode in ("all", "core_oracle"):
            print("CORE_ORACLE...")
            r = run_core_oracle(claims, raw_by, gold_ev_by)
            results["core_oracle"] = r
            EVAL_DIR.mkdir(parents=True, exist_ok=True)
            (EVAL_DIR / "phase23_11_2_core_oracle.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  acc={r['accuracy']} f1={r['macro_f1']} gold_acc={r['gold_gate_acceptance_rate']} rej_gold={r['gate_rejected_gold_count']} sel_empty={r['selector_empty_rate']}")
        if args.mode in ("all", "noisy_oracle"):
            print("NOISY_ORACLE...")
            r = run_noisy_oracle(claims, raw_by, gold_ev_by)
            results["noisy_oracle"] = r
            (EVAL_DIR / "phase23_11_2_noisy_oracle.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  acc={r['accuracy']} f1={r['macro_f1']} prec={r['gate_precision']} recall={r['gate_recall']} noise={r['accepted_noise_rate']} rej_gold={r['rejected_gold_rate']}")
        if args.mode in ("all", "real_e2e"):
            print("REAL_E2E...")
            r = run_real_e2e(claims, raw_by, session)
            results["real_e2e"] = r
            E2E_DIR.mkdir(parents=True, exist_ok=True)
            (E2E_DIR / "phase23_11_2_real_e2e.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  acc={r['accuracy']} f1={r['macro_f1']} cov={r['coverage']} sel_acc={r['selective_accuracy']} abst={r['abstention_rate']} sum43={r['primary_outcome_sum_equals_total']}")
        summary = {"phase": "23.11.2", "schema": val.to_dict(), "calibrated_threshold": {"medium": 0.3, "high": 0.5, "ambiguity": 0.05}, "modes": {k: {kk: vv for kk, vv in v.items() if kk != "per_claim"} for k, v in results.items()}}
        (ART / "phase23_11_2_acceptance.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Summary: {ART / 'phase23_11_2_acceptance.json'}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
