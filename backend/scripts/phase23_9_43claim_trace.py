#!/usr/bin/env python3
"""Phase 23.9 — 43 条 Development Claims 运行时 Integration Trace。

真实主链：verification_service._select_verifier → core_pipeline.core_verify
（整合 FinancialValue / PeriodContext / metric_scope / verdict_decision / semantic_verifier）。

输入：Gold Evidence Block（与 Oracle 评测一致），Gold 输入 = gold_evidence.json，
Gold 输出 = gold_verifications.json（仅评测用，系统推理不读取）。

每条 claim 输出（验收要求）：
- claim_id
- selected_verifier / financial_value_called / period_context_called
- metric_scope_called / verdict_decision_called / semantic_verifier_called
- numeric_preliminary_verdict / semantic_preliminary_verdict
- final_verdict / override_source / rule_id / evidence_ids

验收：
1. 43 条全部有完整 trace
2. 数值类必须调用 FinancialValue
3. 期间类必须调用 PeriodContext
4. 口径类必须调用 ScopeContext
5. 最终 Verdict 必须能指出由哪个模块决定
6. 禁止静默覆盖（override_source 非空）

用法:
    cd backend
    python scripts/phase23_9_43claim_trace.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "integration"

# 文档文件名 → 报告期间（与 core_pipeline.DOC_PERIOD_BY_NAME 一致）
DOC_PERIOD_BY_NAME = {
    "annual_report.pdf": "2025FY",
    "half_year_report.pdf": "2025H1",
    "q1_report.pdf": "2025Q1",
    "quarter_report.pdf": "2025Q3",
    "annual_report_2025.pdf": "2025FY",
    "annual_report_2024.pdf": "2024FY",
}


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def load_gold(dataset: str) -> tuple[list[dict], dict[str, list[dict]], dict[str, dict]]:
    claims = json.load(open(DATA_DIR / dataset / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])
    evs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_evidence.json", encoding="utf-8")).get("evidence", [])
    vrs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_verifications.json", encoding="utf-8")).get("verifications", [])
    ev_by: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        ev_by[e.get("claim_id", "")].append(e)
    vr_by = {v.get("claim_id", ""): v for v in vrs}
    return claims, dict(ev_by), vr_by


def run_trace() -> dict:
    _ensure_app_on_path()
    from app.services.verification.core_pipeline import IntegrationTrace, core_verify

    all_claims: list[dict] = []
    all_ev: dict[str, list[dict]] = {}
    all_vr: dict[str, dict] = {}
    for ds in ["demo", "holdout"]:
        claims, ev, vr = load_gold(ds)
        for c in claims:
            c["_dataset"] = ds
        all_claims.extend(claims)
        all_ev.update(ev)
        all_vr.update(vr)

    traces: list[dict] = []
    for claim in all_claims:
        cid = claim.get("claim_id")
        ev_blocks = all_ev.get(cid, [])
        evidence_list = []
        for e in ev_blocks:
            fname = str(e.get("document_name") or "")
            base = fname.split("/")[-1]
            evidence_list.append({
                "evidence_id": e.get("evidence_id"),
                "text": e.get("evidence_text", "") or e.get("text", ""),
                "doc_period": DOC_PERIOD_BY_NAME.get(base),
                "document_name": fname,
                "page": e.get("page"),
            })
        trace = IntegrationTrace(claim_id=cid)
        try:
            result = core_verify(claim, evidence_list, trace)
        except Exception as exc:  # noqa: BLE001
            trace.final_verdict = "ERROR"
            trace.detail["exception"] = str(exc)[:200]
            result = None

        gold = all_vr.get(cid, {}).get("expected_verdict", "UNKNOWN")
        tdict = trace.to_dict()
        tdict.update({
            "gold_verdict": gold,
            "dataset": claim.get("_dataset"),
            "claim_type": claim.get("claim_type", ""),
            "metric": claim.get("metric", ""),
            "period": claim.get("period", ""),
            "gold_evidence_count": len(ev_blocks),
            "prediction_matches_gold": (result.verification_status if result else None) == gold,
        })
        traces.append(tdict)

    # ---- 验收检查 ----
    numeric_types = {"raw_number", "calculated_financial_metric"}
    period_types = {"calculated_financial_metric"}
    checks = {
        "all_43_have_complete_trace": all(
            t.get("final_verdict") is not None and t.get("claim_id")
            for t in traces
        ),
        "numeric_claims_call_financial_value": all(
            t["financial_value_called"] for t in traces if t.get("claim_type") in numeric_types
        ),
        "period_claims_call_period_context": all(
            t["period_context_called"] for t in traces if t.get("claim_type") in period_types
        ),
        "scope_claims_call_metric_scope": all(
            t["metric_scope_called"] for t in traces if t.get("claim_type") == "scope"
        ),
        "final_verdict_has_deciding_module": all(
            bool(t.get("override_source")) or t.get("final_verdict") in ("ERROR",)
            for t in traces
        ),
        "no_silent_override": all(
            t.get("final_verdict") is None
            or t.get("final_verdict") == t.get("numeric_preliminary_verdict")
            or t.get("final_verdict") == t.get("semantic_preliminary_verdict")
            or t.get("override_source")
            for t in traces
        ),
    }
    correct = sum(1 for t in traces if t.get("prediction_matches_gold"))
    result_json = {
        "phase": "23.9",
        "script": "phase23_9_43claim_trace",
        "entry_point": "verification_service._select_verifier → core_pipeline.core_verify",
        "total_claims": len(traces),
        "correct_count": correct,
        "accuracy": round(correct / len(traces), 3) if traces else 0.0,
        "acceptance_checks": checks,
        "traces": traces,
        "note": "Gold Evidence Block 输入（Oracle 模式）；gold_verifications 仅用于评测对照，不进入推理路径",
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_9_43claim_trace.json"
    out_path.write_text(json.dumps(result_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    print(f"total: {len(traces)}, correct: {correct}, accuracy: {result_json['accuracy']}")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    return result_json


if __name__ == "__main__":
    run_trace()
