"""FinProof Financial AI Agent Arena Schemas（Phase 19）。

多 Agent 金融研究竞技系统：Analyst / Skeptic / Auditor / Judge 对同一任务分析、质疑、审计。
通过对抗提高金融 AI 可靠性。保持 Evidence First。

**禁止**：投资建议 / 股票推荐 / 交易 / 修改 Verification 核心逻辑。
所有结论必须来自 Evidence。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Agent 角色（任务书 §Agent Roles）
# ---------------------------------------------------------------------------
ROLE_ANALYST = "Analyst"      # 分析师：分析公司业务、提取财务事实、建立研究观点
ROLE_SKEPTIC = "Skeptic"       # 质疑者：挑战 Analyst，寻找漏洞
ROLE_AUDITOR = "Auditor"      # 审计师：最终审计，检查覆盖率/一致性/完整性
ROLE_JUDGE = "Judge"          # 评判：综合评分

AGENT_ROLES = {ROLE_ANALYST, ROLE_SKEPTIC, ROLE_AUDITOR, ROLE_JUDGE}

ROLE_LABELS = {
    ROLE_ANALYST: "分析师 Agent",
    ROLE_SKEPTIC: "质疑者 Agent",
    ROLE_AUDITOR: "审计师 Agent",
    ROLE_JUDGE: "评判",
}


# ---------------------------------------------------------------------------
# Arena 阶段（任务书 §Workflow）
# ---------------------------------------------------------------------------
PHASE_ANALYST = "Analyst Generates"
PHASE_SKEPTIC_ATTACKS = "Skeptic Attacks"
PHASE_AUDITOR_VERIFIES = "Auditor Verifies"
PHASE_JUDGE_SCORES = "Judge Scores"
PHARE_DONE = "Done"

PHASE_ORDER = [
    PHASE_ANALYST,
    PHASE_SKEPTIC_ATTACKS,
    PHASE_AUDITOR_VERIFIES,
    PHASE_JUDGE_SCORES,
    PHARE_DONE,
]


# ---------------------------------------------------------------------------
# Skeptic 挑战类型（任务书 §2 Skeptic Agent）
# ---------------------------------------------------------------------------
CHALLENGE_UNSUPPORTED_CLAIM = "Unsupported Claim"        # 无依据主张
CHALLENGE_OVERSTATEMENT = "Overstatement"               # 夸大
CHALLENGE_MISSING_EVIDENCE = "Missing Evidence"          # 缺证据
CHALLENGE_CONTRADICTORY_FACTS = "Contradictory Facts"    # 事实冲突
CHALLENGE_GROWTH_QUALITY = "Growth Quality Problem"      # 增长质量

CHALLENGE_TYPES = {
    CHALLENGE_UNSUPPORTED_CLAIM,
    CHALLENGE_OVERSTATEMENT,
    CHALLENGE_MISSING_EVIDENCE,
    CHALLENGE_CONTRADICTORY_FACTS,
    CHALLENGE_GROWTH_QUALITY,
}

CHALLENGE_LABELS = {
    CHALLENGE_UNSUPPORTED_CLAIM: "无依据主张",
    CHALLENGE_OVERSTATEMENT: "夸大",
    CHALLENGE_MISSING_EVIDENCE: "缺证据",
    CHALLENGE_CONTRADICTORY_FACTS: "事实冲突",
    CHALLENGE_GROWTH_QUALITY: "增长质量",
}


# ---------------------------------------------------------------------------
# EvidenceRef：证据引用（每结论必须绑定）
# ---------------------------------------------------------------------------
@dataclass
class EvidenceRef:
    """证据引用：所有结论必须绑定至少一条 Evidence。"""

    block_id: str | int = ""
    document_id: str | int = ""
    page_number: str | int = ""
    text: str = ""
    final_score: float = 0.0
    evidence_type: str = ""
    evidence_tier: str = ""

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "document_id": self.document_id,
            "page_number": self.page_number,
            "text": self.text[:200],
            "final_score": round(self.final_score, 3) if isinstance(self.final_score, (int, float)) else self.final_score,
            "evidence_type": self.evidence_type,
            "evidence_tier": self.evidence_tier,
        }


# ---------------------------------------------------------------------------
# AnalystViewpoint：分析师观点（任务书 §1 Analyst Agent）
# ---------------------------------------------------------------------------
@dataclass
class AnalystViewpoint:
    """分析师观点：claim / evidence / confidence。"""

    viewpoint_id: str = ""  # AV-001
    claim: str = ""  # 观点（仅事实，不含投资建议）
    evidence: list[EvidenceRef] = field(default_factory=list)  # 必须绑定 Evidence
    confidence: float = 0.0  # 0-1
    metric: str = ""  # revenue / profit / margin / cash_flow / segments / competitive
    unsupported: bool = False  # 无证据 → True（将被 Skeptic 抓出）

    def to_dict(self) -> dict:
        return {
            "viewpoint_id": self.viewpoint_id,
            "claim": self.claim,
            "evidence": [e.to_dict() for e in self.evidence],
            "confidence": round(self.confidence, 3),
            "metric": self.metric,
            "unsupported": self.unsupported,
        }


# ---------------------------------------------------------------------------
# SkepticChallenge：质疑者挑战（任务书 §2 Skeptic Agent）
# ---------------------------------------------------------------------------
@dataclass
class SkepticChallenge:
    """质疑者挑战：counter_claim / missing_evidence / risk。"""

    challenge_id: str = ""  # SC-001
    target_viewpoint_id: str = ""  # 针对 AnalystViewpoint
    challenge_type: str = ""  # CHALLENGE_TYPES
    counter_claim: str = ""  # 反驳主张（基于 Evidence）
    missing_evidence: str = ""  # 缺失证据描述
    risk: str = ""  # 风险描述
    evidence: list[EvidenceRef] = field(default_factory=list)  # 反驳证据
    risk_score: float = 0.0
    valid: bool = True  # Auditor 后续判定是否成立

    def to_dict(self) -> dict:
        return {
            "challenge_id": self.challenge_id,
            "target_viewpoint_id": self.target_viewpoint_id,
            "challenge_type": self.challenge_type,
            "counter_claim": self.counter_claim,
            "missing_evidence": self.missing_evidence,
            "risk": self.risk,
            "evidence": [e.to_dict() for e in self.evidence],
            "risk_score": round(self.risk_score, 3),
            "valid": self.valid,
        }


# ---------------------------------------------------------------------------
# AuditorIssue：审计师发现（任务书 §3 Auditor Agent）
# ---------------------------------------------------------------------------
@dataclass
class AuditorIssue:
    """审计师发现：issue_type / description / affected。"""

    issue_id: str = ""  # AI-001
    issue_type: str = ""  # evidence_coverage / logical_consistency / risk_completeness
    description: str = ""
    affected: str = ""  # analyst / skeptic / both

    def to_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "issue_type": self.issue_type,
            "description": self.description,
            "affected": self.affected,
        }


@dataclass
class AuditorReport:
    """审计师报告：audit_score + issues。"""

    audit_score: float = 0.0  # 0-100
    issues: list[AuditorIssue] = field(default_factory=list)
    evidence_coverage: float = 0.0  # 0-1
    logical_consistency: float = 0.0
    risk_completeness: float = 0.0
    valid_challenges: list[str] = field(default_factory=list)  # 成立的 SkepticChallenge ID
    invalid_challenges: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "audit_score": round(self.audit_score, 2),
            "issues": [i.to_dict() for i in self.issues],
            "evidence_coverage": round(self.evidence_coverage, 3),
            "logical_consistency": round(self.logical_consistency, 3),
            "risk_completeness": round(self.risk_completeness, 3),
            "valid_challenges": self.valid_challenges,
            "invalid_challenges": self.invalid_challenges,
        }


# ---------------------------------------------------------------------------
# ArenaScore：评判评分（任务书 §4 Judge）
# ---------------------------------------------------------------------------
@dataclass
class ScoreBreakdown:
    """单项评分 0-100 + notes。"""

    score: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {"score": round(self.score, 2), "notes": self.notes}


@dataclass
class ArenaScore:
    """评判综合评分：5 项子分 + Final Arena Score。

    权重（任务书 §4）：Evidence 30% / Reasoning 25% / Risk Detection 25% /
    Efficiency 10% / Safety 10%。
    """

    analyst_quality: ScoreBreakdown = field(default_factory=ScoreBreakdown)    # Analyst 质量
    skeptic_detection: ScoreBreakdown = field(default_factory=ScoreBreakdown)  # Skeptic 发现能力
    auditor_reliability: ScoreBreakdown = field(default_factory=ScoreBreakdown)  # Auditor 可靠性
    evidence_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)    # Evidence 30%
    reasoning_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)   # Reasoning 25%
    risk_detection_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)  # Risk 25%
    efficiency_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)  # Efficiency 10%
    safety_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)      # Safety 10%
    final_arena_score: float = 0.0  # 加权 0-100

    def to_dict(self) -> dict:
        return {
            "analyst_quality": self.analyst_quality.to_dict(),
            "skeptic_detection": self.skeptic_detection.to_dict(),
            "auditor_reliability": self.auditor_reliability.to_dict(),
            "evidence_score": self.evidence_score.to_dict(),
            "reasoning_score": self.reasoning_score.to_dict(),
            "risk_detection_score": self.risk_detection_score.to_dict(),
            "efficiency_score": self.efficiency_score.to_dict(),
            "safety_score": self.safety_score.to_dict(),
            "final_arena_score": round(self.final_arena_score, 2),
        }


# ---------------------------------------------------------------------------
# ArenaMessage：辩论消息（任务书 §数据库 arena_messages）
# ---------------------------------------------------------------------------
@dataclass
class ArenaMessage:
    """辩论消息：role / phase / content / evidence / timestamp。"""

    message_id: str = ""  # MSG-001
    role: str = ""  # AGENT_ROLES
    phase: str = ""  # PHASE_ORDER
    content: str = ""  # 消息文本
    viewpoints: list[AnalystViewpoint] = field(default_factory=list)  # Analyst 观点
    challenges: list[SkepticChallenge] = field(default_factory=list)  # Skeptic 挑战
    audit: AuditorReport | None = None  # Auditor 报告
    evidence: list[EvidenceRef] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "phase": self.phase,
            "content": self.content,
            "viewpoints": [v.to_dict() for v in self.viewpoints],
            "challenges": [c.to_dict() for c in self.challenges],
            "audit": self.audit.to_dict() if self.audit else None,
            "evidence": [e.to_dict() for e in self.evidence],
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# ArenaRun + ArenaResult（任务书 §Workflow §数据库）
# ---------------------------------------------------------------------------
@dataclass
class ArenaResult:
    """竞技结果：双方观点/挑战/审计 + 评分。"""

    result_id: str = ""  # AR-XXXX
    run_id: str = ""
    analyst_viewpoints: list[AnalystViewpoint] = field(default_factory=list)
    skeptic_challenges: list[SkepticChallenge] = field(default_factory=list)
    auditor_report: AuditorReport | None = None
    score: ArenaScore = field(default_factory=ArenaScore)
    winner: str = ""  # analyst / skeptic / tie（仅指辩论胜负，非投资建议）
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "run_id": self.run_id,
            "analyst_viewpoints": [v.to_dict() for v in self.analyst_viewpoints],
            "skeptic_challenges": [c.to_dict() for c in self.skeptic_challenges],
            "auditor_report": self.auditor_report.to_dict() if self.auditor_report else None,
            "score": self.score.to_dict(),
            "winner": self.winner,
            "created_at": self.created_at,
        }


@dataclass
class ArenaRun:
    """竞技运行：company + research_question + messages + result。"""

    run_id: str = ""  # ARENA-XXXX
    company: str = ""
    research_question: str = ""
    phase: str = PHASE_ANALYST
    messages: list[ArenaMessage] = field(default_factory=list)
    result: ArenaResult | None = None
    created_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "company": self.company,
            "research_question": self.research_question,
            "phase": self.phase,
            "messages": [m.to_dict() for m in self.messages],
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# 禁止词护栏（不输出投资建议）
FORBIDDEN_KW = (
    "买入", "卖出", "目标价", "建议加仓", "建议减仓", "估值预测",
    "buy", "sell", "target price", "recommendation",
    "推荐股票", "推荐买入", "推荐卖出",
)


def _is_forbidden_text(text: str) -> bool:
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


def contains_forbidden_content(text: str) -> bool:
    """检查文本是否含禁止词。"""
    return _is_forbidden_text(text)


def risk_level_of(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"


__all__ = [
    # 角色
    "ROLE_ANALYST", "ROLE_SKEPTIC", "ROLE_AUDITOR", "ROLE_JUDGE",
    "AGENT_ROLES", "ROLE_LABELS",
    # 阶段
    "PHASE_ANALYST", "PHASE_SKEPTIC_ATTACKS", "PHASE_AUDITOR_VERIFIES",
    "PHASE_JUDGE_SCORES", "PHARE_DONE", "PHASE_ORDER",
    # 挑战类型
    "CHALLENGE_UNSUPPORTED_CLAIM", "CHALLENGE_OVERSTATEMENT",
    "CHALLENGE_MISSING_EVIDENCE", "CHALLENGE_CONTRADICTORY_FACTS",
    "CHALLENGE_GROWTH_QUALITY",
    "CHALLENGE_TYPES", "CHALLENGE_LABELS",
    # 数据类
    "EvidenceRef", "AnalystViewpoint", "SkepticChallenge",
    "AuditorIssue", "AuditorReport", "ScoreBreakdown", "ArenaScore",
    "ArenaMessage", "ArenaResult", "ArenaRun",
    # 工具
    "_now_iso", "FORBIDDEN_KW", "contains_forbidden_content", "risk_level_of",
]
