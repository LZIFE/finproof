"""Phase 23.20 Task 2 — Financial Evidence Retriever

输入 Claim，输出 FinancialEvidence 候选对象（从 evidence_index 检索）。

匹配维度（score 0-1 加权）：
- metric matching     : 指标家族/别名一致（claim metric_code vs evidence metric_code）
- value matching      : claim reported_value 与 evidence current_value/previous_value 兼容（单位换算）
- growth matching     : claim 含增长率主张时，evidence.growth 存在且接近
- period matching     : claim period 年份 ∈ evidence.periods
- table type matching : claim 路由章节 vs evidence.table_type

输出：按 composite score 降序的 evidence 对象列表。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]  # backend/
INDEX_PATH = BACKEND / "artifacts" / "financial_evidence_index" / "evidence_index_v1.json"

# 指标家族等价（与 financial_fact_extractor 对齐）
_METRIC_FAMILY: dict[str, set[str]] = {
    "revenue": {"revenue", "total_operating_revenue"},
    "total_operating_revenue": {"revenue", "total_operating_revenue"},
    "net_profit": {"net_profit"},
    "net_profit_attributable": {"net_profit_attributable"},
    "deducted_net_profit": {"deducted_net_profit"},
    "operating_cash_flow": {"operating_cash_flow"},
}
# 章节路由 → 表格类型（简化版，与 claim_routing 对齐）
_SECTION_TO_TABLE = {
    "income_statement": "income_statement",
    "balance_sheet": "balance_sheet",
    "cash_flow": "cash_flow",
    "equity_changes": "equity_changes",
}

_index: list[dict] | None = None


def _load_index() -> list[dict]:
    global _index
    if _index is None:
        _index = json.loads(INDEX_PATH.read_text(encoding="utf-8")).get("evidence", [])
    return _index


def _norm_metric_code(code: str) -> str:
    """growth 前缀剥除：yoy_growth_revenue → revenue。"""
    c = str(code or "")
    for pfx in ("yoy_growth_", "qoq_growth_", "growth_"):
        if c.startswith(pfx):
            return c[len(pfx):]
    return c


def _metric_match(claim_code: str, ev_code: str) -> float:
    cbase = _norm_metric_code(claim_code)
    ebase = _norm_metric_code(ev_code)
    if not cbase or not ebase:
        return 0.0
    if cbase == ebase:
        return 1.0
    fam = _METRIC_FAMILY.get(cbase, set())
    if fam and ebase in fam:
        return 1.0
    return 0.0


def _value_compatible(claim_value: float | None, claim_unit: str | None,
                      ev_value: float | None, ev_unit: str | None) -> float:
    """claim 数值与 evidence 数值兼容（同量纲，容差 1%）。"""
    if claim_value is None or ev_value is None:
        return 0.0
    # 同单位族直接比；不同单位族按千元基准换算（千元→元×1000 等）
    unit_scale = {"元": 1.0, "千元": 1000.0, "万元": 1e4, "百万元": 1e6, "亿元": 1e8}
    cu = (claim_unit or "").replace("人民币", "")
    eu = (ev_unit or "").replace("人民币", "")
    cs = unit_scale.get(cu, unit_scale.get("千元", 1.0))
    es = unit_scale.get(eu, unit_scale.get("千元", 1.0))
    claim_abs = claim_value * cs
    ev_abs = ev_value * es
    if ev_abs == 0:
        return 0.0
    ratio = claim_abs / ev_abs
    return 1.0 if 0.99 <= ratio <= 1.01 else 0.0


def _growth_match(claim_text: str, ev_growth: float | None) -> float:
    """claim 含增长率主张时，evidence 有 growth 即算匹配信号。"""
    if ev_growth is None:
        return 0.0
    if any(w in claim_text for w in ("同比", "增长", "下降", "YoY", "增减", "增幅")):
        return 1.0
    return 0.5


def _period_match(claim_period: str | None, ev_periods: list[str]) -> float:
    if not claim_period or not ev_periods:
        return 0.0
    year = re.search(r"(19|20)\d{2}", str(claim_period))
    if not year:
        return 0.0
    return 1.0 if any(y == f"{year.group(0)}年" for y in ev_periods) else 0.0


def _table_match(claim_sections: list[str], ev_table_type: str) -> float:
    if not claim_sections:
        return 0.0
    for sec in claim_sections:
        if _SECTION_TO_TABLE.get(sec) == ev_table_type:
            return 1.0
    return 0.0


def retrieve_financial_evidence(
    claim: dict,
    target_sections: list[str] | None = None,
    top_k: int = 50,
    weights: dict | None = None,
) -> list[dict]:
    """从 evidence index 检索财务证据候选，按复合分降序返回。"""
    w = weights or {"metric": 0.40, "value": 0.30, "growth": 0.10, "period": 0.10, "table": 0.10}
    claim_text = str(claim.get("original_text") or claim.get("claim_text") or "")
    claim_code = str(claim.get("metric_code") or "").strip() or str(claim.get("metric") or "").strip()
    claim_value = claim.get("reported_value") or claim.get("value")
    if isinstance(claim_value, str):
        try:
            claim_value = float(claim_value.replace(",", ""))
        except ValueError:
            claim_value = None
    claim_unit = str(claim.get("unit") or "").strip()
    claim_period = claim.get("period")

    scored: list[dict] = []
    for ev in _load_index():
        m = _metric_match(claim_code, ev.get("metric_code", ""))
        v = _value_compatible(claim_value, claim_unit, ev.get("current_value"), ev.get("unit"))
        g = _growth_match(claim_text, ev.get("growth"))
        p = _period_match(claim_period, ev.get("periods", []))
        t = _table_match(target_sections or [], ev.get("table_type", ""))
        score = (w["metric"] * m + w["value"] * v + w["growth"] * g
                 + w["period"] * p + w["table"] * t)
        if score <= 0:
            continue
        scored.append({
            **ev,
            "retrieval_score": round(score, 4),
            "match_components": {"metric": m, "value": v, "growth": g, "period": p, "table": t},
        })
    scored.sort(key=lambda e: -e["retrieval_score"])
    return scored[:top_k]
