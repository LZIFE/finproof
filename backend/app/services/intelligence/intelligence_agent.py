"""Investment Intelligence Agent（Phase 8）：投资调查辅助 Agent。

输入：投资标的（公司 + 投资材料中的观点 + 公司公开信息）

流程：
1. 投资观点登记（InvestmentClaim）
2. 公司事实抽取（fact_extractor：财报 + 公告/新闻/官网）
3. 冲突检测（conflict_detector：Claim vs Fact）
4. 报告汇总（Company Profile + Verified Facts + Conflicts +
            Risk Findings + Evidence Chain）

设计约束（任务书）：
- 不开发自动投资建议；
- 不进行股票推荐；
- 不替代投资经理决策。

保持 Evidence First：每条 Fact 与每条 Conflict 均附证据链可追溯。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document
from app.services.intelligence.conflict_detector import (
    DetectionResult,
    compute_overall_risk,
    detect_conflicts,
)
from app.services.intelligence.fact_extractor import (
    build_company_facts,
    register_external_facts_from_dicts,
)
from app.services.intelligence.schemas import (
    CompanyFact,
    CompanyProfile,
    ConflictFinding,
    IntelligenceReport,
    InvestmentClaim,
    RiskFinding,
    risk_level_of,
)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
# Company Profile 聚合（从 Facts 抽取公司画像）
# ---------------------------------------------------------------------------
def build_company_profile(
    company: str,
    stock_code: str,
    facts: list[CompanyFact],
) -> CompanyProfile:
    """从已登记的事实聚合公司画像。

    规则（可解释）：
    - business_fields：BUSINESS 维度事实的 subject 去重
    - key_financials：FINANCIAL 维度的事实（含数值）
    - market_coverage：MARKET 维度事实的关键词
    - products：PRODUCT 维度事实的 subject
    - competitors：COMPETITION 维度事实中出现的对手名
    """
    business_fields: list[str] = []
    key_financials: list[dict] = []
    market_coverage: list[str] = []
    products: list[str] = []
    competitors: list[str] = []

    for f in facts:
        if f.dimension == "BUSINESS" and f.subject and f.subject not in business_fields:
            business_fields.append(f.subject)
        elif f.dimension == "FINANCIAL" and f.value is not None:
            key_financials.append(
                {
                    "statement": f.statement,
                    "value": f.value,
                    "unit": f.unit,
                    "period": f.period,
                    "source_label": f.source_label,
                }
            )
        elif f.dimension == "MARKET":
            label = f.subject or f.statement
            if label and label not in market_coverage:
                market_coverage.append(label)
        elif f.dimension == "PRODUCT":
            label = f.subject or f.statement
            if label and label not in products:
                products.append(label)
        elif f.dimension == "COMPETITION":
            for comp in ("海尔", "格力", "海信", "西门子", "三星", "LG"):
                if comp in f"{f.subject} {f.statement} {f.evidence}" and comp not in competitors:
                    competitors.append(comp)

    return CompanyProfile(
        company=company,
        stock_code=stock_code,
        business_fields=business_fields,
        key_financials=key_financials[:10],
        market_coverage=market_coverage[:10],
        products=products[:10],
        competitors=competitors[:10],
    )


# ---------------------------------------------------------------------------
# Risk Findings：从冲突结论聚合
# ---------------------------------------------------------------------------
def build_risk_findings(
    findings: list[ConflictFinding],
) -> list[RiskFinding]:
    """将 ConflictFindings 转为 RiskFindings（仅保留风险项，按 risk_score 排序）。"""
    risks: list[RiskFinding] = []
    for f in findings:
        if f.conflict_type == "NO_OPPOSITION":
            continue
        risks.append(
            RiskFinding(
                finding_id=f.finding_id,
                claim_id=f.claim_id,
                risk_type=f.risk_type,
                risk_score=f.risk_score,
                risk_level=f.risk_level,
                summary=f.difference,
                conflict_type=f.conflict_type,
            )
        )
    risks.sort(key=lambda r: -r.risk_score)
    return risks


# ---------------------------------------------------------------------------
# Evidence Chain：Claim → External Evidence → Conflict/Support → Risk
# ---------------------------------------------------------------------------
def build_evidence_chain(
    claims: list[InvestmentClaim],
    facts: list[CompanyFact],
    findings: list[ConflictFinding],
) -> list[dict]:
    """构造证据链展示（任务书 §5：Claim ↓ Evidence ↓ Conflict/Support ↓ Risk）。"""
    finding_by_claim = {f.claim_id: f for f in findings}
    facts_by_id = {f.fact_id: f for f in facts}
    chain: list[dict] = []
    for c in claims:
        f = finding_by_claim.get(c.claim_id)
        if f is None:
            chain.append(
                {
                    "claim_id": c.claim_id,
                    "claim": c.claim,
                    "evidence": [],
                    "conflict_type": "NO_OPPOSITION",
                    "difference": "未比对",
                    "risk_score": 0.0,
                    "risk_level": "LOW",
                    "risk_type": "NONE",
                }
            )
            continue
        evidence_items: list[dict] = []
        for trace in f.evidence_trace:
            if trace.get("role") == "fact":
                fid = trace.get("fact_id", "")
                fact = facts_by_id.get(fid)
                evidence_items.append(
                    {
                        "fact_id": fid,
                        "source": trace.get("source", ""),
                        "source_label": trace.get("source_label", ""),
                        "timestamp": trace.get("timestamp", ""),
                        "confidence": trace.get("confidence", 0.0),
                        "text": trace.get("text", ""),
                        "fact_statement": fact.statement if fact else "",
                    }
                )
            elif trace.get("role") == "claim":
                evidence_items.append(
                    {
                        "role": "claim",
                        "text": trace.get("text", ""),
                    }
                )
        chain.append(
            {
                "claim_id": c.claim_id,
                "claim": c.claim,
                "evidence": evidence_items,
                "conflict_type": f.conflict_type,
                "difference": f.difference,
                "risk_score": round(f.risk_score, 1),
                "risk_level": f.risk_level,
                "risk_type": f.risk_type,
            }
        )
    return chain


# ---------------------------------------------------------------------------
# 主入口：run_investigation
# ---------------------------------------------------------------------------
def run_investigation(
    session: Session,
    document_id: int,
    claims: list[InvestmentClaim],
    external_fact_records: list[dict] | None = None,
) -> IntelligenceReport:
    """投资调查主流程。

    参数：
    - document_id：财报文档 ID（用于事实抽取）
    - claims：投资观点列表
    - external_fact_records：外部事实字典列表（公告/新闻/官网），可选

    返回：IntelligenceReport（不持久化，由调用方入库）。
    """
    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError(f"文档不存在: {document_id}")

    company = doc.company_name or ""
    stock_code = doc.stock_code or ""
    report_period = doc.report_period or ""

    # Step 1: 财报事实抽取
    report_facts = build_company_facts(session, document_id, external_facts=None)
    used_ids = [f.fact_id for f in report_facts]

    # Step 2: 外部事实登记（公告/新闻/官网）
    external_facts: list[CompanyFact] = []
    if external_fact_records:
        external_facts = register_external_facts_from_dicts(used_ids, external_fact_records)

    all_facts = report_facts + external_facts

    # Step 3: 冲突检测
    detection: DetectionResult = detect_conflicts(claims, all_facts)

    # Step 4: 报告汇总
    profile = build_company_profile(company, stock_code, all_facts)
    risk_findings = build_risk_findings(detection.findings)
    evidence_chain = build_evidence_chain(claims, all_facts, detection.findings)
    overall_score, overall_level = compute_overall_risk(detection.findings)

    report = IntelligenceReport(
        document_id=document_id,
        company=company,
        stock_code=stock_code,
        report_period=report_period,
        company_profile=profile,
        verified_facts=all_facts,
        conflicts=detection.findings,
        risk_findings=risk_findings,
        evidence_chain=evidence_chain,
        overall_risk_score=overall_score,
        overall_risk_level=overall_level,
        conflict_count=detection.conflict_count,
        support_count=detection.support_count,
        created_at=_now_iso(),
    )
    return report


# ---------------------------------------------------------------------------
# 持久化（IntelligenceReport → DB）
# ---------------------------------------------------------------------------
def save_report(session: Session, report: IntelligenceReport) -> IntelligenceReport:
    """持久化投资情报报告。"""
    from app.models.intelligence import IntelligenceReportRow

    row = IntelligenceReportRow(
        document_id=report.document_id,
        company=report.company,
        stock_code=report.stock_code,
        report_period=report.report_period,
        overall_risk_score=report.overall_risk_score,
        overall_risk_level=report.overall_risk_level,
        conflict_count=report.conflict_count,
        support_count=report.support_count,
        report_json=json.dumps(report.to_dict(), ensure_ascii=False),
    )
    session.add(row)
    session.flush()
    report.id = row.id
    session.commit()
    return report


def get_report(session: Session, report_id: int) -> IntelligenceReport:
    """读取持久化的投资情报报告。"""
    from app.models.intelligence import IntelligenceReportRow

    row = session.get(IntelligenceReportRow, report_id)
    if row is None:
        raise LookupError(f"投资情报报告不存在: {report_id}")
    data = json.loads(row.report_json or "{}")
    return _report_from_dict(row, data)


def _report_from_dict(row, data: dict) -> IntelligenceReport:
    """从持久化 JSON 还原 IntelligenceReport（保留核心字段）。"""
    profile_data = data.get("company_profile", {})
    profile = CompanyProfile(
        company=profile_data.get("company", ""),
        stock_code=profile_data.get("stock_code", ""),
        business_fields=profile_data.get("business_fields", []),
        key_financials=profile_data.get("key_financials", []),
        market_coverage=profile_data.get("market_coverage", []),
        products=profile_data.get("products", []),
        competitors=profile_data.get("competitors", []),
    )
    facts = [CompanyFact(**f) for f in data.get("verified_facts", [])]
    conflicts = [ConflictFinding(**c) for c in data.get("conflicts", [])]
    risk_findings = [RiskFinding(**r) for r in data.get("risk_findings", [])]
    return IntelligenceReport(
        id=row.id,
        document_id=row.document_id,
        company=row.company,
        stock_code=row.stock_code or "",
        report_period=row.report_period or "",
        company_profile=profile,
        verified_facts=facts,
        conflicts=conflicts,
        risk_findings=risk_findings,
        evidence_chain=data.get("evidence_chain", []),
        overall_risk_score=row.overall_risk_score,
        overall_risk_level=row.overall_risk_level,
        conflict_count=row.conflict_count,
        support_count=row.support_count,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z" if row.created_at else "",
    )


__all__ = [
    "run_investigation",
    "save_report",
    "get_report",
    "build_company_profile",
    "build_risk_findings",
    "build_evidence_chain",
]
