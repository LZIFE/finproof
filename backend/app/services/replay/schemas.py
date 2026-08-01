"""FinProof AI Audit Replay Timeline Schemas（Phase 21）。

将已有 FinProof 审计流程转化为可视化审计回放。**不新增分析能力**，仅展示既有
Evidence / Verification / Risk / Agent Trace。

5 类事件（任务书 §记录）：
    claim_event        AI 主张
    evidence_event     证据检索
    verification_event 事实验证
    risk_event         风险评估
    agent_event        Agent 讨论

数据库：audit_replay_events（任务书 §数据库）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 事件类型（任务书 §记录）
# ---------------------------------------------------------------------------
EVENT_CLAIM = "claim_event"                # AI Claim
EVENT_EVIDENCE = "evidence_event"          # Evidence Found
EVENT_VERIFICATION = "verification_event"  # Verification
EVENT_RISK = "risk_event"                  # Risk Assessment
EVENT_AGENT = "agent_event"                # Agent Discussion
EVENT_CONCLUSION = "conclusion_event"      # Final Conclusion（前端第 6 步）

EVENT_TYPES = {
    EVENT_CLAIM,
    EVENT_EVIDENCE,
    EVENT_VERIFICATION,
    EVENT_RISK,
    EVENT_AGENT,
    EVENT_CONCLUSION,
}

# 回放时间线顺序（任务书 §前端 Timeline）
TIMELINE_ORDER = [
    EVENT_CLAIM,        # ① AI Claim
    EVENT_EVIDENCE,     # ② Evidence Found
    EVENT_VERIFICATION, # ③ Verification
    EVENT_RISK,         # ④ Risk Assessment
    EVENT_AGENT,        # ⑤ Agent Discussion
    EVENT_CONCLUSION,   # ⑥ Final Conclusion
]

EVENT_LABELS = {
    EVENT_CLAIM: "AI 主张",
    EVENT_EVIDENCE: "证据检索",
    EVENT_VERIFICATION: "事实验证",
    EVENT_RISK: "风险评估",
    EVENT_AGENT: "Agent 讨论",
    EVENT_CONCLUSION: "最终结论",
}

EVENT_ICONS = {
    EVENT_CLAIM: "💬",
    EVENT_EVIDENCE: "📄",
    EVENT_VERIFICATION: "🔍",
    EVENT_RISK: "⚠️",
    EVENT_AGENT: "🤖",
    EVENT_CONCLUSION: "🏁",
}


# ---------------------------------------------------------------------------
# ReplayEvent：回放事件（任务书 §数据库字段）
# ---------------------------------------------------------------------------
@dataclass
class ReplayEvent:
    """单个回放事件。

    每一步必须显示：来源 / 证据 / 结果（任务书 §前端）。
    """

    id: int | None = None
    audit_id: str = ""
    event_type: str = ""  # EVENT_TYPES
    timestamp: str = ""
    actor: str = ""  # 来源（AI / Evidence Retrieval / Verification / Risk Engine / Analyst / Skeptic / Auditor / Judge）
    content: str = ""  # 结果
    evidence_reference: str = ""  # 证据引用（JSON 字符串或纯文本）
    source: str = ""  # 来源模块（research / verification / risk / arena / committee）
    evidence_summary: str = ""  # 证据摘要
    result_summary: str = ""  # 结果摘要

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "audit_id": self.audit_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "content": self.content,
            "evidence_reference": self.evidence_reference,
            "source": self.source,
            "evidence_summary": self.evidence_summary,
            "result_summary": self.result_summary,
        }


# ---------------------------------------------------------------------------
# ReplayTimeline：回放时间线
# ---------------------------------------------------------------------------
@dataclass
class ReplayTimeline:
    """审计回放时间线：按 6 步顺序排列的事件。"""

    audit_id: str = ""
    events: list[ReplayEvent] = field(default_factory=list)
    total_events: int = 0
    steps: dict[str, list[ReplayEvent]] = field(default_factory=dict)  # {event_type: events}
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "total_events": self.total_events,
            "created_at": self.created_at,
            "events": [e.to_dict() for e in self.events],
            "steps": {
                et: [e.to_dict() for e in self.steps.get(et, [])]
                for et in TIMELINE_ORDER
            },
            "step_order": TIMELINE_ORDER,
            "step_labels": EVENT_LABELS,
            "step_icons": EVENT_ICONS,
        }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# 禁止词护栏（不输出投资建议）
_FORBIDDEN_KW = (
    "买入", "卖出", "目标价", "建议加仓", "建议减仓", "估值预测",
    "buy", "sell", "target price", "recommendation",
    "推荐股票", "推荐买入", "推荐卖出",
)


def contains_forbidden_content(text: str) -> bool:
    """是否含禁止词（投资建议/股票推荐/估值预测）。

    剥离否定式免责片段后判定，不误伤"不构成...建议/推荐"声明。
    """
    if not text:
        return False
    import re as _re
    stripped = _re.sub(
        r"(不构成|不包含|不含|不输出|不涉及|非|并无|未含|不提供)[^;。；\.]{0,40}",
        "",
        text,
    )
    lowered = stripped.lower()
    strong = ("买入", "卖出", "目标价", "建议加仓", "建议减仓", "估值预测", "buy", "sell", "target price")
    for kw in strong:
        if kw.lower() in lowered:
            return True
    if "推荐买入" in stripped or "推荐卖出" in stripped or "推荐加仓" in stripped or "推荐减仓" in stripped:
        return True
    return False


__all__ = [
    # 事件类型
    "EVENT_CLAIM", "EVENT_EVIDENCE", "EVENT_VERIFICATION",
    "EVENT_RISK", "EVENT_AGENT", "EVENT_CONCLUSION",
    "EVENT_TYPES", "TIMELINE_ORDER", "EVENT_LABELS", "EVENT_ICONS",
    # 数据类
    "ReplayEvent", "ReplayTimeline",
    # 工具
    "_now_iso", "contains_forbidden_content",
]
