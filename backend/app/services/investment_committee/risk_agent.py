"""Risk Agent（Phase 9）：调用已有 Verification / Risk Engine / Intelligence。

Evidence First：所有风险结论必须引用已有核验/风险/情报证据，
不引入未核验的信息。

输入（AgentTask）：
- document_id     投资材料文档 ID
- audit_id        已有审计任务 ID（Risk Agent 必填）
- intelligence_report_id  已有情报报告 ID（可选；无则仅用 Risk Engine）

工具调用（可追溯）：
- assess_audit（Risk Engine）         整体风险评分 + claim_details
- get_investment_memo / Verification  核验结果摘要
- get_report（Intelligence Agent）    冲突结论 + Verified Facts

输出（任务书 §4）：
- Risk Findings       来自 Risk Engine 的 claim_details / top_risks
- Conflict Findings   来自 Intelligence 的 Conflicts
- Risk Score          整体风险评分（取 Risk Engine 与 Intelligence 的较高者）

设计约束：不输出投资建议、不自动决定买卖、保持 Human-in-the-loop。
不修改已有核心模块（Verification / Risk / Intelligence / Audit / Investment Memo）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Document
from app.models.audit import AuditReport
from app.services.investment_committee.schemas import (
    AGENT_RISK,
    AGENT_STATUS_DONE,
    AGENT_STATUS_FAILED,
    AgentResult,
    AgentTask,
    RiskFindings,
    risk_level_of,
)

# ---------------------------------------------------------------------------
# 工具调用清单（可追溯）
# ---------------------------------------------------------------------------
TOOL_RISK_ENGINE = "risk_engine.assess_audit"
TOOL_INTELLIGENCE = "intelligence_agent.get_report"
TOOL_AUDIT_REPORT = "audit.report_json"

RISK_TOOLS = [TOOL_RISK_ENGINE, TOOL_INTELLIGENCE, TOOL_AUDIT_REPORT]


# ---------------------------------------------------------------------------
# 工具 1：Risk Engine（assess_audit）
# ---------------------------------------------------------------------------
def _call_risk_engine(session: Session, audit_id: int) -> dict:
    """调用 Risk Engine 生成整体风险评分与 claim_details。"""
    from app.services.risk.risk_engine import assess_audit

    report = assess_audit(session, audit_id, persist=False)
    return report.to_dict()


# ---------------------------------------------------------------------------
# 工具 2：Intelligence Agent（get_report）
# ---------------------------------------------------------------------------
def _call_intelligence(session: Session, intelligence_report_id: int | None) -> dict:
    """调用 Intelligence Agent 读取冲突结论与 Verified Facts。"""
    if intelligence_report_id is None:
        return {}
    from app.services.intelligence.intelligence_agent import get_report

    try:
        report = get_report(session, intelligence_report_id)
    except LookupError:
        return {}
    return report.to_dict()


# ---------------------------------------------------------------------------
# 工具 3：Audit Report（核验结果摘要）
# ---------------------------------------------------------------------------
def _call_audit_report(session: Session, audit_id: int) -> dict:
    """读取审计报告中的核验结果摘要。"""
    row = session.get(AuditReport, audit_id)
    if row is None:
        return {}
    import json

    report = json.loads(row.report_json or "{}")
    verification_results = report.get("verification_results", [])
    # 按核验状态聚合
    status_counts: dict[str, int] = {}
    for v in verification_results:
        status = v.get("verification_status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "total_claims": len(verification_results),
        "status_counts": status_counts,
        "summary": report.get("summary", {}),
    }


# ---------------------------------------------------------------------------
# Risk Findings 构建
# ---------------------------------------------------------------------------
def _build_risk_findings_from_engine(risk_report: dict) -> tuple[list[dict], list[str]]:
    """从 Risk Engine 的 claim_details 提取风险点（非 SUPPORTED 或 risk_score>0）。"""
    claim_details = risk_report.get("claim_details", [])
    top_risks = risk_report.get("top_risks", [])

    # 优先用 top_risks（已按风险分数排序）
    risk_findings: list[dict] = []
    evidence_refs: list[str] = []
    for item in top_risks:
        risk_findings.append(
            {
                "claim_id": item.get("claim_id", ""),
                "risk_score": round(item.get("risk_score", 0.0), 1),
                "risk_level": item.get("risk_level", "LOW"),
                "risk_type": item.get("risk_type", ""),
                "verification_status": item.get("verification_status", ""),
                "risk_reason": item.get("risk_reason", []),
            }
        )
    # 补充 claim_details 中未在 top_risks 的风险点
    top_ids = {i.get("claim_id") for i in top_risks}
    for item in claim_details:
        cid = item.get("claim_id")
        if cid in top_ids:
            continue
        if item.get("risk_score", 0.0) <= 0:
            continue
        risk_findings.append(
            {
                "claim_id": cid or "",
                "risk_score": round(item.get("risk_score", 0.0), 1),
                "risk_level": item.get("risk_level", "LOW"),
                "risk_type": item.get("risk_type", ""),
                "verification_status": item.get("verification_status", ""),
                "risk_reason": item.get("risk_reason", []),
            }
        )
    return risk_findings, evidence_refs


def _build_conflict_findings_from_intelligence(intel_report: dict) -> tuple[list[dict], list[str]]:
    """从 Intelligence Report 提取冲突结论（仅保留冲突项，非 NO_OPPOSITION）。"""
    conflicts: list[dict] = []
    evidence_refs: list[str] = []
    for c in intel_report.get("conflicts", []):
        if c.get("conflict_type") == "NO_OPPOSITION":
            continue
        conflicts.append(
            {
                "finding_id": c.get("finding_id", ""),
                "claim_id": c.get("claim_id", ""),
                "claim": c.get("claim", ""),
                "fact": c.get("fact", ""),
                "conflict_type": c.get("conflict_type", ""),
                "difference": c.get("difference", ""),
                "risk_type": c.get("risk_type", ""),
                "risk_score": round(c.get("risk_score", 0.0), 1),
                "risk_level": c.get("risk_level", "LOW"),
            }
        )
    # Verified Facts 作为证据引用
    for f in intel_report.get("verified_facts", []):
        fid = f.get("fact_id", "")
        if fid:
            evidence_refs.append(fid)
    return conflicts, evidence_refs


# ---------------------------------------------------------------------------
# Risk Score 聚合（取 Risk Engine 与 Intelligence 的较高者）
# ---------------------------------------------------------------------------
def _aggregate_risk_score(
    risk_report: dict,
    intel_report: dict,
) -> tuple[float, str]:
    """整体风险评分：max(Risk Engine overall, Intelligence overall)。"""
    engine_score = float(risk_report.get("overall_risk_score", 0.0))
    intel_score = float(intel_report.get("overall_risk_score", 0.0))
    overall = max(engine_score, intel_score)
    return round(overall, 1), risk_level_of(overall)


# ---------------------------------------------------------------------------
# 主入口：run_risk
# ---------------------------------------------------------------------------
def run_risk(session: Session, task: AgentTask) -> AgentResult:
    """Risk Agent 主入口：调用 Verification / Risk / Intelligence。"""
    if task.agent != AGENT_RISK:
        return AgentResult(
            agent=AGENT_RISK,
            status=AGENT_STATUS_FAILED,
            error=f"Risk Agent 收到非法任务: {task.agent}",
        )

    if task.audit_id is None:
        return AgentResult(
            agent=AGENT_RISK,
            status=AGENT_STATUS_FAILED,
            error="Risk Agent 需要 audit_id（已有审计任务 ID）",
        )

    # 工具调用
    try:
        risk_report = _call_risk_engine(session, task.audit_id)
    except LookupError as exc:
        return AgentResult(
            agent=AGENT_RISK,
            status=AGENT_STATUS_FAILED,
            error=str(exc),
        )

    intel_report = _call_intelligence(session, task.intelligence_report_id)
    audit_summary = _call_audit_report(session, task.audit_id)

    # 构建 Risk Findings
    risk_findings, _ = _build_risk_findings_from_engine(risk_report)
    conflict_findings, intel_evidence_refs = _build_conflict_findings_from_intelligence(intel_report)

    # 整体风险评分
    overall_score, overall_level = _aggregate_risk_score(risk_report, intel_report)

    # 证据引用（Risk Engine 的 claim_id + Intelligence 的 fact_id）
    evidence_refs = list(
        dict.fromkeys(
            [f.get("claim_id", "") for f in risk_findings if f.get("claim_id")]
            + intel_evidence_refs
        )
    )

    findings = RiskFindings(
        risk_score=overall_score,
        risk_level=overall_level,
        risk_findings=risk_findings,
        conflict_findings=conflict_findings,
        verification_summary=audit_summary,
        evidence_refs=evidence_refs,
    )

    summary = (
        f"Risk Agent 完成风险评估：整体风险 {overall_score}/100 {overall_level}"
        f"（Risk Engine {risk_report.get('overall_risk_score', 0.0)}"
        f" vs Intelligence {intel_report.get('overall_risk_score', 0.0)}）；"
        f"风险点 {len(risk_findings)} 项 / 冲突 {len(conflict_findings)} 项。"
    )

    return AgentResult(
        agent=AGENT_RISK,
        status=AGENT_STATUS_DONE,
        findings=[findings.to_dict()],
        summary=summary,
        tools_called=RISK_TOOLS,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "RISK_TOOLS",
    "run_risk",
]
