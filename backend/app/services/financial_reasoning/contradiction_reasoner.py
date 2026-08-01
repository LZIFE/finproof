"""FinProof Contradiction Reasoner（Phase 16，任务书 §5）。

检测冲突类型：
- claim 与事实冲突
- 不同证据相互冲突
- 同一报告前后冲突
- 最新披露与旧披露冲突

输出冲突双方、来源、期间、指标和冲突原因。

约束：不替代 Verification；不输出投资建议。
"""

from __future__ import annotations

import re

from app.services.financial_reasoning.schemas import (
    Contradiction,
    ReasoningInput,
    ReasoningResult,
    STATUS_MIXED_EVIDENCE,
    STATUS_UNSUPPORTED,
    _now_iso,
)
from app.services.financial_reasoning.logic_rules import RULE_VERSION


# 方向关键词
_POS_KW = ("增长", "上升", "提升", "扩大", "改善", "上行", "增加", "回暖")
_NEG_KW = ("下降", "下滑", "减少", "收缩", "恶化", "下行", "回落", "降低")


def detect_contradictions(input_: ReasoningInput) -> list[Contradiction]:
    """检测四类冲突，返回 Contradiction 列表。"""
    contradictions: list[Contradiction] = []

    # 1) claim 与事实冲突（事实来自 evidence_candidates / KG facts）
    contradictions.extend(_claim_vs_facts(input_))

    # 2) 不同证据相互冲突
    contradictions.extend(_evidence_vs_evidence(input_))

    # 3) 同一报告前后冲突（document_id 相同但方向相反）
    contradictions.extend(_same_report_internal(input_))

    # 4) 最新披露 vs 旧披露冲突（period 不同且方向相反）
    contradictions.extend(_new_vs_old_disclosure(input_))

    return contradictions


def contradiction_to_results(
    input_: ReasoningInput,
    contradictions: list[Contradiction],
) -> list[ReasoningResult]:
    """将冲突转换为 ReasoningResult（便于统一展示与持久化）。"""
    results: list[ReasoningResult] = []
    if not contradictions:
        return results

    # 汇总支持与反证
    supporting = [
        ev for ev in input_.evidence_candidates
        if not any(k in (ev.get("text") or "") for k in _NEG_KW)
    ]
    counter = [
        ev for ev in input_.evidence_candidates
        if any(k in (ev.get("text") or "") for k in _NEG_KW)
    ]

    explanation_parts = ["检测到冲突："]
    for c in contradictions[:5]:
        explanation_parts.append(
            f"· {c.party_a} vs {c.party_b}（指标 {c.metric or '-'}，期间 {c.period_a or '-'} vs {c.period_b or '-'}）：{c.reason}"
        )

    # 判定 status：claim 与事实冲突 → UNSUPPORTED；其余 → MIXED_EVIDENCE
    has_claim_fact = any(c.party_a == "claim" for c in contradictions)
    status = STATUS_UNSUPPORTED if has_claim_fact else STATUS_MIXED_EVIDENCE

    results.append(ReasoningResult(
        reasoning_type="CONTRADICTION",
        status=status,
        premises=["多证据共存"],
        supporting_evidence=_ev_ids(supporting),
        counter_evidence=_ev_ids(counter),
        assumptions=[],
        logical_gap="；".join(c.reason for c in contradictions[:3]),
        confidence=0.80,
        explanation="\n".join(explanation_parts),
        suggested_safe_wording="存在证据冲突，结论应同时披露支持与反证，不宜单边表述。",
        triggered_rules=["C001-contradiction-detect"],
        evidence_ids=_collect_ids(supporting, counter),
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    ))
    return results


# ---------------------------------------------------------------------------
# 内部：四类冲突检测
# ---------------------------------------------------------------------------
def _claim_vs_facts(input_: ReasoningInput) -> list[Contradiction]:
    """1) claim 与事实冲突。"""
    out: list[Contradiction] = []
    claim_text = input_.claim_text
    claim_positive = any(k in claim_text for k in _POS_KW)
    claim_negative = any(k in claim_text for k in _NEG_KW)

    for ev in input_.evidence_candidates:
        ev_text = ev.get("text") or ""
        ev_positive = any(k in ev_text for k in _POS_KW)
        ev_negative = any(k in ev_text for k in _NEG_KW)
        # claim 正向但证据负向 → 冲突
        if claim_positive and ev_negative and not ev_positive:
            out.append(Contradiction(
                party_a="claim",
                party_b=ev.get("block_id") or ev.get("evidence_id") or "evidence",
                source_a="claim_text",
                source_b=ev.get("document_id") or ev.get("source") or "未知",
                period_a=input_.period or "",
                period_b=ev.get("page_number") or "",
                metric=_extract_metric(claim_text) or _extract_metric(ev_text),
                reason=f"claim 含正向表述但证据含负向：{ev_text[:60]}",
            ))
        elif claim_negative and ev_positive and not ev_negative:
            out.append(Contradiction(
                party_a="claim",
                party_b=ev.get("block_id") or ev.get("evidence_id") or "evidence",
                source_a="claim_text",
                source_b=ev.get("document_id") or ev.get("source") or "未知",
                period_a=input_.period or "",
                period_b=ev.get("page_number") or "",
                metric=_extract_metric(claim_text) or _extract_metric(ev_text),
                reason=f"claim 含负向表述但证据含正向：{ev_text[:60]}",
            ))
    return out


