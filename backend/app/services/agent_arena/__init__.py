"""FinProof Financial AI Agent Arena Package（Phase 19）。

多 Agent 金融研究竞技系统：Analyst / Skeptic / Auditor / Judge 对同一任务分析、质疑、审计。
通过对抗提高金融 AI 可靠性。保持 Evidence First。

约束：不修改 Verification 核心逻辑；所有结论来自 Evidence；不输出投资建议。
"""

from app.services.agent_arena.analyst_agent import generate_viewpoints
from app.services.agent_arena.arena import get_arena, list_arena, run_arena
from app.services.agent_arena.auditor_agent import audit_debate
from app.services.agent_arena.judge import decide_winner, score_arena
from app.services.agent_arena.skeptic_agent import challenge_viewpoints
from app.services.agent_arena.schemas import (
    AGENT_ROLES,
    ArenaMessage,
    ArenaResult,
    ArenaRun,
    ArenaScore,
    AuditorReport,
    AnalystViewpoint,
    SkepticChallenge,
    EvidenceRef,
    AuditorIssue,
    ScoreBreakdown,
    PHASE_ORDER,
    CHALLENGE_TYPES,
    CHALLENGE_LABELS,
    ROLE_LABELS,
    contains_forbidden_content,
)

__all__ = [
    # schemas
    "AGENT_ROLES", "ArenaMessage", "ArenaResult", "ArenaRun", "ArenaScore",
    "AuditorReport", "AnalystViewpoint", "SkepticChallenge", "EvidenceRef",
    "AuditorIssue", "ScoreBreakdown", "PHASE_ORDER", "CHALLENGE_TYPES",
    "CHALLENGE_LABELS", "ROLE_LABELS", "contains_forbidden_content",
    # agents
    "generate_viewpoints", "challenge_viewpoints", "audit_debate",
    "score_arena", "decide_winner",
    # orchestrator
    "run_arena", "get_arena", "list_arena",
]
