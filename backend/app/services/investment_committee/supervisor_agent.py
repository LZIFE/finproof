"""Supervisor Agent（Phase 9）：投资委员会多 Agent 协调器。

职责（任务书 §2）：
- 任务拆解：将投资材料审核拆为 Research / Risk / Compliance 子任务
- 调用子 Agent：依次执行 Research → Risk → Compliance
- 汇总结果：合并三 Agent 输出为 Investment Committee Report

流程（任务书 §7）：
  Supervisor
   ↓
  Research
   ↓
  Risk
   ↓
  Compliance
   ↓
  Final Report

设计约束（任务书）：
- 不输出投资建议；
- 不自动决定买卖；
- 保持 Human-in-the-loop（高风险/合规问题自动提请人工审核）；
- 不修改已有核心模块。

Evidence First：所有报告结论必须引用已有证据，
Agent 流程与工具调用全程可追溯。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document
from app.services.investment_committee.compliance_agent import run_compliance
from app.services.investment_committee.research_agent import run_research
from app.services.investment_committee.risk_agent import run_risk
from app.services.investment_committee.schemas import (
    AGENT_COMPLIANCE,
    AGENT_RESEARCH,
    AGENT_RISK,
    AGENT_SUPERVISOR,
    AGENT_STATUS_DONE,
    AGENT_STATUS_FAILED,
    AGENT_STATUS_RUNNING,
    AgentResult,
    AgentTask,
    BusinessAnalysis,
    CommitteeReport,
    ComplianceFindings,
    ExecutiveSummary,
    FinancialSummary,
    HumanReviewItem,
    ResearchFindings,
    RiskFindings,
    risk_level_of,
)

# ---------------------------------------------------------------------------
# Human Review 阈值（高于该分数自动提请人工审核）
# ---------------------------------------------------------------------------
REVIEW_SCORE_THRESHOLD = 60.0


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
# 任务拆解：Supervisor → AgentTask 列表
# ---------------------------------------------------------------------------
def split_tasks(
    document_id: int,
    audit_id: int | None,
    intelligence_report_id: int | None,
) -> list[AgentTask]:
    """将投资材料审核拆为三个 Agent 子任务。

    顺序：Research → Risk → Compliance（Risk/Compliance 需 audit_id）。
    """
    return [
        AgentTask(
            agent=AGENT_RESEARCH,
            document_id=document_id,
            audit_id=audit_id,
            intelligence_report_id=intelligence_report_id,
        ),
        AgentTask(
            agent=AGENT_RISK,
            document_id=document_id,
            audit_id=audit_id,
            intelligence_report_id=intelligence_report_id,
        ),
        AgentTask(
            agent=AGENT_COMPLIANCE,
            document_id=document_id,
            audit_id=audit_id,
            intelligence_report_id=intelligence_report_id,
        ),
    ]


# ---------------------------------------------------------------------------
# 子 Agent 调度
# ---------------------------------------------------------------------------
_AGENT_RUNNERS = {
    AGENT_RESEARCH: run_research,
    AGENT_RISK: run_risk,
    AGENT_COMPLIANCE: run_compliance,
}


def _dispatch(session: Session, task: AgentTask) -> AgentResult:
    """调用单个子 Agent。"""
    runner = _AGENT_RUNNERS.get(task.agent)
    if runner is None:
        return AgentResult(
            agent=task.agent,
            status=AGENT_STATUS_FAILED,
            error=f"未知 Agent: {task.agent}",
        )
    return runner(session, task)


# ---------------------------------------------------------------------------
# Agent 流程日志（前端展示用）
# ---------------------------------------------------------------------------
def _record_flow(agent: str, status: str, summary: str, tools: list[str]) -> dict:
    return {
        "agent": agent,
        "status": status,
        "summary": summary,
        "tools_called": tools,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# 报告各部分还原（从 AgentResult.findings 还原为 dataclass）
# ---------------------------------------------------------------------------
def _research_from_result(result: AgentResult) -> ResearchFindings:
    """还原 ResearchFindings（取 findings[0]）。"""
    if not result.findings:
        return ResearchFindings()
    from app.services.investment_committee.schemas import (
        BusinessAnalysis,
        CompanyOverview,
        FinancialSummary,
    )

    data = result.findings[0]
    co_data = data.get("company_overview", {})
    ba_data = data.get("business_analysis", {})
    fs_data = data.get("financial_summary", {})
    return ResearchFindings(
        company_overview=CompanyOverview(**co_data) if co_data else CompanyOverview(),
        business_analysis=BusinessAnalysis(**ba_data) if ba_data else BusinessAnalysis(),
        financial_summary=FinancialSummary(**fs_data) if fs_data else FinancialSummary(),
        evidence_refs=data.get("evidence_refs", []),
    )


def _risk_from_result(result: AgentResult) -> RiskFindings:
    if not result.findings:
        return RiskFindings()
    data = result.findings[0]
    return RiskFindings(
        risk_score=data.get("risk_score", 0.0),
        risk_level=data.get("risk_level", "LOW"),
        risk_findings=data.get("risk_findings", []),
        conflict_findings=data.get("conflict_findings", []),
        verification_summary=data.get("verification_summary", {}),
        evidence_refs=data.get("evidence_refs", []),
    )


def _compliance_from_result(result: AgentResult) -> ComplianceFindings:
    if not result.findings:
        return ComplianceFindings()
    data = result.findings[0]
    from app.services.investment_committee.schemas import ComplianceFinding

    findings = [ComplianceFinding(**f) for f in data.get("findings", [])]
    return ComplianceFindings(
        findings=findings,
        unsupported_claim_count=data.get("unsupported_claim_count", 0),
        overstatement_count=data.get("overstatement_count", 0),
        missing_evidence_count=data.get("missing_evidence_count", 0),
        forecast_as_fact_count=data.get("forecast_as_fact_count", 0),
        overall_compliance_score=data.get("overall_compliance_score", 0.0),
    )


# ---------------------------------------------------------------------------
# Human Review Items 自动提请（保持 Human-in-the-loop）
# ---------------------------------------------------------------------------
def _build_human_review_items(
    research: ResearchFindings,
    risk: RiskFindings,
    compliance: ComplianceFindings,
) -> list[HumanReviewItem]:
    """高风险/合规问题自动提请人工审核。

    - Risk Findings：risk_score ≥ 阈值
    - Conflict Findings：所有冲突项
    - Compliance Findings：severity HIGH 或 risk_score ≥ 阈值
    """
    items: list[HumanReviewItem] = []
    rev_idx = 1

    # Risk Findings
    for rf in risk.risk_findings:
        score = float(rf.get("risk_score", 0.0))
        if score < REVIEW_SCORE_THRESHOLD:
            continue
        items.append(
            HumanReviewItem(
                item_id=f"REV-{rev_idx:04d}",
                agent=AGENT_RISK,
                review_type="RISK",
                claim_id=rf.get("claim_id", ""),
                description=f"风险点：{rf.get('risk_type', '')} 风险分 {score}",
                risk_score=score,
                risk_level=risk_level_of(score),
            )
        )
        rev_idx += 1

    # Conflict Findings
    for cf in risk.conflict_findings:
        score = float(cf.get("risk_score", 0.0))
        if score < REVIEW_SCORE_THRESHOLD:
            continue
        items.append(
            HumanReviewItem(
                item_id=f"REV-{rev_idx:04d}",
                agent=AGENT_RISK,
                review_type="CONFLICT",
                claim_id=cf.get("claim_id", ""),
                description=f"冲突：{cf.get('difference', '')}",
                risk_score=score,
                risk_level=risk_level_of(score),
            )
        )
        rev_idx += 1

    # Compliance Findings
    for f in compliance.findings:
        if f.severity != "HIGH" and f.risk_score < REVIEW_SCORE_THRESHOLD:
            continue
        items.append(
            HumanReviewItem(
                item_id=f"REV-{rev_idx:04d}",
                agent=AGENT_COMPLIANCE,
                review_type="COMPLIANCE",
                claim_id=f.claim_id,
                description=f"合规：{f.description}",
                risk_score=f.risk_score,
                risk_level=risk_level_of(f.risk_score),
            )
        )
        rev_idx += 1

    return items


# ---------------------------------------------------------------------------
# Executive Summary 汇总
# ---------------------------------------------------------------------------
def _build_executive_summary(
    doc: Document,
    research: ResearchFindings,
    risk: RiskFindings,
    compliance: ComplianceFindings,
) -> ExecutiveSummary:
    """Supervisor 汇总三 Agent 结论为执行摘要。"""
    co = research.company_overview
    # 关键发现：风险/冲突/合规要点各取前三
    key_findings: list[str] = []

    # Research 关键发现
    if co.business_fields:
        key_findings.append(f"业务领域：{', '.join(co.business_fields[:3])}")
    if research.financial_summary.key_metrics:
        key_findings.append(
            f"关键财务：{research.financial_summary.key_metrics[0].get('statement', '')}"
        )

    # Risk 关键发现
    for rf in risk.risk_findings[:3]:
        key_findings.append(
            f"风险：{rf.get('risk_type', '')} {rf.get('risk_score', 0.0)}"
        )
    for cf in risk.conflict_findings[:2]:
        key_findings.append(f"冲突：{cf.get('difference', '')}")

    # Compliance 关键发现
    if compliance.findings:
        for f in compliance.findings[:3]:
            key_findings.append(f"合规：{f.description}")

    # 摘要文本
    research_summary = (
        f"调研覆盖业务 {len(co.business_fields)} 项 / 产品 {len(co.products)} 项 / "
        f"市场 {len(co.market_coverage)} 项 / �财务指标 {len(research.financial_summary.key_metrics)} 项。"
    )
    risk_summary = (
        f"整体风险 {risk.risk_score}/100 {risk.risk_level}；"
        f"风险点 {len(risk.risk_findings)} 项 / 冲突 {len(risk.conflict_findings)} 项。"
    )
    compliance_summary = (
        f"合规评分 {compliance.overall_compliance_score}/100；"
        f"无证据支持 {compliance.unsupported_claim_count} / 夸大表达 {compliance.overstatement_count} / "
        f"证据缺失 {compliance.missing_evidence_count} / 预测为事实 {compliance.forecast_as_fact_count}。"
    )

    return ExecutiveSummary(
        company=co.company or (doc.company_name or ""),
        stock_code=co.stock_code or (doc.stock_code or ""),
        report_period=co.report_period or (doc.report_period or ""),
        overall_risk_score=risk.risk_score,
        overall_risk_level=risk.risk_level,
        overall_compliance_score=compliance.overall_compliance_score,
        research_summary=research_summary,
        risk_summary=risk_summary,
        compliance_summary=compliance_summary,
        key_findings=key_findings[:10],
    )


# ---------------------------------------------------------------------------
# Evidence Chain：合并三 Agent 的证据引用
# ---------------------------------------------------------------------------
def _build_evidence_chain(
    research: ResearchFindings,
    risk: RiskFindings,
    compliance: ComplianceFindings,
) -> list[dict]:
    """合并各 Agent 的证据引用为可读证据链。"""
    chain: list[dict] = []

    # Research 证据
    chain.append(
        {
            "agent": AGENT_RESEARCH,
            "evidence_refs": research.evidence_refs,
            "summary": "Research Agent 引用的 Verified Facts 与文档块证据",
        }
    )

    # Risk 证据（claim_id + fact_id）
    chain.append(
        {
            "agent": AGENT_RISK,
            "evidence_refs": risk.evidence_refs,
            "summary": "Risk Agent 引用的核验结果与情报报告证据",
            "risk_findings_count": len(risk.risk_findings),
            "conflict_findings_count": len(risk.conflict_findings),
        }
    )

    # Compliance 证据（claim_id）
    comp_refs = list(
        dict.fromkeys(
            ref for f in compliance.findings for ref in f.evidence_refs if ref
        )
    )
    chain.append(
        {
            "agent": AGENT_COMPLIANCE,
            "evidence_refs": comp_refs,
            "summary": "Compliance Agent 引用的核验结果与投资材料证据",
            "compliance_findings_count": len(compliance.findings),
        }
    )

    return chain


# ---------------------------------------------------------------------------
# 主入口：run_committee
# ---------------------------------------------------------------------------
def run_committee(
    session: Session,
    document_id: int,
    audit_id: int | None,
    intelligence_report_id: int | None = None,
) -> CommitteeReport:
    """Supervisor 主入口：拆任务 → 调度三 Agent → 汇总报告。"""
    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError(f"文档不存在: {document_id}")

    # Step 1: 任务拆解
    tasks = split_tasks(document_id, audit_id, intelligence_report_id)

    # Step 2: 依次调度（Research → Risk → Compliance）
    agent_flow: list[dict] = []
    agent_results: dict[str, AgentResult] = {}

    for task in tasks:
        flow_entry = _record_flow(task.agent, AGENT_STATUS_RUNNING, "", [])
        result = _dispatch(session, task)
        agent_results[task.agent] = result
        # 更新流程日志
        flow_entry["status"] = result.status
        flow_entry["summary"] = result.summary
        flow_entry["tools_called"] = result.tools_called
        agent_flow.append(flow_entry)

    # Step 3: 汇总报告
    research = _research_from_result(agent_results.get(AGENT_RESEARCH, AgentResult(agent=AGENT_RESEARCH)))
    risk = _risk_from_result(agent_results.get(AGENT_RISK, AgentResult(agent=AGENT_RISK)))
    compliance = _compliance_from_result(agent_results.get(AGENT_COMPLIANCE, AgentResult(agent=AGENT_COMPLIANCE)))

    executive_summary = _build_executive_summary(doc, research, risk, compliance)
    human_review_items = _build_human_review_items(research, risk, compliance)
    evidence_chain = _build_evidence_chain(research, risk, compliance)

    # 整体风险（与 Risk Agent 一致）
    overall_score = risk.risk_score
    overall_level = risk.risk_level

    report = CommitteeReport(
        document_id=document_id,
        audit_id=audit_id,
        intelligence_report_id=intelligence_report_id,
        company=doc.company_name or "",
        stock_code=doc.stock_code or "",
        report_period=doc.report_period or "",
        agent_flow=agent_flow,
        agent_results=agent_results,
        executive_summary=executive_summary,
        research_findings=research,
        risk_findings=risk,
        compliance_findings=compliance,
        evidence_chain=evidence_chain,
        human_review_items=human_review_items,
        overall_risk_score=overall_score,
        overall_risk_level=overall_level,
        created_at=_now_iso(),
    )
    return report


# ---------------------------------------------------------------------------
# Phase 13：Supervisor 动态调查规划
# ---------------------------------------------------------------------------
def run_committee_autonomous(
    session: Session,
    document_id: int,
    audit_id: int | None,
    intelligence_report_id: int | None = None,
) -> CommitteeReport:
    """Phase 13 升级入口：Supervisor 根据风险类型动态生成调查计划。

    升级内容（任务书 §6）：
    - 升级 Supervisor：从固定调用 Research/Risk/Compliance
      → 根据任务动态生成调查计划。
    - 保留原流程作为 fallback：若自主调查失败，回退 run_committee。

    不修改已有核心逻辑；不输出投资建议、不自动交易、不替代投资经理。
    """
    from app.services.autonomous_agent import run_investigation
    from app.services.autonomous_agent.schemas import ClaimContext
    from app.services.autonomous_agent.planner import classify_claim_type

    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError(f"文档不存在: {document_id}")

    # 动态规划：以文档主张为输入，自主调查
    claim_text = doc.company_name or "投资材料审核"
    ctx = ClaimContext(
        claim_text=claim_text,
        company=doc.company_name or "",
        stock_code=doc.stock_code or "",
    )
    try:
        run = run_investigation(session, ctx, use_memory=True)
    except Exception:  # noqa: BLE001
        # Fallback：原 Research → Risk → Compliance 流程
        return run_committee(session, document_id, audit_id, intelligence_report_id)

    # 复用原 run_committee 的汇总逻辑（fallback 兼容）
    report = run_committee(session, document_id, audit_id, intelligence_report_id)
    # 在 agent_flow 前置自主调查记录
    autonomous_flow = _record_flow(
        AGENT_SUPERVISOR,
        AGENT_STATUS_DONE,
        f"自主调查 {run.trace_id}：{run.conclusion.get('summary', '')}",
        [s.tool for s in run.steps],
    )
    report.agent_flow = [autonomous_flow, *report.agent_flow]
    return report


# ---------------------------------------------------------------------------
# 持久化（CommitteeReport → DB）
# ---------------------------------------------------------------------------
def save_report(session: Session, report: CommitteeReport) -> CommitteeReport:
    """持久化投资委员会报告。"""
    from app.models.investment_committee import CommitteeReportRow

    row = CommitteeReportRow(
        document_id=report.document_id,
        audit_id=report.audit_id,
        intelligence_report_id=report.intelligence_report_id,
        company=report.company,
        stock_code=report.stock_code,
        report_period=report.report_period,
        overall_risk_score=report.overall_risk_score,
        overall_risk_level=report.overall_risk_level,
        overall_compliance_score=report.executive_summary.overall_compliance_score,
        agent_flow_json=json.dumps(report.agent_flow, ensure_ascii=False),
        report_json=json.dumps(report.to_dict(), ensure_ascii=False),
    )
    session.add(row)
    session.flush()
    report.id = row.id
    session.commit()
    return report


def get_report(session: Session, report_id: int) -> CommitteeReport:
    """读取持久化的投资委员会报告。"""
    from app.models.investment_committee import CommitteeReportRow

    row = session.get(CommitteeReportRow, report_id)
    if row is None:
        raise LookupError(f"投资委员会报告不存在: {report_id}")
    data = json.loads(row.report_json or "{}")
    return _report_from_dict(row, data)


def _report_from_dict(row, data: dict) -> CommitteeReport:
    """从持久化 JSON 还原 CommitteeReport。"""
    from app.services.investment_committee.schemas import (
        ComplianceFinding,
        CompanyOverview,
    )

    # 还原各部分
    research_data = data.get("research_findings", {})
    research = ResearchFindings(
        company_overview=CompanyOverview(**research_data.get("company_overview", {})),
        business_analysis=BusinessAnalysis(**research_data.get("business_analysis", {})),
        financial_summary=FinancialSummary(**research_data.get("financial_summary", {})),
        evidence_refs=research_data.get("evidence_refs", []),
    )

    risk_data = data.get("risk_findings", {})
    risk = RiskFindings(
        risk_score=risk_data.get("risk_score", 0.0),
        risk_level=risk_data.get("risk_level", "LOW"),
        risk_findings=risk_data.get("risk_findings", []),
        conflict_findings=risk_data.get("conflict_findings", []),
        verification_summary=risk_data.get("verification_summary", {}),
        evidence_refs=risk_data.get("evidence_refs", []),
    )

    comp_data = data.get("compliance_findings", {})
    compliance = ComplianceFindings(
        findings=[ComplianceFinding(**f) for f in comp_data.get("findings", [])],
        unsupported_claim_count=comp_data.get("unsupported_claim_count", 0),
        overstatement_count=comp_data.get("overstatement_count", 0),
        missing_evidence_count=comp_data.get("missing_evidence_count", 0),
        forecast_as_fact_count=comp_data.get("forecast_as_fact_count", 0),
        overall_compliance_score=comp_data.get("overall_compliance_score", 0.0),
    )

    exec_data = data.get("executive_summary", {})
    executive_summary = ExecutiveSummary(**exec_data)

    human_items = [HumanReviewItem(**h) for h in data.get("human_review_items", [])]

    # 还原 agent_results
    agent_results_raw = data.get("agent_results", {})
    agent_results = {
        k: AgentResult(
            agent=v.get("agent", k),
            status=v.get("status", "DONE"),
            findings=v.get("findings", []),
            summary=v.get("summary", ""),
            tools_called=v.get("tools_called", []),
            evidence_refs=v.get("evidence_refs", []),
            error=v.get("error", ""),
        )
        for k, v in agent_results_raw.items()
    }

    return CommitteeReport(
        id=row.id,
        document_id=row.document_id,
        audit_id=row.audit_id,
        intelligence_report_id=row.intelligence_report_id,
        company=row.company,
        stock_code=row.stock_code or "",
        report_period=row.report_period or "",
        agent_flow=data.get("agent_flow", []),
        agent_results=agent_results,
        executive_summary=executive_summary,
        research_findings=research,
        risk_findings=risk,
        compliance_findings=compliance,
        evidence_chain=data.get("evidence_chain", []),
        human_review_items=human_items,
        overall_risk_score=row.overall_risk_score,
        overall_risk_level=row.overall_risk_level,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z" if row.created_at else "",
    )


# ---------------------------------------------------------------------------
# 人工审核更新（保持 Human-in-the-loop）
# ---------------------------------------------------------------------------
def update_human_review(
    session: Session,
    report_id: int,
    item_id: str,
    review_status: str,
    note: str = "",
    reviewer: str = "",
) -> HumanReviewItem:
    """更新单个人工审核项状态（NEED_REVIEW / APPROVED / REJECTED）。"""
    if review_status not in ("NEED_REVIEW", "APPROVED", "REJECTED"):
        raise ValueError(f"非法审核状态: {review_status}")

    report = get_report(session, report_id)
    target: HumanReviewItem | None = None
    for item in report.human_review_items:
        if item.item_id == item_id:
            target = item
            break
    if target is None:
        raise LookupError(f"审核项不存在: report={report_id} item={item_id}")

    target.review_status = review_status
    target.note = note
    target.reviewer = reviewer

    # 持久化整个报告（覆盖）
    from app.models.investment_committee import CommitteeReportRow

    row = session.get(CommitteeReportRow, report_id)
    if row is None:
        raise LookupError(f"报告不存在: {report_id}")
    row.report_json = json.dumps(report.to_dict(), ensure_ascii=False)
    session.commit()

    return target


__all__ = [
    "REVIEW_SCORE_THRESHOLD",
    "split_tasks",
    "run_committee",
    "save_report",
    "get_report",
    "update_human_review",
]
