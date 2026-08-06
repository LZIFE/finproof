"""Phase 23.22 Task 1/2 — Fact-Level Alignment（gold evidence → FinancialEvidenceObject）

关键洞察（Phase 23.22）：gold grounding blocks 与 evidence index source_blocks 是
不同位置但代表同一事实（如 gold page 9 block 169/189 vs index page 135 blocks 4440-4446，
都是 Revenue 458,502,407）。因此对齐用**事实级匹配**而非 block 级。

对齐方法：
1. 从 gold evidence_text 提取数值序列（current / previous / growth%）+ 指标词
2. 在 evidence index 中找匹配对象：
   - current+previous 精确匹配且 metric 家族一致 → EXACT_BLOCK_MATCH（若块也重叠）
   - current+previous 匹配但块不同 → FACT_MATCH_BLOCK_DIFF
   - 仅 current 或 growth 匹配 → PARTIAL_FACT_MATCH
   - 无任何匹配 → NO_FACT_FOUND

输出：backend/artifacts/gold_contract/phase23_22_gold_fact_alignment.json
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
GI_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_grounding_inventory.json"
IDX_PATH = BACKEND / "artifacts" / "financial_evidence_index" / "evidence_index_v1.json"
OUT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_22_gold_fact_alignment.json"

_METRIC_FAMILY = {
    "revenue": {"revenue", "total_operating_revenue"},
    "total_operating_revenue": {"revenue", "total_operating_revenue"},
    "net_profit": {"net_profit"},
    "net_profit_attributable": {"net_profit_attributable"},
    "deducted_net_profit": {"deducted_net_profit"},
    "operating_cash_flow": {"operating_cash_flow"},
}


def _extract_numbers(text: str) -> list[float]:
    """提取文本中的财务数值（千分位 + 百分比），过滤年份。"""
    out: list[float] = []
    for m in re.finditer(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", text or ""):
        try:
            v = float(m.group(0).replace(",", ""))
        except ValueError:
            continue
        if 1900 <= v <= 2100:
            continue
        out.append(v)
    pct = None
    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d+)?)%(?!\d)", text or ""):
        pct = float(m.group(1))
        break
    return out, pct


def _growth_of(cur, prev):
    if not cur or not prev:
        return None
    return round((cur - prev) / abs(prev) * 100.0, 2)


def _norm_code(code: str) -> str:
    c = str(code or "")
    for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
        if c.startswith(pfx):
            return c[len(pfx):]
    return c


def _metric_family_match(ev_code: str, gold_metric_hint: str) -> bool:
    """evidence metric_code 与 gold 指标文本是否家族一致。"""
    ec = _norm_code(ev_code)
    if not ec:
        return False
    if gold_metric_hint and any(k in gold_metric_hint for k in ("营业收入", "营业总收入", "收入", "revenue", "sales")):
        return ec in ("revenue", "total_operating_revenue")
    if gold_metric_hint and any(k in gold_metric_hint for k in ("净利润", "净利", "net")):
        return ec in ("net_profit", "net_profit_attributable", "deducted_net_profit")
    if gold_metric_hint and any(k in gold_metric_hint for k in ("现金流", "cash")):
        return ec == "operating_cash_flow"
    return True  # 无指标提示时放宽


def align_gold_to_fact(gold_ev: dict, index: list[dict]) -> dict:
    """单条 gold evidence → 对齐结果。"""
    eid = gold_ev["gold_evidence_id"]
    text = gold_ev.get("evidence_text") or ""
    numbers, pct = _extract_numbers(text)
    cur = numbers[0] if len(numbers) >= 1 else None
    prev = numbers[1] if len(numbers) >= 2 else None
    gold_growth = _growth_of(cur, prev) if (cur and prev) else pct
    gold_blocks = {str(b) for b in (gold_ev.get("candidate_block_ids") or [])}
    metric_hint = gold_ev.get("claim_metric") or text

    best = None
    best_kind = "NO_FACT_FOUND"
    for ev in index:
        ev_cur = ev.get("current_value")
        ev_prev = ev.get("previous_value")
        ev_growth = ev.get("growth")
        # 数值匹配（容差 0.5%）
        cur_match = cur is not None and ev_cur is not None and abs(cur - ev_cur) / max(1, abs(ev_cur)) < 0.005
        prev_match = prev is not None and ev_prev is not None and abs(prev - ev_prev) / max(1, abs(ev_prev)) < 0.005
        growth_match = (gold_growth is not None and ev_growth is not None
                        and abs(gold_growth - ev_growth) < 1.0)
        fam = _metric_family_match(ev.get("metric_code", ""), metric_hint)
        # 块重叠
        ev_blocks = {str(b) for b in ev.get("source_blocks", [])}
        block_overlap = bool(gold_blocks & ev_blocks)

        if cur_match and prev_match and fam:
            kind = "EXACT_BLOCK_MATCH" if block_overlap else "FACT_MATCH_BLOCK_DIFF"
            if best is None or kind == "EXACT_BLOCK_MATCH":
                best = ev
                best_kind = kind
        elif (cur_match or growth_match) and fam and best is None:
            best = ev
            best_kind = "PARTIAL_FACT_MATCH"

    return {
        "gold_evidence_id": eid,
        "claim_id": gold_ev.get("claim_id"),
        "gold_text": text,
        "gold_grounding_blocks": sorted(gold_blocks),
        "gold_page": gold_ev.get("existing_page"),
        "gold_fact": {"current": cur, "previous": prev, "growth": gold_growth},
        "alignment_category": best_kind,
        "matched_evidence": (None if best is None else {
            "id": best["id"], "metric": best.get("metric"), "metric_code": best.get("metric_code"),
            "current_value": best.get("current_value"), "previous_value": best.get("previous_value"),
            "growth": best.get("growth"), "page": best.get("page_number"),
            "source_blocks": best.get("source_blocks"),
        }),
    }


def main() -> int:
    gi = json.loads(GI_PATH.read_text(encoding="utf-8"))
    index = json.loads(IDX_PATH.read_text(encoding="utf-8")).get("evidence", [])
    results = [align_gold_to_fact(p, index) for p in gi["per_evidence"]]

    from collections import Counter
    counts = Counter(r["alignment_category"] for r in results)
    out = {
        "phase": "23.22",
        "step": "1_2_fact_alignment",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_gold_evidence": len(results),
        "category_counts": dict(counts),
        "alignment_rate": round((counts["EXACT_BLOCK_MATCH"] + counts["FACT_MATCH_BLOCK_DIFF"] + counts["PARTIAL_FACT_MATCH"]) / max(1, len(results)), 4),
        "alignment": results,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"total: {len(results)}")
    print(f"category_counts: {dict(counts)}")
    print(f"alignment_rate: {out['alignment_rate']}")
    print(f"wrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
