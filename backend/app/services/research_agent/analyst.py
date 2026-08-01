"""FinProof Research Analyst（Phase 17，任务书 §3）。

将收集的证据转为绑定 Evidence 的事实（ResearchFinding），并调用
Risk Engine / Reasoning Engine / Monitoring 发现风险。

无证据的事实 → supported=False（Open Question）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.financial_reasoning import reason_about
from app.services.financial_reasoning.schemas import ReasoningInput
from app.services.monitoring.detector import list_theses
from app.services.research_agent.schemas import (
    EvidenceRef,
    ResearchFinding,
    ResearchPlan,
    ResearchTaskSpec,
    RiskFinding,
    TASK_BUSINESS_ANALYSIS,
    TASK_COMPANY_PROFILE,
    TASK_COMPETITION_FACTS,
    TASK_FINANCIAL_OVERVIEW,
    TASK_RISK_DISCOVERY,
    ToolCall,
    _now_iso,
    risk_level_of,
)
from app.services.risk.risk_engine import assess_claim


def analyze_findings(
    session: Session,
    plan: ResearchPlan,
    evidence_by_task: dict[str, list[EvidenceRef]],
    tool_calls: list[ToolCall],
) -> tuple[list[ResearchFinding], list[RiskFinding]]:
    """分析证据 → 生成 ResearchFinding 列表 + RiskFinding 列表。"""
    findings: list[ResearchFinding] = []
    risk_findings: list[RiskFinding] = []

    for spec in plan.tasks:
        ev_list = evidence_by_task.get(spec.task_type, [])
        if not ev_list:
            # 无证据 → Open Question（不凭空生成事实）
            findings.append(ResearchFinding(
                task_type=spec.task_type,
                metric=spec.metric,
                content=f"{plan.company} {spec.objective}：未检索到证据，列入待验证事项。",
                evidence=[],
                supported=False,
                notes="无证据支持，转入 Open Questions",
            ))
            continue

        if spec.task_type == TASK_RISK_DISCOVERY:
            # 风险发现：调用 Risk Engine + Reasoning + Monitoring
            risks = _discover_risks(session, plan, spec, ev_list, tool_calls)
            risk_findings.extend(risks)
            # 同时把风险结论作为一条 finding
            for r in risks:
                findings.append(ResearchFinding(
                    task_type=spec.task_type,
                    metric=spec.metric,
                    content=r.content,
                    evidence=r.evidence,
                    supported=True,
                    risk_score=r.risk_score,
                    risk_level=r.risk_level,
                    notes=r.logical_gap,
                ))
        else:
            # 常规事实：每条证据抽出一句事实陈述
            for ev in ev_list[:3]:  # 每任务最多产出3条事实
                fact_text = _extract_fact(ev, plan.company, spec)
                findings.append(ResearchFinding(
                    task_type=spec.task_type,
                    metric=spec.metric,
                    content=fact_text,
                    evidence=[ev],
                    supported=True,
                ))

    return findings, risk_findings


# ---------------------------------------------------------------------------
# 内部：风险发现
# ---------------------------------------------------------------------------
def _discover_risks(
    session: Session,
    plan: ResearchPlan,
    spec: ResearchTaskSpec,
    evidence: list[EvidenceRef],
    tool_calls: list[ToolCall],
) -> list[RiskFinding]:
    """调用 Risk Engine / Reasoning / Monitoring 发现财务/业务/逻辑风险。"""
    risks: list[RiskFinding] = []

    # 1) Risk Engine：对每条证据做风险评估
    for ev in evidence[:3]:
        try:
            report = assess_claim(
                session,
                claim={"original_text": ev.text, "company": plan.company},
                evidence_candidates=[{"block_id": ev.block_id, "text": ev.text}],
            )
            score = float(getattr(report, "overall_risk_score", 0.0) or 0.0)
            if score > 0:
                risks.append(RiskFinding(
                    risk_type="financial",
                    source_tool="risk_engine",
                    content=f"风险评分 {score:.1f}（{risk_level_of(score)}）：{ev.text[:80]}",
                    evidence=[ev],
                    risk_score=score,
                    risk_level=risk_level_of(score),
                ))
        except Exception:  # noqa: BLE001
            pass
    tool_calls.append(ToolCall(
        tool="risk_engine",
        task_type=spec.task_type,
        input_summary=f"assess {len(evidence[:3])} evidence blocks",
        output_summary=f"{len([r for r in risks if r.source_tool == 'risk_engine'])} risk findings",
        evidence_count=len(evidence[:3]),
        timestamp=_now_iso(),
    ))

    # 2) Reasoning Engine：识别逻辑风险
    try:
        run = reason_about(session, ReasoningInput(
            claim_text=spec.claim_query,
            claim={"original_text": spec.claim_query, "company": plan.company},
            evidence_candidates=[{"block_id": e.block_id, "text": e.text, "document_id": e.document_id} for e in evidence],
            company=plan.company,
        ))
        for r in run.results:
            if r.logical_gap or r.status not in ("OK",):
                risks.append(RiskFinding(
                    risk_type="logic",
                    source_tool="reasoning",
                    content=r.explanation or r.logical_gap,
                    evidence=[EvidenceRef(block_id=eid) for eid in r.evidence_ids[:2]],
                    risk_score=float(r.confidence) * 100.0,
                    risk_level=risk_level_of(float(r.confidence) * 100.0),
                    logical_gap=r.logical_gap,
                ))
        tool_calls.append(ToolCall(
            tool="reasoning",
            task_type=spec.task_type,
            input_summary=spec.claim_query,
            output_summary=f"reasoning run {run.run_id} → {len(run.results)} results",
            evidence_count=len(evidence),
            timestamp=_now_iso(),
        ))
    except Exception as exc:  # noqa: BLE001
        tool_calls.append(ToolCall(
            tool="reasoning",
            task_type=spec.task_type,
            input_summary=spec.claim_query,
            output_summary=f"error: {exc}",
            success=False,
            timestamp=_now_iso(),
        ))

    # 3) Monitoring：历史观点冲突
    try:
        theses = list_theses(session)
        related = [t for t in theses if plan.company in (t.company or "")]
        if related:
            for t in related[:2]:
                risks.append(RiskFinding(
                    risk_type="business",
                    source_tool="monitoring",
                    content=f"历史观点冲突：{t.company} {t.claim_text[:60]}",
                    evidence=[],
                    risk_score=50.0,
                    risk_level="MEDIUM",
                ))
        tool_calls.append(ToolCall(
            tool="monitoring",
            task_type=spec.task_type,
            input_summary=f"list_theses for {plan.company}",
            output_summary=f"{len(related)} related theses",
            timestamp=_now_iso(),
        ))
    except Exception as exc:  # noqa: BLE001
        tool_calls.append(ToolCall(
            tool="monitoring",
            task_type=spec.task_type,
            input_summary=f"list_theses for {plan.company}",
            output_summary=f"error: {exc}",
            success=False,
            timestamp=_now_iso(),
        ))

    return risks


# ---------------------------------------------------------------------------
# 内部：从证据抽取一句事实陈述
# ---------------------------------------------------------------------------
def _extract_fact(ev: EvidenceRef, company: str, spec: ResearchTaskSpec) -> str:
    """从证据文本抽取一句事实陈述（不含投资观点）。"""
    text = (ev.text or "").strip()
    if not text:
        return f"{company} {spec.objective}：证据文本为空。"
    # 取首句或前 120 字
    first_sentence = text.split("。")[0] if "。" in text else text
    fact = first_sentence[:120]
    if len(first_sentence) < len(text):
        fact += "…"
    source = f"（来源 {ev.document_id} p{ev.page_number}）"
    return f"{fact}{source}"


__all__ = ["analyze_findings"]
