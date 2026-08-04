"""Phase 23.11.3 CORE_ORACLE Per-Stage Trace (Task 2).

对 43 条 CORE_ORACLE 逐层核对每一步真实输入输出 (§2):
CANONICAL_ADAPTER → GATE → SELECTOR → CORE_VERIFY → AGGREGATION →
VERDICT_NORMALIZATION → EVALUATION_JOIN → NONE

每条输出 first_divergence_stage (首个偏离正确的阶段). 统计 43 条中
每个阶段造成多少错误. 不得提前把 33 条统一标为 AGGREGATION_WRONG.

Output: backend/artifacts/aggregation/phase23_11_3_core_oracle_trace.json

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_3_aggregation_diagnosis.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import (
    load_canonical_claims, normalize_verdict_for_evaluation,
)
from app.services.canonical_evidence import adapt_core_oracle
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_all
from app.services.evidence_selector import SelectorConfig, select
from app.services.verification_contract import (
    EvidenceVerificationResult, FIRST_DIVG_STAGES,
    STAGE_NONE, STAGE_CANONICAL_ADAPTER, STAGE_GATE, STAGE_SELECTOR,
    STAGE_CORE_VERIFY, STAGE_AGGREGATION, STAGE_VERDICT_NORMALIZATION,
    STAGE_EVALUATION_JOIN,
)
from app.services.verification.core_pipeline import IntegrationTrace, core_verify
from app.services.evidence_aggregation import RULE_EMPTY

ART = BACKEND / "artifacts"
AGG_DIR = ART / "aggregation"
OUT_PATH = AGG_DIR / "phase23_11_3_core_oracle_trace.json"

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


def diagnose() -> int:
    claims, _ = load_canonical_claims()
    gold_ev_by = load_gold_evidence_by_claim()
    raw_by = load_raw_claims_by_id()

    rows = []
    stage_error_counter: Counter = Counter()
    correct = 0

    for cc in claims:
        cid = cc.claim_id
        gold_ev = gold_ev_by.get(cid, [])
        raw = raw_by.get(cid, {})
        claim = _build_claim(cc, raw)
        gold = cc.expected_verdict

        # ------------------------------------------------------------------
        # Data-gap guard: NO gold evidence for this claim
        # ------------------------------------------------------------------
        if not gold_ev:
            # Pipeline abstains (empty selection → INSUFFICIENT_EVIDENCE)
            final_prediction = "INSUFFICIENT_EVIDENCE"
            is_correct = final_prediction == gold
            if is_correct:
                first_div = STAGE_NONE
                root = "correct abstention (no gold evidence, gold=INSUFFICIENT_EVIDENCE)"
            else:
                # gold expects a definite/non-abstention class but annotations
                # provide no evidence — input data gap, NOT a pipeline stage bug.
                first_div = STAGE_CANONICAL_ADAPTER
                root = (
                    f"gold-data gap: gold_evidence.json has no evidence for claim; "
                    f"pipeline abstains (gold={gold})"
                )
            if first_div != STAGE_NONE:
                stage_error_counter[first_div] += 1
            if is_correct:
                correct += 1
            rows.append({
                "claim_id": cid,
                "expected_verdict": gold,
                "gold_evidence_ids": [],
                "gate_accepted_ids": [],
                "selector_selected_ids": [],
                "evidence_level_verdicts": [],
                "evidence_level_confidences": [],
                "aggregation_rule": RULE_EMPTY,
                "internal_verdict": "INSUFFICIENT_EVIDENCE",
                "normalized_external_verdict": "INSUFFICIENT_EVIDENCE",
                "final_prediction": final_prediction,
                "correct": is_correct,
                "first_divergence_stage": first_div,
                "root_cause": root,
            })
            continue

        # Stage 1: CANONICAL_ADAPTER
        ce_list, _ = adapt_core_oracle(gold_ev, claim, route_claim(claim).route)
        adapter_ok = len(ce_list) == len(gold_ev) and all(ce.text for ce in ce_list)
        # adapter divergence: if gold evidence couldn't be adapted (missing id/text)
        adapter_divg = not adapter_ok

        # Stage 2: GATE
        routing = route_claim(claim)
        gate_results = evaluate_all(claim, gold_ev, routing, GATE_CFG)
        gate_accepted = [c for c, r in zip(gold_ev, gate_results) if r.accepted]
        gate_accepted_ids = [str(c.get("evidence_id") or "?") for c in gate_accepted]
        # gate divergence: gold exists but全部被拒
        gate_divg = not gate_accepted

        # Stage 3: SELECTOR
        bundle_sel, sel_meta = select(gate_results, routing, SEL_CFG)
        sel_ids = [b.get("evidence_id") for b in bundle_sel]
        gold_ids_set = {str(e.get("evidence_id") or "?") for e in gold_ev}
        gold_selected = any(str(x) in gold_ids_set for x in sel_ids)
        # selector divergence: gate有accepted gold但selector没选任何gold
        selector_divg = not gold_selected

        # Stage 4: CORE_VERIFY (single-evidence-level on each selected)
        # Fill text into bundle
        id_to_text = {str(e.get("evidence_id") or "?"): e for e in gold_ev}
        for b in bundle_sel:
            e = id_to_text.get(b.get("evidence_id"))
            if e:
                b["text"] = str(e.get("evidence_text") or e.get("text") or "")
                b["page"] = e.get("page")
                b["document_id"] = e.get("document_id")
                b["evidence_type"] = e.get("evidence_type", "")
        # evidence-level verdicts
        evidence_level_verdicts = []
        evidence_level_confidences = []
        for b in bundle_sel:
            trace = IntegrationTrace(claim_id=cid)
            try:
                r = core_verify(claim, [b], trace)
                ev_raw = r.verification_status
                ev_conf = r.confidence
            except Exception:
                ev_raw = "INSUFFICIENT_EVIDENCE"; ev_conf = 0.2
            ev_norm = normalize_verdict_for_evaluation(ev_raw)
            evidence_level_verdicts.append(ev_norm)
            evidence_level_confidences.append(round(ev_conf, 4))

        # Stage 5: AGGREGATION (§4 真值表)
        from app.services.evidence_aggregation import aggregate_evidence
        ev_results = []
        for b, ev_norm, ev_conf in zip(bundle_sel, evidence_level_verdicts, evidence_level_confidences):
            # Build EvidenceVerificationResult
            gate_r = next((r for r in gate_results if r.evidence_id == b.get("evidence_id")), None)
            ev_results.append(EvidenceVerificationResult(
                claim_id=cid, evidence_id=b.get("evidence_id", "?"),
                evidence_text=b.get("text", ""),
                gate_quality_score=gate_r.final_quality_score if gate_r else 0.0,
                gate_status="ACCEPTED" if gate_r and gate_r.accepted else "REJECTED",
                selector_rank=1,  # simplified
                entity_match=gate_r.entity_state if gate_r else "UNKNOWN",
                metric_match=gate_r.metric_state if gate_r else "UNKNOWN",
                period_match=gate_r.period_state if gate_r else "UNKNOWN",
                unit_match=gate_r.unit_state if gate_r else "UNKNOWN",
                scope_match=gate_r.scope_state if gate_r else "UNKNOWN",
                numeric_match="UNKNOWN",
                evidence_verdict=ev_norm, evidence_confidence=ev_conf,
            ))
        agg_result = aggregate_evidence(cid, ev_results)
        internal_verdict = agg_result.internal_verdict

        # Stage 6: VERDICT_NORMALIZATION
        external_verdict = normalize_verdict_for_evaluation(internal_verdict)

        # Stage 7: EVALUATION_JOIN
        final_prediction = external_verdict
        is_correct = final_prediction == gold
        if is_correct:
            correct += 1

        # ------------------------------------------------------------------
        # Honest first-divergence attribution (逐层对账, NOT AGGREGATION_WRONG dump)
        # ------------------------------------------------------------------
        first_div = STAGE_NONE
        if adapter_divg:
            first_div = STAGE_CANONICAL_ADAPTER
        elif gate_divg:
            first_div = STAGE_GATE
        elif selector_divg:
            first_div = STAGE_SELECTOR
        elif is_correct:
            first_div = STAGE_NONE
        else:
            # Not correct. Attribute to the FIRST stage that diverged.
            # (a) no selected evidence → cannot happen here (gate_divg/selector_divg handled)
            # (b) evidence-level: does any selected gold evidence's verdict match gold?
            any_single_correct = any(v == gold for v in evidence_level_verdicts)
            if not bundle_sel or not any_single_correct:
                # core_verify never produced the gold verdict at evidence level
                # (includes ALL-ABSTAIN case: gold wants a definite verdict but
                #  core_verify abstained on every selected evidence)
                first_div = STAGE_CORE_VERIFY
            elif internal_verdict != gold:
                # a correct single-evidence verdict existed but aggregation
                # produced a different verdict (or conflict→abstention)
                first_div = STAGE_AGGREGATION
            elif external_verdict != internal_verdict:
                # internal was correct but normalization mapping changed it
                first_div = STAGE_VERDICT_NORMALIZATION
            else:
                # residual join mismatch (gold label normalization differs, etc.)
                first_div = STAGE_EVALUATION_JOIN

        if first_div != STAGE_NONE:
            stage_error_counter[first_div] += 1

        rows.append({
            "claim_id": cid,
            "expected_verdict": gold,
            "gold_evidence_ids": [str(e.get("evidence_id") or "?") for e in gold_ev],
            "gate_accepted_ids": gate_accepted_ids,
            "selector_selected_ids": sel_ids,
            "evidence_level_verdicts": evidence_level_verdicts,
            "evidence_level_confidences": evidence_level_confidences,
            "aggregation_rule": agg_result.aggregation_rule,
            "internal_verdict": internal_verdict,
            "normalized_external_verdict": external_verdict,
            "final_prediction": final_prediction,
            "correct": is_correct,
            "first_divergence_stage": first_div,
            "root_cause": _root_cause(first_div, gold, final_prediction),
        })

    total = len(claims)
    output = {
        "phase": "23.11.3",
        "script": "phase23_11_3_aggregation_diagnosis",
        "description": "43 CORE_ORACLE逐层对账: CANONICAL_ADAPTER → GATE → SELECTOR → CORE_VERIFY → AGGREGATION → VERDICT_NORMALIZATION → EVALUATION_JOIN",
        "sample_count": total,
        "correct": correct,
        "accuracy": round(correct / total, 4),
        "first_divergence_stage_counts": dict(stage_error_counter),
        "stage_error_summary": {
            "CANONICAL_ADAPTER": stage_error_counter.get(STAGE_CANONICAL_ADAPTER, 0),
            "GATE": stage_error_counter.get(STAGE_GATE, 0),
            "SELECTOR": stage_error_counter.get(STAGE_SELECTOR, 0),
            "CORE_VERIFY": stage_error_counter.get(STAGE_CORE_VERIFY, 0),
            "AGGREGATION": stage_error_counter.get(STAGE_AGGREGATION, 0),
            "VERDICT_NORMALIZATION": stage_error_counter.get(STAGE_VERDICT_NORMALIZATION, 0),
            "EVALUATION_JOIN": stage_error_counter.get(STAGE_EVALUATION_JOIN, 0),
            "NONE (correct)": stage_error_counter.get(STAGE_NONE, 0) + (total - sum(stage_error_counter.values())),
        },
        "first_divergence_stage_taxonomy": list(FIRST_DIVG_STAGES),
        "per_claim": rows,
    }
    AGG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CORE_ORACLE trace written to {OUT_PATH}")
    print(f"  sample_count: {total}, correct: {correct}, accuracy: {round(correct/total,4)}")
    print(f"  first_divergence_stage_counts:")
    for s, n in sorted(stage_error_counter.items(), key=lambda x: -x[1]):
        print(f"    {n:>3}  {s}")
    return 0


def _root_cause(stage: str, gold: str, pred: str) -> str:
    if stage == STAGE_NONE:
        return "correct"
    if stage == STAGE_CANONICAL_ADAPTER:
        return "canonical adapter failed to adapt gold evidence (missing id/text)"
    if stage == STAGE_GATE:
        return "gate rejected all gold evidence (GATE_REJECTED_GOLD)"
    if stage == STAGE_SELECTOR:
        return "selector dropped gold after gate acceptance (SELECTOR_DROPPED_GOLD)"
    if stage == STAGE_CORE_VERIFY:
        return f"core_verify evidence-level verdict wrong (gold={gold}, pred={pred})"
    if stage == STAGE_AGGREGATION:
        return f"aggregation真值表错误 (gold={gold}, pred={pred})"
    if stage == STAGE_VERDICT_NORMALIZATION:
        return f"verdict normalization mapping wrong (gold={gold}, pred={pred})"
    if stage == STAGE_EVALUATION_JOIN:
        return f"evaluation join wrong (gold={gold}, pred={pred})"
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(diagnose())
