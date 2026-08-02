"""Compliance Agent（Phase 9）：检查投资材料的合规问题。

Evidence First：所有合规结论必须引用已有核验/证据，
不引入未核验的信息。

检查（任务书 §5）：投资材料是否存在
- UNSUPPORTED_CLAIM      无证据支持的主张
- OVERSTATEMENT          夸大表达
- MISSING_EVIDENCE       证据缺失
- FORECAST_AS_FACT       预测被描述为事实

工具调用（可追溯）：
- audit.report_json      读取核验结果（verification_results）
- risk_engine.assess_audit  读取风险评分（risk_type / risk_score）
- read_investment_material  读取投资材料原文做关键词检查

输入（AgentTask）：
- document_id     投资材料文档 ID
- audit_id        已有审计任务 ID（必填）
- intelligence_report_id  已有情报报告 ID（可选）

输出：ComplianceFindings
  findings[] / unsupported_claim_count / overstatement_count /
  missing_evidence_count / forecast_as_fact_count /
  overall_compliance_score（0-100，越高越不合规）

设计约束：不输出投资建议、不自动决定买卖、保持 Human-in-the-loop。
不修改已有核心模块。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, DocumentBlock
from app.models.audit import AuditReport
from app.services.investment_committee.schemas import (
    AGENT_COMPLIANCE,
    AGENT_STATUS_DONE,
    AGENT_STATUS_FAILED,
    COMPLIANCE_DEFAULT_SCORE,
    COMPLIANCE_FORECAST_AS_FACT,
    COMPLIANCE_MISSING_EVIDENCE,
    COMPLIANCE_OVERSTATEMENT,
    COMPLIANCE_UNSUPPORTED_CLAIM,
    AgentResult,
    ComplianceFinding,
    ComplianceFindings,
    severity_of,
)

# ---------------------------------------------------------------------------
# 工具调用清单（可追溯）
# ---------------------------------------------------------------------------
TOOL_AUDIT_REPORT = "audit.report_json"
TOOL_RISK_ENGINE = "risk_engine.assess_audit"
TOOL_READ_INVESTMENT_MATERIAL = "read_investment_material"

COMPLIANCE_TOOLS = [TOOL_AUDIT_REPORT, TOOL_RISK_ENGINE, TOOL_READ_INVESTMENT_MATERIAL]

# ---------------------------------------------------------------------------
# 关键词：夸大表达 / 预测被描述为事实
# ---------------------------------------------------------------------------
# 夸大表达：绝对化、最强、唯一、领跑、龙头（用于投资观点的定性）
_OVERSTATEMENT_KW = (
    "唯一",
    "最强",
    "绝对",
    "遥遥领先",
    "无可争议",
    "世界第一",
    "全球第一",
    "行业第一",
    "龙头",
    "领跑",
    "顶级",
    "独占",
)

# 预测被描述为事实：未来时态 / 持续 / 必将 / 一定 / 注定
_FORECAST_AS_FACT_KW = (
    "必将",
    "一定",
    "注定",
    "持续高速增长",
    "永远",
    "未来一定",
    "确定增长",
    "确定翻倍",
    "未来将实现",
    "持续保持",
)

# 预测类主张识别正则：含"未来/预计/有望/计划/将"等预测信号词
_FORECAST_SIGNAL_RE = re.compile(
    r"(未来|预计|有望|计划|将要|预期|展望|forecast|will|expect)"
)


# ---------------------------------------------------------------------------
# 工具 1：读取核验结果
# ---------------------------------------------------------------------------
def _call_audit_verification(session: Session, audit_id: int) -> list[dict]:
    """读取审计报告中的核验结果。"""
    row = session.get(AuditReport, audit_id)
    if row is None:
        return []
    report = json.loads(row.report_json or "{}")
    return report.get("verification_results", [])


# ---------------------------------------------------------------------------
# 工具 2：读取风险评分（claim_details）
# ---------------------------------------------------------------------------
def _call_risk_engine(session: Session, audit_id: int) -> dict:
    """读取 Risk Engine 的 claim_details / risk_distribution。"""
    from app.services.risk.risk_engine import assess_audit

    report = assess_audit(session, audit_id, persist=False)
    return report.to_dict()


# ---------------------------------------------------------------------------
# 工具 3：读取投资材料原文
# ---------------------------------------------------------------------------
def _call_read_investment_material(session: Session, document_id: int) -> str:
    """读取投资材料原文（拼接文档块）。"""
    blocks = (
        session.query(DocumentBlock)
        .filter(DocumentBlock.document_id == document_id)
        .order_by(DocumentBlock.id)
        .all()
    )
    return "\n".join((b.text or "") for b in blocks)


# ---------------------------------------------------------------------------
# 检查 1：UNSUPPORTED_CLAIM —— 无证据支持的主张
# ---------------------------------------------------------------------------
def _check_unsupported_claim(
    verification_results: list[dict],
    risk_report: dict,
) -> list[ComplianceFinding]:
    """核验状态为 INSUFFICIENT/UNABLE 的主张视为无证据支持。"""
    findings: list[ComplianceFinding] = []
    unsupported_statuses = {"INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE"}

    claim_details_by_id = {
        cd.get("claim_id"): cd for cd in risk_report.get("claim_details", [])
    }

    for v in verification_results:
        status = v.get("verification_status", "")
        if status not in unsupported_statuses:
            continue
        claim_id = v.get("claim_id", "")
        risk_detail = claim_details_by_id.get(claim_id, {})
        risk_score = float(risk_detail.get("risk_score", COMPLIANCE_DEFAULT_SCORE[COMPLIANCE_UNSUPPORTED_CLAIM]))
        findings.append(
            ComplianceFinding(
                finding_id="",  # 由 run_compliance 统一编号
                check_type=COMPLIANCE_UNSUPPORTED_CLAIM,
                claim_id=claim_id,
                claim_text=v.get("reason", "")[:120],
                description=f"主张核验状态为 {status}，缺乏证据支持",
                severity=severity_of(risk_score),
                risk_score=risk_score,
                evidence_refs=[claim_id] if claim_id else [],
            )
        )
    return findings


# ---------------------------------------------------------------------------
# 检查 2：OVERSTATEMENT —— 夸大表达
# ---------------------------------------------------------------------------
def _check_overstatement(
    investment_material: str,
    verification_results: list[dict],
) -> list[ComplianceFinding]:
    """投资材料中含绝对化/夸大关键词的主张。"""
    findings: list[ComplianceFinding] = []
    # 对每条核验主张检查是否含夸大关键词
    for v in verification_results:
        claim_id = v.get("claim_id", "")
        reason = v.get("reason", "")
        # 检查 reason 与投资材料中是否含夸大关键词
        text_to_check = f"{reason} {investment_material}"
        matched_kw = [kw for kw in _OVERSTATEMENT_KW if kw in text_to_check]
        if not matched_kw:
            continue
        risk_score = COMPLIANCE_DEFAULT_SCORE[COMPLIANCE_OVERSTATEMENT]
        findings.append(
            ComplianceFinding(
                finding_id="",
                check_type=COMPLIANCE_OVERSTATEMENT,
                claim_id=claim_id,
                claim_text=reason[:120] if reason else "（夸大表达）",
                description=f"投资材料含夸大表达关键词：{', '.join(matched_kw[:3])}",
                severity=severity_of(risk_score),
                risk_score=risk_score,
                evidence_refs=[claim_id] if claim_id else [],
            )
        )
    return findings


# ---------------------------------------------------------------------------
# 检查 3：MISSING_EVIDENCE —— 证据缺失
# ---------------------------------------------------------------------------
def _check_missing_evidence(
    verification_results: list[dict],
    risk_report: dict,
) -> list[ComplianceFinding]:
    """核验状态为 REFUTED/PARTIALLY_SUPPORTED 且证据质量低的主张。"""
    findings: list[ComplianceFinding] = []
    # PARTIALLY_SUPPORTED 或 REFUTED 且 evidence_quality < 0.5 → 证据缺失
    target_statuses = {"REFUTED", "PARTIALLY_SUPPORTED"}

    claim_details_by_id = {
        cd.get("claim_id"): cd for cd in risk_report.get("claim_details", [])
    }

    for v in verification_results:
        status = v.get("verification_status", "")
        if status not in target_statuses:
            continue
        claim_id = v.get("claim_id", "")
        risk_detail = claim_details_by_id.get(claim_id, {})
        evidence_quality = float(risk_detail.get("evidence_quality", 0.3))
        if evidence_quality >= 0.5:
            continue  # 证据质量尚可，不算缺失
        risk_score = COMPLIANCE_DEFAULT_SCORE[COMPLIANCE_MISSING_EVIDENCE]
        findings.append(
            ComplianceFinding(
                finding_id="",
                check_type=COMPLIANCE_MISSING_EVIDENCE,
                claim_id=claim_id,
                claim_text=v.get("reason", "")[:120],
                description=f"主张核验状态为 {status}，证据质量低（{evidence_quality:.1f}）",
                severity=severity_of(risk_score),
                risk_score=risk_score,
                evidence_refs=[claim_id] if claim_id else [],
            )
        )
    return findings


# ---------------------------------------------------------------------------
# 检查 4：FORECAST_AS_FACT —— 预测被描述为事实
# ---------------------------------------------------------------------------
def _check_forecast_as_fact(
    verification_results: list[dict],
    risk_report: dict,
) -> list[ComplianceFinding]:
    """预测类主张（含未来/预计等信号词）被描述为事实。"""
    findings: list[ComplianceFinding] = []

    claim_details_by_id = {
        cd.get("claim_id"): cd for cd in risk_report.get("claim_details", [])
    }

    for v in verification_results:
        claim_id = v.get("claim_id", "")
        reason = v.get("reason", "")
        risk_detail = claim_details_by_id.get(claim_id, {})
        risk_type = risk_detail.get("risk_type", "")

        # 预测信号词检测
        text_to_check = f"{reason}"
        is_forecast_signal = bool(_FORECAST_SIGNAL_RE.search(text_to_check))

        # Risk Engine 已标记 FORECAST_RISK 的主张
        is_forecast_risk = risk_type == "FORECAST_RISK"

        if not (is_forecast_signal or is_forecast_risk):
            continue

        # 预测被描述为事实：含"持续/必将/一定"等绝对化预测词
        has_absolutism = any(kw in text_to_check for kw in _FORECAST_AS_FACT_KW)
        if not (has_absolutism or is_forecast_risk):
            continue

        risk_score = COMPLIANCE_DEFAULT_SCORE[COMPLIANCE_FORECAST_AS_FACT]
        existing_score = float(risk_detail.get("risk_score", 0.0))
        # 取较高者作为合规风险分
        risk_score = max(risk_score, existing_score)

        findings.append(
            ComplianceFinding(
                finding_id="",
                check_type=COMPLIANCE_FORECAST_AS_FACT,
                claim_id=claim_id,
                claim_text=reason[:120] if reason else "（预测表达）",
                description="预测类主张被描述为事实，缺少历史数据支持",
                severity=severity_of(risk_score),
                risk_score=risk_score,
                evidence_refs=[claim_id] if claim_id else [],
            )
        )
    return findings


# ---------------------------------------------------------------------------
# 合规评分聚合
# ---------------------------------------------------------------------------
def _aggregate_compliance_score(findings: list[ComplianceFinding]) -> float:
    """整体合规评分：所有合规发现的平均风险分（0-100，越高越不合规）。

    无合规发现 → 0.0（完全合规）。
    """
    if not findings:
        return 0.0
    scores = [f.risk_score for f in findings if f.risk_score > 0]
    if not scores:
        return 0.0
    # 平均 + 0.3 × 最高（兼顾"普遍不合规"与"个别严重"）
    avg = sum(scores) / len(scores)
    highest = max(scores)
    overall = 0.7 * avg + 0.3 * highest
    return round(min(100.0, overall), 1)


# ---------------------------------------------------------------------------
# 主入口：run_compliance
# ---------------------------------------------------------------------------
def run_compliance(session: Session, task: AgentTask) -> AgentResult:
    """Compliance Agent 主入口：检查投资材料的合规问题。"""
    if task.agent != AGENT_COMPLIANCE:
        return AgentResult(
            agent=AGENT_COMPLIANCE,
            status=AGENT_STATUS_FAILED,
            error=f"Compliance Agent 收到非法任务: {task.agent}",
        )

    if task.audit_id is None:
        return AgentResult(
            agent=AGENT_COMPLIANCE,
            status=AGENT_STATUS_FAILED,
            error="Compliance Agent 需要 audit_id（已有审计任务 ID）",
        )

    # 工具调用
    verification_results = _call_audit_verification(session, task.audit_id)
    risk_report = _call_risk_engine(session, task.audit_id)
    investment_material = _call_read_investment_material(session, task.document_id)

    # 四类合规检查
    findings: list[ComplianceFinding] = []
    findings.extend(_check_unsupported_claim(verification_results, risk_report))
    findings.extend(_check_overstatement(investment_material, verification_results))
    findings.extend(_check_missing_evidence(verification_results, risk_report))
    findings.extend(_check_forecast_as_fact(verification_results, risk_report))

    # 统一编号 COMP-0001
    for idx, f in enumerate(findings, start=1):
        f.finding_id = f"COMP-{idx:04d}"

    # 统计
    unsupported_count = sum(1 for f in findings if f.check_type == COMPLIANCE_UNSUPPORTED_CLAIM)
    overstatement_count = sum(1 for f in findings if f.check_type == COMPLIANCE_OVERSTATEMENT)
    missing_evidence_count = sum(1 for f in findings if f.check_type == COMPLIANCE_MISSING_EVIDENCE)
    forecast_as_fact_count = sum(1 for f in findings if f.check_type == COMPLIANCE_FORECAST_AS_FACT)

    overall_compliance_score = _aggregate_compliance_score(findings)

    compliance_findings = ComplianceFindings(
        findings=findings,
        unsupported_claim_count=unsupported_count,
        overstatement_count=overstatement_count,
        missing_evidence_count=missing_evidence_count,
        forecast_as_fact_count=forecast_as_fact_count,
        overall_compliance_score=overall_compliance_score,
    )

    evidence_refs = list(
        dict.fromkeys(
            ref for f in findings for ref in f.evidence_refs if ref
        )
    )

    summary = (
        f"Compliance Agent 完成合规检查：合规风险评分 {overall_compliance_score}/100；"
        f"无证据支持 {unsupported_count} / 夸大表达 {overstatement_count} / "
        f"证据缺失 {missing_evidence_count} / 预测描述为事实 {forecast_as_fact_count}。"
    )

    return AgentResult(
        agent=AGENT_COMPLIANCE,
        status=AGENT_STATUS_DONE,
        findings=[compliance_findings.to_dict()],
        summary=summary,
        tools_called=COMPLIANCE_TOOLS,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "COMPLIANCE_TOOLS",
    "run_compliance",
]
