"""Phase 23.11 Regression Diff Script (Task 8).

Compares Phase 23.9 vs Phase 23.10 results claim-by-claim.
Output: backend/artifacts/e2e/phase23_11_regression_diff.json

Each entry contains:
- claim_id
- phase23_9_verdict
- phase23_10_verdict
- gold_verdict
- phase23_9_evidence
- phase23_10_evidence
- ranking_change
- evidence_noise_added
- failure_reason
- phase23_11_expected_fix

Usage:
    python backend/scripts/phase23_11_regression_diff.py
"""
from __future__ import annotations

import json
from pathlib import Path

# Resolve paths
BACKEND = Path(__file__).resolve().parent.parent
ARTIFACTS = BACKEND / "artifacts"
E2E_DIR = ARTIFACTS / "e2e"

# Output
OUT_PATH = E2E_DIR / "phase23_11_regression_diff.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def extract_claims(data: dict) -> dict[str, dict]:
    """Return {claim_id: claim_record} from a development E2E result file.

    Reads the `per_claim` array (43 entries with claim_id/gold/pred/...).
    """
    out: dict[str, dict] = {}
    if not data:
        return out
    # Prefer per_claim array (Phase 23.9/23.10 E2E format)
    per_claim = data.get("per_claim") if isinstance(data, dict) else None
    if isinstance(per_claim, list):
        for c in per_claim:
            cid = str(c.get("claim_id") or c.get("claim_uid") or "?")
            out[cid] = c
        return out
    # Fallback: top-level claims array
    claims = data.get("claims") if isinstance(data, dict) else None
    if claims is None and isinstance(data, list):
        claims = data
    if claims is None:
        return out
    for c in claims:
        cid = str(c.get("claim_id") or c.get("claim_uid") or "?")
        out[cid] = c
    return out


def classify_failure(
    p9_verdict: str,
    p10_verdict: str,
    gold: str,
) -> tuple[str, str]:
    """Classify the failure reason and Phase 23.11 expected fix.

    Returns (failure_reason, phase23_11_expected_fix).
    """
    p9_correct = p9_verdict == gold
    p10_correct = p10_verdict == gold

    if p9_correct and not p10_correct:
        reason = "Phase 23.9 correct, Phase 23.10 wrong (regression)"
        fix = "Restore Phase 23.9 verdict via routing + gate"
    elif not p9_correct and not p10_correct:
        reason = "Both phases wrong (persistent failure)"
        fix = "Apply Phase 23.11 routing + gate to recover"
    elif p9_correct and p10_correct:
        reason = "Both phases correct (no regression)"
        fix = "Maintain correctness with Phase 23.11 pipeline"
    else:
        reason = "Phase 23.9 wrong, Phase 23.10 correct (improvement)"
        fix = "Maintain Phase 23.10 correctness"

    return reason, fix


def build_diff(
    p9_claims: dict[str, dict],
    p10_claims: dict[str, dict],
    gold_claims: dict[str, dict],
) -> list[dict]:
    """Build per-claim diff entries."""
    all_ids = sorted(set(p9_claims) | set(p10_claims) | set(gold_claims))
    diff: list[dict] = []
    for cid in all_ids:
        p9 = p9_claims.get(cid, {})
        p10 = p10_claims.get(cid, {})
        gold = gold_claims.get(cid, {})

        # Per-claim records use `gold` and `pred` fields (Phase 23.9/23.10 E2E format)
        p9_verdict = str(
            p9.get("pred") or p9.get("verdict")
            or p9.get("verification_status") or "UNKNOWN"
        )
        p10_verdict = str(
            p10.get("pred") or p10.get("verdict")
            or p10.get("verification_status") or "UNKNOWN"
        )
        gold_verdict = str(
            p10.get("gold") or gold.get("gold_verdict")
            or gold.get("verdict") or "UNKNOWN"
        )

        # Evidence IDs (from multi_evidence block if present)
        def _ev(rec: dict) -> list[str]:
            me = rec.get("multi_evidence") or {}
            ids = me.get("selected_evidence_ids") or rec.get("evidence_ids") or []
            return [str(e) for e in ids]

        p9_ev = _ev(p9)
        p10_ev = _ev(p10)

        # Ranking change description
        p9_ev_set = set(str(e) for e in p9_ev)
        p10_ev_set = set(str(e) for e in p10_ev)
        added = sorted(p10_ev_set - p9_ev_set)
        removed = sorted(p9_ev_set - p10_ev_set)

        ranking_change = ""
        if added or removed:
            parts = []
            if added:
                parts.append(f"+{added}")
            if removed:
                parts.append(f"-{removed}")
            ranking_change = " ".join(parts)

        # Noise added in Phase 23.10
        evidence_noise_added = added

        reason, fix = classify_failure(p9_verdict, p10_verdict, gold_verdict)

        diff.append({
            "claim_id": cid,
            "phase23_9_verdict": p9_verdict,
            "phase23_10_verdict": p10_verdict,
            "gold_verdict": gold_verdict,
            "phase23_9_evidence": [str(e) for e in p9_ev],
            "phase23_10_evidence": [str(e) for e in p10_ev],
            "ranking_change": ranking_change,
            "evidence_noise_added": evidence_noise_added,
            "failure_reason": reason,
            "phase23_11_expected_fix": fix,
        })
    return diff


def main() -> int:
    # Load Phase 23.9 and Phase 23.10 Development E2E results
    p9_path = E2E_DIR / "phase23_9_development_e2e.json"
    p10_path = E2E_DIR / "phase23_10_development_e2e.json"

    p9_data = load_json(p9_path)
    p10_data = load_json(p10_path)

    p9_claims = extract_claims(p9_data)
    p10_claims = extract_claims(p10_data)

    # Gold verdicts (from p10 file if it includes gold_verdict, else empty)
    gold_claims: dict[str, dict] = {}
    for cid, c in p10_claims.items():
        gold_claims[cid] = {
            "gold_verdict": c.get("gold_verdict") or c.get("expected_verdict") or "UNKNOWN",
        }

    diff = build_diff(p9_claims, p10_claims, gold_claims)

    # Summary stats
    regressions = sum(
        1 for d in diff
        if d["phase23_9_verdict"] == d["gold_verdict"]
        and d["phase23_10_verdict"] != d["gold_verdict"]
    )
    persistent = sum(
        1 for d in diff
        if d["phase23_9_verdict"] != d["gold_verdict"]
        and d["phase23_10_verdict"] != d["gold_verdict"]
    )
    improvements = sum(
        1 for d in diff
        if d["phase23_9_verdict"] != d["gold_verdict"]
        and d["phase23_10_verdict"] == d["gold_verdict"]
    )

    output = {
        "phase": "23.11",
        "description": "Phase 23.9 vs Phase 23.10 per-claim regression diff",
        "baseline_commits": {
            "phase23_9": "bf6089e",
            "phase23_10": "3dada2c",
        },
        "summary": {
            "total_claims": len(diff),
            "regressions_p9_correct_p10_wrong": regressions,
            "persistent_failures_both_wrong": persistent,
            "improvements_p9_wrong_p10_correct": improvements,
            "recovery_target_pct": round(
                (regressions / max(regressions + persistent, 1)) * 100, 1
            ) if (regressions + persistent) > 0 else 0.0,
        },
        "diff": diff,
    }

    E2E_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Regression diff written to {OUT_PATH}")
    print(f"  Total claims: {len(diff)}")
    print(f"  Regressions (P9 correct, P10 wrong): {regressions}")
    print(f"  Persistent failures (both wrong): {persistent}")
    print(f"  Improvements (P9 wrong, P10 correct): {improvements}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
