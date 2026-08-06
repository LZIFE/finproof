"""Phase 23.29 Task 1 — Gold Fact Mapping

把每条 gold evidence（grounding inventory）与 Financial Evidence Index 中的
事实对象对齐（fact-level，非 block-level），输出 gold_fact_alignment.json。

对齐依据：gold evidence 文本的数值（current/previous/growth）+ metric 家族
匹配 evidence index 对象；匹配对象 id 写入 aligned_evidence_ids。

不修改任何 gold label。

输出：backend/artifacts/gold_contract/phase23_29_gold_fact_alignment.json
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
GI_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_grounding_inventory.json"
IDX_PATH = BACKEND / "artifacts" / "financial_evidence_index" / "evidence_index_v1.json"
OUT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_29_gold_fact_alignment.json"

_METRIC_FAMILY = {
    "revenue": {"revenue", "total_operating_revenue"},
    "total_operating_revenue": {"revenue", "total_operating_revenue"},
    "net_profit": {"net_profit"},
    "net_profit_attributable": {"net_profit_attributable"},
    "deducted_net_profit": {"deducted_net_profit"},
    "operating_cash_flow": {"operating_cash_flow"},
}


def _extract_numbers(text: str):
    out = []
    for m in re.finditer(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", text or ""):
        try:
            v = float(m.group(0).replace(",", ""))
        except ValueError:
            continue
        if not (1900 <= v <= 2100):
            out.append(v)
    pct = None
    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d+)?)%(?!\d)", text or ""):
        pct = float(m.group(1))
        break
    return out, pct


def _norm(code: str) -> str:
    c = str(code or "")
    for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
        if c.startswith(pfx):
            return c[len(pfx):]
    return c


def _family_compatible(ev_code: str, gold_hint: str) -> bool:
    ec = _norm(ev_code)
    if not ec:
        return False
    if gold_hint and any(k in gold_hint for k in ("营业收入", "营业总收入", "收入", "revenue", "sales")):
        return ec in ("revenue", "total_operating_revenue")
    if gold_hint and any(k in gold_hint for k in ("净利润", "净利", "net")):
        return ec in ("net_profit", "net_profit_attributable", "deducted_net_profit")
    if gold_hint and any(k in gold_hint for k in ("现金流", "cash")):
        return ec == "operating_cash_flow"
    if gold_hint and any(k in gold_hint for k in ("总资产", "资产", "asset")):
        return ec == "total_assets"
    if gold_hint and any(k in gold_hint for k in ("净资产", "权益", "net asset")):
        return ec == "net_assets"
    return True


def main() -> int:
    gi = json.loads(GI_PATH.read_text(encoding="utf-8"))
    index = json.loads(IDX_PATH.read_text(encoding="utf-8")).get("evidence", [])

    mappings = []
    aligned_count = 0
    for p in gi["per_evidence"]:
        eid = p["gold_evidence_id"]
        text = p.get("evidence_text") or ""
        numbers, pct = _extract_numbers(text)
        cur = numbers[0] if len(numbers) >= 1 else None
        prev = numbers[1] if len(numbers) >= 2 else None
        growth = pct
        if cur and prev:
            growth = round((cur - prev) / abs(prev) * 100.0, 2)
        hint = text

        # 对齐 index 对象（数值 + metric 家族）
        aligned = []
        for ev in index:
            ev_cur = ev.get("current_value")
            ev_prev = ev.get("previous_value")
            cur_ok = cur is not None and ev_cur is not None and abs(cur - ev_cur) / max(1, abs(ev_cur)) < 0.005
            prev_ok = prev is not None and ev_prev is not None and abs(prev - ev_prev) / max(1, abs(ev_prev)) < 0.005
            fam = _family_compatible(ev.get("metric_code", ""), hint)
            if fam and (cur_ok or (cur_ok and prev_ok)):
                aligned.append(ev["id"])
        aligned = list(dict.fromkeys(aligned))
        if aligned:
            aligned_count += 1

        mappings.append({
            "gold_id": eid,
            "claim_id": p.get("claim_id"),
            "metric": hint[:40],
            "current_value": cur,
            "previous_value": prev,
            "growth": growth,
            "period": str(p.get("existing_page") or ""),
            "aligned_evidence_ids": aligned,
        })

    out = {
        "phase": "23.29",
        "step": "1_gold_fact_mapping",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_gold_evidence": len(mappings),
        "aligned_count": aligned_count,
        "alignment_rate": round(aligned_count / max(1, len(mappings)), 4),
        "mappings": mappings,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"total gold evidence: {len(mappings)}")
    print(f"aligned: {aligned_count} ({out['alignment_rate']})")
    print(f"wrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
