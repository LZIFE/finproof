"""Phase 23.11.3 NOISY_ORACLE Noise Definition Repair (Task 8).

每条 Hard Negative 必须拥有明确冲突标签 (§8):
- WRONG_ENTITY
- WRONG_METRIC
- WRONG_PERIOD
- WRONG_SCOPE
- WRONG_UNIT
- SIMILAR_VALUE_WRONG_METRIC
- NARRATIVE_MENTION_ONLY

CanonicalEvidence 中应明确解析出冲突字段. 禁止通过 is_noise=true 让 Gate
读取答案; Gate 仍必须根据 Evidence 内容和 metadata 自行判断.

逐条输出: noise_type, parsed mismatch, gate result, accepted/rejected,
false acceptance 原因.

Output: backend/artifacts/evidence_gate/phase23_11_3_noisy_oracle_diagnosis.json

Usage:
    cd backend && PYTHONPATH=. python scripts/phase23_11_3_noisy_diagnosis.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import load_canonical_claims
from app.services.claim_router import route_claim
from app.services.evidence_gate import GateConfig, evaluate_one
from app.services.canonical_evidence import adapt_noisy_oracle

ART = BACKEND / "artifacts"
GATE_DIR = ART / "evidence_gate"
OUT_PATH = GATE_DIR / "phase23_11_3_noisy_oracle_diagnosis.json"

GATE_CFG = GateConfig(
    metric_match_threshold=0.6, period_conflict_strict=True, scope_conflict_strict=True,
    high_quality_threshold=0.5, medium_quality_threshold=0.3, causal_language_required=True,
)

# Explicit conflict tags (§8)
WRONG_ENTITY = "WRONG_ENTITY"
WRONG_METRIC = "WRONG_METRIC"
WRONG_PERIOD = "WRONG_PERIOD"
WRONG_SCOPE = "WRONG_SCOPE"
WRONG_UNIT = "WRONG_UNIT"
SIMILAR_VALUE_WRONG_METRIC = "SIMILAR_VALUE_WRONG_METRIC"
NARRATIVE_MENTION_ONLY = "NARRATIVE_MENTION_ONLY"


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


def _build_tagged_negatives(claim: dict) -> list[dict]:
    """Build hard negatives EACH with explicit conflict tag + conflict field.

    §8: 禁止 is_noise=true; Gate must judge from content. We attach tag only
    for diagnosis (NOT read by Gate).
    """
    period = claim.get("period") or "2025FY"
    metric = claim.get("metric") or "revenue"
    scope = claim.get("scope") or "consolidated"
    unit = claim.get("unit") or "亿元"
    value = claim.get("value")
    cid = claim.get("claim_id")

    # WRONG_PERIOD: explicit different year
    wrong_period = "2023FY" if "2025" in period else "2025FY"
    # WRONG_METRIC: explicit different metric keyword
    wrong_metric = "net_profit" if metric == "revenue" else "revenue"
    # WRONG_SCOPE: explicit different scope keyword
    wrong_scope = "归母" if scope == "consolidated" else "合并"
    # WRONG_ENTITY: explicit different company
    # WRONG_UNIT: explicit non-convertible unit context (e.g. 元/股 vs 亿元)

    return [
        {
            "evidence_id": f"NEG-WP-{cid}",
            "text": f"{metric} {value} {unit} {wrong_period}",
            "page": 5, "document_id": 1,
            "_noise_tag": WRONG_PERIOD,
            "_conflict_field": "period",
        },
        {
            "evidence_id": f"NEG-WM-{cid}",
            "text": f"{wrong_metric} {value} {unit} {period}",
            "page": 5, "document_id": 1,
            "_noise_tag": WRONG_METRIC,
            "_conflict_field": "metric",
        },
        {
            "evidence_id": f"NEG-WS-{cid}",
            "text": f"({wrong_scope}) {metric} {value} {unit} {period}",
            "page": 5, "document_id": 1,
            "_noise_tag": WRONG_SCOPE,
            "_conflict_field": "scope",
        },
        {
            "evidence_id": f"NEG-SV-{cid}",
            "text": f"{wrong_metric} {round(value * 0.95, 2) if isinstance(value, (int, float)) else value} {unit} {period}",
            "page": 6, "document_id": 1,
            "_noise_tag": SIMILAR_VALUE_WRONG_METRIC,
            "_conflict_field": "metric",
        },
        {
            "evidence_id": f"NEG-NN-{cid}",
            "text": "公司本期持续推进产品结构优化与渠道升级",
            "page": 12, "document_id": 1,
            "_noise_tag": NARRATIVE_MENTION_ONLY,
            "_conflict_field": "none",
        },
    ]


def _parse_mismatch(claim: dict, cand: dict, gate_result) -> dict:
    """Parse which fields the Gate detected as MISMATCH (from three-state)."""
    return {
        "entity": gate_result.entity_state,
        "metric": gate_result.metric_state,
        "period": gate_result.period_state,
        "unit": gate_result.unit_state,
        "scope": gate_result.scope_state,
    }


def _false_acceptance_reason(claim: dict, cand: dict, gate_result, noise_tag: str, conflict_field: str) -> str:
    """Why was this noise accepted by Gate?"""
    if noise_tag == WRONG_PERIOD and gate_result.period_state != "MISMATCH":
        # Gate didn't detect the period conflict
        ev_text = cand.get("text", "")
        claim_year = (claim.get("period") or "")[:4]
        if claim_year and claim_year in ev_text:
            return f"wrong_period negative contains claim year {claim_year} as substring, Gate period parser hit MATCH"
        return "Gate period_state=UNKNOWN (not MISMATCH); missing year extraction"
    if noise_tag in (WRONG_METRIC, SIMILAR_VALUE_WRONG_METRIC) and gate_result.metric_state != "MISMATCH":
        return "Gate metric_state=UNKNOWN/MATCH (not MISMATCH); metric_aliases too lenient"
    if noise_tag == WRONG_SCOPE and gate_result.scope_state != "MISMATCH":
        return "Gate scope_state=UNKNOWN/MATCH (not MISMATCH); scope markers not检测"
    if noise_tag == NARRATIVE_MENTION_ONLY and gate_result.accepted:
        return "narrative noise accepted because no MISMATCH on entity/metric/period (all UNKNOWN soft penalty)"
    return "other"


def diagnose() -> int:
    claims, _ = load_canonical_claims()
    raw_by = load_raw_claims_by_id()

    rows = []
    tag_counter: Counter = Counter()
    accepted_counter: Counter = Counter()
    rejected_counter: Counter = Counter()
    total_noise = 0
    accepted_noise = 0

    for cc in claims:
        claim = _build_claim(cc, raw_by.get(cc.claim_id, {}))
        routing = route_claim(claim)
        negatives = _build_tagged_negatives(claim)
        for neg in negatives:
            total_noise += 1
            tag = neg["_noise_tag"]
            tag_counter[tag] += 1
            # Strip诊断-only fields before Gate (Gate must NOT see tag)
            cand_for_gate = {k: v for k, v in neg.items() if not k.startswith("_")}
            gate_result = evaluate_one(claim, cand_for_gate, routing, GATE_CFG)
            parsed = _parse_mismatch(claim, neg, gate_result)
            if gate_result.accepted:
                accepted_noise += 1
                accepted_counter[tag] += 1
                fa_reason = _false_acceptance_reason(
                    claim, neg, gate_result, tag, neg["_conflict_field"]
                )
            else:
                rejected_counter[tag] += 1
                fa_reason = ""
            rows.append({
                "claim_id": cc.claim_id,
                "noise_type": tag,
                "conflict_field": neg["_conflict_field"],
                "noise_text": neg["text"][:120],
                "parsed_mismatch": parsed,
                "gate_result": {
                    "accepted": gate_result.accepted,
                    "final_quality_score": round(gate_result.final_quality_score, 4),
                    "rejection_reason": gate_result.rejection_reason,
                },
                "accepted": gate_result.accepted,
                "false_acceptance_reason": fa_reason,
            })

    output = {
        "phase": "23.11.3",
        "script": "phase23_11_3_noisy_diagnosis",
        "description": "每条 Hard Negative 标明确冲突标签 + Gate 误接原因诊断",
        "total_noise": total_noise,
        "accepted_noise": accepted_noise,
        "accepted_noise_rate": round(accepted_noise / max(total_noise, 1), 4),
        "noise_tag_counts": dict(tag_counter),
        "accepted_per_tag": dict(accepted_counter),
        "rejected_per_tag": dict(rejected_counter),
        "noise_tags": [
            WRONG_ENTITY, WRONG_METRIC, WRONG_PERIOD, WRONG_SCOPE, WRONG_UNIT,
            SIMILAR_VALUE_WRONG_METRIC, NARRATIVE_MENTION_ONLY,
        ],
        "forbidden_note": "Gate must NOT read _noise_tag; it judges from content only. Tag is diagnosis-only.",
        "per_noise": rows,
    }
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Noisy diagnosis written to {OUT_PATH}")
    print(f"  total noise: {total_noise}, accepted: {accepted_noise}, rate: {round(accepted_noise/max(total_noise,1),4)}")
    print(f"  accepted per tag:")
    for tag, n in sorted(accepted_counter.items(), key=lambda x: -x[1]):
        print(f"    {n:>3}  {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(diagnose())
