"""Agent Report Generator（Phase 5）：将核验结果组装为结构化审计报告。

报告结构：Summary（数量统计）+ Risk Findings（风险主张详情）+ Evidence Chain（证据链）。
遵守 Evidence First：每个结论均附证据与计算明细，不凭空判断。
"""

from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)

RISK_STATUSES = (STATUS_REFUTED, STATUS_PARTIALLY_SUPPORTED, STATUS_INSUFFICIENT, STATUS_UNABLE)


def _calc_text(calc: dict | None) -> str:
    if not calc:
        return ""
    keys = [
        ("calculated_growth_pp", "计算增长率"),
        ("claimed_growth_pp", "主张增长率"),
        ("converted_value", "换算值"),
        ("source_unit", "证据单位"),
        ("calculated_quarter_value", "推算单季值"),
        ("claimed_value", "主张值"),
        ("covered", "覆盖"),
        ("required", "要求"),
    ]
    parts = []
    for k, label in keys:
        if k in calc:
            parts.append(f"{label}={calc[k]}")
    return "，".join(parts) if parts else str(calc)


def build_report(
    document_id: int,
    claims: list[dict],
    evidence_map: dict[str, list[dict]],
    verification_results: list[dict],
) -> dict:
    """生成审计报告：summary + findings + evidence_chain + verification_results。"""
    counts = {
        "total_claims": len(verification_results),
        "supported_count": 0,
        "refuted_count": 0,
        "partially_supported_count": 0,
        "insufficient_count": 0,
        "unknown_count": 0,
    }
    status_key = {
        STATUS_SUPPORTED: "supported_count",
        STATUS_REFUTED: "refuted_count",
        STATUS_PARTIALLY_SUPPORTED: "partially_supported_count",
        STATUS_INSUFFICIENT: "insufficient_count",
        STATUS_UNABLE: "unknown_count",
    }
    for v in verification_results:
        key = status_key.get(v["verification_status"], "unknown_count")
        counts[key] += 1

    claim_by_id = {}
    for c in claims:
        claim_by_id[c.get("claim_id") or c.get("claim_uid")] = c

    # Risk Findings：非 SUPPORTED 的风险主张（Claim/Evidence/Calculation/Conclusion）
    findings = []
    for v in verification_results:
        if v["verification_status"] not in RISK_STATUSES:
            continue
        c = claim_by_id.get(v["claim_id"], {})
        evidence = evidence_map.get(v["claim_id"], [])
        findings.append(
            {
                "claim_id": v["claim_id"],
                "claim": c.get("original_text") or c.get("source_text") or v["claim_id"],
                "evidence": [
                    {
                        "page_number": e.get("page_number"),
                        "block_id": e.get("block_id"),
                        "text": (e.get("text") or "")[:120],
                        "evidence_type": e.get("evidence_type"),
                    }
                    for e in evidence[:2]
                ],
                "calculation": _calc_text(v.get("calculation_detail")),
                "conclusion": v["verification_status"],
                "reason": v["reason"],
            }
        )

    # Evidence Chain：每个 claim 的 claim → evidence → verification → conclusion
    evidence_chain = []
    for v in verification_results:
        c = claim_by_id.get(v["claim_id"], {})
        evidence = evidence_map.get(v["claim_id"], [])
        evidence_chain.append(
            {
                "claim_id": v["claim_id"],
                "claim": c.get("original_text") or c.get("source_text") or v["claim_id"],
                "evidence": [
                    f"p{e.get('page_number')} blk{e.get('block_id')}（{e.get('evidence_type')}）"
                    for e in evidence[:3]
                ],
                "verification": v["verification_status"],
                "conclusion": v["reason"],
            }
        )

    return {
        "document_id": document_id,
        "summary": counts,
        "findings": findings,
        "evidence_chain": evidence_chain,
        "verification_results": verification_results,
    }
