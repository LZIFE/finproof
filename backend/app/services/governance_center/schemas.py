"""FinProof Executive AI Governance Center Schemas（Phase 20）。

整合 Phase 0-19 能力，面向投资机构/企业管理层的 AI Governance Dashboard。
保持 Evidence First。禁止投资建议 / 交易 / �票推荐。

**不做新业务**：本模块为整合展示层，仅调用已有模块入口、聚合既有 ORM 行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 1. AI Reliability Score（来源：Benchmark / Red Team / Arena）
# ---------------------------------------------------------------------------
@dataclass
class ReliabilityScore:
    """AI 可靠性综合评分 0-100。"""

    overall_reliability: float = 0.0          # 综合
    hallucination_detection_rate: float = 0.0  # 幻觉检出率 0-1
    evidence_coverage: float = 0.0           # 证据覆盖率 0-1
    reasoning_accuracy: float = 0.0          # 逻辑准确率 0-1
    risk_detection_rate: float = 0.0         # 风险检出率 0-1
    benchmark_accuracy: float = 0.0
    red_team_reliability: float = 0.0
    arena_score: float = 0.0
    samples: int = 0

    def to_dict(self) -> dict:
        return {
            "overall_reliability": round(self.overall_reliability, 2),
            "hallucination_detection_rate": round(self.hallucination_detection_rate, 3),
            "evidence_coverage": round(self.evidence_coverage, 3),
            "reasoning_accuracy": round(self.reasoning_accuracy, 3),
            "risk_detection_rate": round(self.risk_detection_rate, 3),
            "benchmark_accuracy": round(self.benchmark_accuracy, 3),
            "red_team_reliability": round(self.red_team_reliability, 2),
            "arena_score": round(self.arena_score, 2),
            "samples": self.samples,
        }


# ---------------------------------------------------------------------------
# 2. Investment Intelligence Overview（来源：Research Agent / Memo / Committee）
# ---------------------------------------------------------------------------
@dataclass
class IntelligenceOverview:
    """投资情报概览：公司数 / 验证主张 / 风险发现 / 证据链。"""

    companies_analyzed: int = 0
    claims_verified: int = 0
    risk_findings: int = 0
    evidence_chains: int = 0
    research_sessions: int = 0
    committee_runs: int = 0
    memos_generated: int = 0
    top_companies: list[dict] = field(default_factory=list)  # [{company, sessions, findings}]

    def to_dict(self) -> dict:
        return {
            "companies_analyzed": self.companies_analyzed,
            "claims_verified": self.claims_verified,
            "risk_findings": self.risk_findings,
            "evidence_chains": self.evidence_chains,
            "research_sessions": self.research_sessions,
            "committee_runs": self.committee_runs,
            "memos_generated": self.memos_generated,
            "top_companies": self.top_companies,
        }


# ---------------------------------------------------------------------------
# 3. AI Risk Monitoring（来源：Risk Engine / Monitoring / Governance）
# ---------------------------------------------------------------------------
@dataclass
class RiskItem:
    """风险条目。"""

    risk_id: str = ""
    company: str = ""
    risk_type: str = ""
    level: str = ""  # LOW / MEDIUM / HIGH
    description: str = ""
    status: str = ""  # OPEN / RESOLVED / REVIEW
    evidence_count: int = 0
    detected_at: str = ""

    def to_dict(self) -> dict:
        return {
            "risk_id": self.risk_id,
            "company": self.company,
            "risk_type": self.risk_type,
            "level": self.level,
            "description": self.description[:200],
            "status": self.status,
            "evidence_count": self.evidence_count,
            "detected_at": self.detected_at,
        }


@dataclass
class RiskMonitoring:
    """风险监控：当前风险 / 历史变化 / 未决评审。"""

    current_risks: list[RiskItem] = field(default_factory=list)
    unresolved_reviews: int = 0
    monitoring_alerts: int = 0
    historical_change: dict[str, int] = field(default_factory=dict)  # {date: count}
    total_risks: int = 0

    def to_dict(self) -> dict:
        return {
            "current_risks": [r.to_dict() for r in self.current_risks],
            "unresolved_reviews": self.unresolved_reviews,
            "monitoring_alerts": self.monitoring_alerts,
            "historical_change": self.historical_change,
            "total_risks": self.total_risks,
        }


# ---------------------------------------------------------------------------
# 4. Agent Performance（来源：Arena / Simulation）
# ---------------------------------------------------------------------------
@dataclass
class AgentPerformance:
    """Agent 性能：Analyst / Skeptic / Auditor / Agent score。"""

    analyst_performance: float = 0.0     # Analyst 质量均分
    skeptic_detection_rate: float = 0.0  # Skeptic 发现率 0-1
    auditor_accuracy: float = 0.0        # Auditor 准确率 0-1
    agent_score: float = 0.0             # 综合 Agent score 0-100
    arena_runs: int = 0
    simulation_runs: int = 0
    fin_agent_score_mean: float = 0.0
    winner_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "analyst_performance": round(self.analyst_performance, 2),
            "skeptic_detection_rate": round(self.skeptic_detection_rate, 3),
            "auditor_accuracy": round(self.auditor_accuracy, 3),
            "agent_score": round(self.agent_score, 2),
            "arena_runs": self.arena_runs,
            "simulation_runs": self.simulation_runs,
            "fin_agent_score_mean": round(self.fin_agent_score_mean, 2),
            "winner_distribution": self.winner_distribution,
        }


# ---------------------------------------------------------------------------
# 5. Evidence Graph（来源：Knowledge Graph）
# ---------------------------------------------------------------------------
@dataclass
class EvidenceNode:
    """证据图谱节点：Company / Business / Metric / Evidence。"""

    node_id: str = ""
    entity_type: str = ""  # company / business / metric / evidence
    label: str = ""
    weight: int = 0

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "entity_type": self.entity_type,
            "label": self.label,
            "weight": self.weight,
        }


@dataclass
class EvidenceEdge:
    """证据图谱边：来源 → 目标。"""

    source: str = ""
    target: str = ""
    relation: str = ""

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "relation": self.relation}


@dataclass
class EvidenceGraph:
    """证据图谱：节点 + 边。"""

    nodes: list[EvidenceNode] = field(default_factory=list)
    edges: list[EvidenceEdge] = field(default_factory=list)
    companies: int = 0
    metrics: int = 0
    evidence_count: int = 0

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "companies": self.companies,
            "metrics": self.metrics,
            "evidence_count": self.evidence_count,
        }


# ---------------------------------------------------------------------------
# 6. Audit Timeline（来源：Audit Trail）
# ---------------------------------------------------------------------------
@dataclass
class AuditEvent:
    """审计事件：user / action / timestamp / model_version / evidence_used。"""

    event_id: str = ""
    user: str = ""
    action: str = ""
    timestamp: str = ""
    model_version: str = ""
    rule_version: str = ""
    evidence_used: int = 0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "user": self.user,
            "action": self.action,
            "timestamp": self.timestamp,
            "model_version": self.model_version,
            "rule_version": self.rule_version,
            "evidence_used": self.evidence_used,
            "detail": self.detail[:200],
        }


@dataclass
class AuditTimeline:
    """审计时间线。"""

    events: list[AuditEvent] = field(default_factory=list)
    total_events: int = 0
    distinct_users: int = 0
    distinct_actions: int = 0

    def to_dict(self) -> dict:
        return {
            "events": [e.to_dict() for e in self.events],
            "total_events": self.total_events,
            "distinct_users": self.distinct_users,
            "distinct_actions": self.distinct_actions,
        }


# ---------------------------------------------------------------------------
# 7. Governance Dashboard（顶层整合）
# ---------------------------------------------------------------------------
@dataclass
class GovernanceDashboard:
    """FinProof AI Governance Dashboard 顶层聚合。"""

    reliability: ReliabilityScore = field(default_factory=ReliabilityScore)
    intelligence: IntelligenceOverview = field(default_factory=IntelligenceOverview)
    risk_monitoring: RiskMonitoring = field(default_factory=RiskMonitoring)
    agent_performance: AgentPerformance = field(default_factory=AgentPerformance)
    evidence_graph: EvidenceGraph = field(default_factory=EvidenceGraph)
    audit_timeline: AuditTimeline = field(default_factory=AuditTimeline)
    generated_at: str = ""
    governance_id: str = ""

    def to_dict(self) -> dict:
        return {
            "governance_id": self.governance_id,
            "generated_at": self.generated_at,
            "reliability": self.reliability.to_dict(),
            "intelligence": self.intelligence.to_dict(),
            "risk_monitoring": self.risk_monitoring.to_dict(),
            "agent_performance": self.agent_performance.to_dict(),
            "evidence_graph": self.evidence_graph.to_dict(),
            "audit_timeline": self.audit_timeline.to_dict(),
        }


# ---------------------------------------------------------------------------
# 8. Final Governance Report（Demo 输出）
# ---------------------------------------------------------------------------
@dataclass
class PipelineStage:
    """治理流水线阶段记录。"""

    stage: str = ""
    status: str = ""  # OK / SKIPPED / ERROR
    summary: str = ""
    artifacts: dict = field(default_factory=dict)
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "summary": self.summary,
            "artifacts": self.artifacts,
            "duration_ms": self.duration_ms,
        }


@dataclass
class FinalGovernanceReport:
    """最终治理报告：用户输入 → 全流水线 → 5 项输出。"""

    report_id: str = ""
    company: str = ""
    research_question: str = ""
    pipeline: list[PipelineStage] = field(default_factory=list)
    reliability_score: float = 0.0          # ① 可信度评分
    risk_list: list[RiskItem] = field(default_factory=list)  # ② 风险列表
    evidence_chain: list[dict] = field(default_factory=list)  # ③ 证据链
    agent_audit_process: list[dict] = field(default_factory=list)  # ④ Agent 审计过程
    final_reliability_score: float = 0.0    # ⑤ Reliability Score
    conclusion: str = ""  # 仅基于证据的可靠性结论，非投资建议
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "company": self.company,
            "research_question": self.research_question,
            "pipeline": [p.to_dict() for p in self.pipeline],
            "reliability_score": round(self.reliability_score, 2),
            "risk_list": [r.to_dict() for r in self.risk_list],
            "evidence_chain": self.evidence_chain,
            "agent_audit_process": self.agent_audit_process,
            "final_reliability_score": round(self.final_reliability_score, 2),
            "conclusion": self.conclusion,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def risk_level_of(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"


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
    "ReliabilityScore", "IntelligenceOverview", "RiskItem", "RiskMonitoring",
    "AgentPerformance", "EvidenceNode", "EvidenceEdge", "EvidenceGraph",
    "AuditEvent", "AuditTimeline", "GovernanceDashboard",
    "PipelineStage", "FinalGovernanceReport",
    "_now_iso", "risk_level_of", "contains_forbidden_content",
]
