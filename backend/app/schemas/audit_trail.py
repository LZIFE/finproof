"""Audit Trail Schemas（Phase 12）。

企业治理审计日志：记录关键操作的执行人与上下文，用于合规审计与回溯。

数据结构：
- AuditTrailLog   审计日志条目（user/action/timestamp/model_version/
                                   rule_version/evidence_used/detail）
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuditTrailLog:
    """审计日志条目。"""

    log_id: str  # LOG-XXXX
    user: str = "system"
    action: str = ""
    target_type: str | None = None
    target_id: int | None = None
    timestamp: str = ""
    model_version: str = ""
    rule_version: str = ""
    evidence_used: list[dict] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "log_id": self.log_id,
            "user": self.user,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "timestamp": self.timestamp,
            "model_version": self.model_version,
            "rule_version": self.rule_version,
            "evidence_used": self.evidence_used,
            "detail": self.detail,
        }


__all__ = ["AuditTrailLog"]
