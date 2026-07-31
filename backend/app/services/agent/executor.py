"""Agent Executor（Phase 5）：执行完整审计流程并保存执行日志。

document_id → extract_claims → retrieve_evidence → verify_claims → generate_report → 入库
"""

import json

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.services.agent import tools
from app.services.agent.planner import build_audit_plan
from app.services.agent.report_generator import build_report
from app.services.agent.schemas import AuditPlan, AuditStep


def run_audit(session: Session, document_id: int, mode: str = "ai") -> dict:
    """执行一次完整审计（同步）：返回审计报告（并持久化 audit_reports）。"""
    tools.require_report_to_verify(session, document_id)
    plan = build_audit_plan(document_id)

    def step(name: str, detail: str = ""):
        plan.log.append(AuditStep(name=name, status="done", detail=detail))

    # Step 1: extract_claims
    try:
        claims = tools.extract_claims(session, document_id, mode=mode)
        step("extract_claims", f"Extracted {len(claims)} claims")
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"主张提取失败: {exc}", status_code=422, code="EXTRACT_FAILED") from exc

    # Step 2+3: retrieve_evidence + verify_claims（逐条）
    evidence_map: dict[str, list[dict]] = {}
    verification_results: list[dict] = []
    try:
        for claim in claims:
            cid = claim.get("claim_id") or claim.get("claim_uid") or "?"
            evidence = tools.retrieve_evidence(session, claim, top_k=8)
            evidence_map[cid] = evidence
            verification_results.append(tools.verify_claim(session, claim))
        step("retrieve_evidence", "Retrieved evidence for claims")
        step("verify_claims", f"Completed verification of {len(verification_results)} claims")
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"证据检索/核验失败: {exc}", status_code=422, code="VERIFY_FAILED") from exc

    # Step 4: generate_report
    report = build_report(document_id, claims, evidence_map, verification_results)
    step("generate_report", "Generated audit report")

    # 持久化 audit_reports
    from app.models.audit import AuditReport

    row = AuditReport(
        document_id=document_id,
        total_claims=report["summary"]["total_claims"],
        supported_count=report["summary"]["supported_count"],
        refuted_count=report["summary"]["refuted_count"],
        partially_supported_count=report["summary"]["partially_supported_count"],
        insufficient_count=report["summary"]["insufficient_count"],
        unknown_count=report["summary"]["unknown_count"],
        risk_summary=json.dumps(report["findings"], ensure_ascii=False),
        report_json=json.dumps(report, ensure_ascii=False),
        plan_json=json.dumps(plan.to_dict(), ensure_ascii=False),
    )
    session.add(row)
    session.commit()

    return {"audit_id": row.id, "plan": plan.to_dict(), "report": report}
