"""FinProof AI Audit Replay Timeline Package（Phase 21）。

将已有 FinProof 审计流程转化为可视化审计回放。**不新增分析能力**，仅展示既有
Evidence / Verification / Risk / Agent Trace。

5 类事件：claim_event / evidence_event / verification_event / risk_event / agent_event。
约束：不修改 Verification/Risk 核心；不增加投资建议；所有内容来自已有数据。
"""

from app.services.replay.collector import collect_events
from app.services.replay.schemas import (
    EVENT_AGENT,
    EVENT_CLAIM,
    EVENT_CONCLUSION,
    EVENT_EVIDENCE,
    EVENT_ICONS,
    EVENT_LABELS,
    EVENT_RISK,
    EVENT_TYPES,
    EVENT_VERIFICATION,
    ReplayEvent,
    ReplayTimeline,
    TIMELINE_ORDER,
    contains_forbidden_content,
)
from app.services.replay.service import build_replay, get_replay, list_replay

__all__ = [
    # schemas
    "EVENT_CLAIM", "EVENT_EVIDENCE", "EVENT_VERIFICATION", "EVENT_RISK",
    "EVENT_AGENT", "EVENT_CONCLUSION", "EVENT_TYPES", "TIMELINE_ORDER",
    "EVENT_LABELS", "EVENT_ICONS", "ReplayEvent", "ReplayTimeline",
    "contains_forbidden_content",
    # collector + service
    "collect_events", "build_replay", "get_replay", "list_replay",
]
