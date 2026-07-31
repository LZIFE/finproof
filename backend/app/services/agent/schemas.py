"""Agent Schemas（Phase 5）：审计计划与审计报告结构。"""

from dataclasses import dataclass, field


@dataclass
class AuditStep:
    name: str
    status: str = "pending"  # pending | running | done | failed
    detail: str = ""


@dataclass
class AuditPlan:
    document_id: int
    steps: list[str] = field(
        default_factory=lambda: ["extract_claims", "retrieve_evidence", "verify_claims", "generate_report"]
    )
    log: list[AuditStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "steps": self.steps,
            "log": [{"name": s.name, "status": s.status, "detail": s.detail} for s in self.log],
        }
