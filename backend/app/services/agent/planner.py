"""Agent Planner（Phase 5）：生成固定审计流程（不使用 LLM 自由规划）。"""

from app.services.agent.schemas import AuditPlan


def build_audit_plan(document_id: int) -> AuditPlan:
    """生成固定审计流程：extract_claims → retrieve_evidence → verify_claims → generate_report。"""
    return AuditPlan(document_id=document_id)