def _evidence_vs_evidence(input_: ReasoningInput) -> list[Contradiction]:
    """2) 不同证据相互冲突。"""
    out: list[Contradiction] = []
    evs = input_.evidence_candidates
    for i, a in enumerate(evs):
        for b in evs[i + 1:]:
            a_text = a.get("text") or ""
            b_text = b.get("text") or ""
            a_pos = any(k in a_text for k in _POS_KW)
            a_neg = any(k in a_text for k in _NEG_KW)
            b_pos = any(k in b_text for k in _POS_KW)
            b_neg = any(k in b_text for k in _NEG_KW)
            if (a_pos and b_neg and not a_neg and not b_pos) or (a_neg and b_pos and not a_pos and not b_neg):
                out.append(Contradiction(
                    party_a=a.get("block_id") or a.get("evidence_id") or "evidence-A",
                    party_b=b.get("block_id") or b.get("evidence_id") or "evidence-B",
                    source_a=a.get("document_id") or a.get("source") or "未知",
                    source_b=b.get("document_id") or b.get("source") or "未知",
                    period_a=a.get("page_number") or "",
                    period_b=b.get("page_number") or "",
                    metric=_extract_metric(a_text) or _extract_metric(b_text),
                    reason=f"两证据方向相反：A「{a_text[:40]}」vs B「{b_text[:40]}」",
                ))
    return out


def _same_report_internal(input_: ReasoningInput) -> list[Contradiction]:
    """3) 同一报告前后冲突（document_id 相同但方向相反）。"""
    out: list[Contradiction] = []
    by_doc: dict[str, list[dict]] = {}
    for ev in input_.evidence_candidates:
        doc = ev.get("document_id") or ev.get("source") or "未知"
        by_doc.setdefault(doc, []).append(ev)
    for doc, evs in by_doc.items():
        if len(evs) < 2:
            continue
        for i, a in enumerate(evs):
            for b in evs[i + 1:]:
                a_text = a.get("text") or ""
                b_text = b.get("text") or ""
                a_pos = any(k in a_text for k in _POS_KW)
                a_neg = any(k in a_text for k in _NEG_KW)
                b_pos = any(k in b_text for k in _POS_KW)
                b_neg = any(k in b_text for k in _NEG_KW)
                if (a_pos and b_neg and not a_neg and not b_pos) or (a_neg and b_pos and not a_pos and not b_neg):
                    out.append(Contradiction(
                        party_a=a.get("block_id") or "block-A",
                        party_b=b.get("block_id") or "block-B",
                        source_a=doc,
                        source_b=doc,
                        period_a=a.get("page_number") or "",
                        period_b=b.get("page_number") or "",
                        metric=_extract_metric(a_text) or _extract_metric(b_text),
                        reason=f"同一报告 {doc} 内前后方向相反",
                    ))
    return out


def _new_vs_old_disclosure(input_: ReasoningInput) -> list[Contradiction]:
    """4) 最新披露 vs 旧披露冲突（period 不同且方向相反）。"""
    out: list[Contradiction] = []
    # 按 period 分组（period 在 evidence 或 page 中）
    by_period: dict[str, list[dict]] = {}
    for ev in input_.evidence_candidates:
        p = ev.get("period") or _extract_period(ev.get("text") or "")
        if p:
            by_period.setdefault(p, []).append(ev)
    periods = list(by_period.keys())
    if len(periods) < 2:
        return out
    for i, p_new in enumerate(periods):
        for p_old in periods[i + 1:]:
            for a in by_period[p_new]:
                for b in by_period[p_old]:
                    a_text = a.get("text") or ""
                    b_text = b.get("text") or ""
                    a_pos = any(k in a_text for k in _POS_KW)
                    a_neg = any(k in a_text for k in _NEG_KW)
                    b_pos = any(k in b_text for k in _POS_KW)
                    b_neg = any(k in b_text for k in _NEG_KW)
                    if (a_pos and b_neg and not a_neg and not b_pos) or (a_neg and b_pos and not a_pos and not b_neg):
                        out.append(Contradiction(
                            party_a=a.get("block_id") or "new",
                            party_b=b.get("block_id") or "old",
                            source_a=a.get("document_id") or "未知",
                            source_b=b.get("document_id") or "未知",
                            period_a=p_new,
                            period_b=p_old,
                            metric=_extract_metric(a_text) or _extract_metric(b_text),
                            reason=f"最新披露 {p_new} 与旧披露 {p_old} 方向相反",
                        ))
    return out


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _extract_metric(text: str) -> str:
    metrics = ["净利润", "营业收入", "营收", "毛利率", "现金流", "海外收入", "海外业务", "利润率"]
    for m in metrics:
        if m in text:
            return m
    return ""


def _extract_period(text: str) -> str:
    match = re.search(r"(2024|2025|2026)(Q1|Q2|Q3|Q4|H1|H2|FY)", text)
    if match:
        return match.group(0)
    return ""


def _ev_ids(evidence: list[dict]) -> list[dict]:
    out = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        out.append({
            "evidence_id": ev.get("block_id") or ev.get("evidence_id") or ev.get("id"),
            "source": ev.get("document_id") or ev.get("source") or "未知",
            "page": ev.get("page_number") or ev.get("page"),
            "text": (ev.get("text") or ev.get("block_text") or "")[:200],
            "stance": ev.get("stance") or "NEUTRAL",
        })
    return out


def _collect_ids(supporting: list[dict], counter: list[dict]) -> list[str]:
    ids = []
    for ev in supporting + counter:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("block_id") or ev.get("evidence_id") or ev.get("id")
        if eid and eid not in ids:
            ids.append(str(eid))
    return ids


__all__ = [
    "detect_contradictions",
    "contradiction_to_results",
    "RULE_VERSION",
]
