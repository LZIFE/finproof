"""FinProof Autonomous Financial Research Agent Schemas（Phase 17）。

从企业名称/股票代码出发的自主金融研究流程，输出 Evidence First Research Memo。

输出仅含：事实、证据、风险、待验证事项。
**禁止**：投资建议 / 股票推荐 / 估值预测 / 自动交易。

约束：不修改 Verification 核心逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 研究阶段（任务书 §7 前端进度展示）
# ---------------------------------------------------------------------------
PHASE_PLANNING = "Planning"
PHASE_COLLECTING = "Collecting Evidence"
PHASE_ANALYZING = "Analyzing"
PHASE_RISK_CHECKING = "Risk Checking"
PHASE_MEMO_GENERATED = "Memo Generated"

PHASE_ORDER = [
    PHASE_PLANNING,
    PHASE_COLLECTING,
    PHASE_ANALYZING,
    PHASE_RISK_CHECKING,
    PHASE_MEMO_GENERATED,
]


# ---------------------------------------------------------------------------
# 研究任务类型（任务书 §2 §3）
# ---------------------------------------------------------------------------
TASK_COMPANY_PROFILE = "Company Profile"
TASK_FINANCIAL_OVERVIEW = "Financial Overview"
TASK_BUSINESS_ANALYSIS = "Business Analysis"
TASK_RISK_DISCOVERY = "Risk Discovery"
TASK_COMPETITION_FACTS = "Competition Facts"

TASK_TYPES = {
    TASK_COMPANY_PROFILE,
    TASK_FINANCIAL_OVERVIEW,
    TASK_BUSINESS_ANALYSIS,
    TASK_RISK_DISCOVERY,
    TASK_COMPETITION_FACTS,
}

TASK_LABELS = {
    TASK_COMPANY_PROFILE: "企业画像",
    TASK_FINANCIAL_OVERVIEW: "财务摘要",
    TASK_BUSINESS_ANALYSIS: "业务分析",
    TASK_RISK_DISCOVERY: "风险发现",
    TASK_COMPETITION_FACTS: "竞争事实",
}


# ---------------------------------------------------------------------------
# 任务状态
# ---------------------------------------------------------------------------
TASK_PENDING = "PENDING"
TASK_RUNNING = "RUNNING"
TASK_DONE = "DONE"
TASK_SKIPPED = "SKIPPED"  # 无证据/工具失败时跳过，不凭空生成

TASK_STATUSES = {TASK_PENDING, TASK_RUNNING, TASK_DONE, TASK_SKIPPED}


# ---------------------------------------------------------------------------
# ResearchPlan（任务书 §2）
# ---------------------------------------------------------------------------
@dataclass
class ResearchTaskSpec:
    """研究任务规格：一个研究领域下的证据检索诉求。"""

    task_type: str  # TASK_TYPES
    category: str  # Financial / Business / Risk / Competition
    objective: str  # 研究目标（自然语言）
    claim_query: str  # 用于 evidence retrieval 的查询文本
    metric: str = ""  # revenue / profit / margin / cash_flow / segments / products / regions / competitor
    need_knowledge_graph: bool = False  # 业务分析需 KG
    need_reasoning: bool = False  # 风险发现需 Reasoning Engine
    need_monitoring: bool = False  # 风险发现需历史观点对比

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "category": self.category,
            "objective": self.objective,
            "claim_query": self.claim_query,
            "metric": self.metric,
            "need_knowledge_graph": self.need_knowledge_graph,
            "need_reasoning": self.need_reasoning,
            "need_monitoring": self.need_monitoring,
        }


@dataclass
class ResearchPlan:
    """研究计划：Financial / Business / Risk / Competition 四类任务集合。"""

    company: str
    stock_code: str = ""
    tasks: list[ResearchTaskSpec] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "stock_code": self.stock_code,
            "tasks": [t.to_dict() for t in self.tasks],
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# ResearchFinding：一个任务产出的证据绑定事实
# ---------------------------------------------------------------------------
@dataclass
class EvidenceRef:
    """证据引用：每条事实必须绑定至少一条 Evidence。"""

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


@dataclass
class ResearchFinding:
    """研究事实：content 必须绑定至少一条 evidence；无证据则标记 unsupported=False。"""

    task_type: str
    metric: str
    content: str  # 事实陈述（仅含事实，不含投资观点）
    evidence: list[EvidenceRef] = field(default_factory=list)
    supported: bool = True  # False 表示无证据支持 → Open Question
    risk_score: float = 0.0
    risk_level: str = "LOW"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "metric": self.metric,
            "content": self.content,
            "evidence": [e.to_dict() for e in self.evidence],
            "supported": self.supported,
            "risk_score": round(self.risk_score, 3),
            "risk_level": self.risk_level,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# ToolCall：研究过程中的工具调用记录（任务书 §4）
# ---------------------------------------------------------------------------
@dataclass
class ToolCall:
    """工具调用记录：tool / input / output / evidence / timestamp。"""

    tool: str  # evidence_retrieval / verification / risk_engine / knowledge_graph / reasoning / monitoring
    task_type: str = ""
    input_summary: str = ""
    output_summary: str = ""
    evidence_count: int = 0
    success: bool = True
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "task_type": self.task_type,
            "input_summary": self.input_summary[:200],
            "output_summary": self.output_summary[:200],
            "evidence_count": self.evidence_count,
            "success": self.success,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# RiskFinding：风险发现（financial / business / logic）
# ---------------------------------------------------------------------------
@dataclass
class RiskFinding:
    """风险发现：来源工具 + 类型 + 内容 + 证据 + 风险评分。"""

    risk_type: str  # financial / business / logic
    source_tool: str  # risk_engine / reasoning / monitoring
    content: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    risk_score: float = 0.0
    risk_level: str = "LOW"
    logical_gap: str = ""

    def to_dict(self) -> dict:
        return {
            "risk_type": self.risk_type,
            "source_tool": self.source_tool,
            "content": self.content,
            "evidence": [e.to_dict() for e in self.evidence],
            "risk_score": round(self.risk_score, 3),
            "risk_level": self.risk_level,
            "logical_gap": self.logical_gap,
        }


# ---------------------------------------------------------------------------
# ResearchMemo（任务书 §5）
# ---------------------------------------------------------------------------
@dataclass
class ResearchMemo:
    """Evidence First Research Memo。

    结构（任务书 §5）：
      1. Company Overview
      2. Key Facts
      3. Financial Facts
      4. Business Facts
      5. Risk Findings
      6. Evidence Chain
      7. Open Questions

    禁止：buy/sell、target price、recommendation。
    """

    company: str
    stock_code: str = ""
    company_overview: str = ""  # ① Company Overview
    key_facts: list[ResearchFinding] = field(default_factory=list)  # ② Key Facts
    financial_facts: list[ResearchFinding] = field(default_factory=list)  # ③ Financial Facts
    business_facts: list[ResearchFinding] = field(default_factory=list)  # ④ Business Facts
    risk_findings: list[RiskFinding] = field(default_factory=list)  # ⑤ Risk Findings
    evidence_chain: list[EvidenceRef] = field(default_factory=list)  # ⑥ Evidence Chain（去重汇总）
    open_questions: list[str] = field(default_factory=list)  # ⑦ Open Questions（无证据/待验证）
    evidence_coverage: float = 0.0  # 评测指标：有证据事实占比
    unsupported_claim_rate: float = 0.0  # 评测指标：无证据事实占比
    task_completion_rate: float = 0.0  # 评测指标：已完成任务占比
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "stock_code": self.stock_code,
            "company_overview": self.company_overview,
            "key_facts": [f.to_dict() for f in self.key_facts],
            "financial_facts": [f.to_dict() for f in self.financial_facts],
            "business_facts": [f.to_dict() for f in self.business_facts],
            "risk_findings": [r.to_dict() for r in self.risk_findings],
            "evidence_chain": [e.to_dict() for e in self.evidence_chain],
            "open_questions": self.open_questions,
            "evidence_coverage": round(self.evidence_coverage, 3),
            "unsupported_claim_rate": round(self.unsupported_claim_rate, 3),
            "task_completion_rate": round(self.task_completion_rate, 3),
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# ResearchSession（任务书 §4）
# ---------------------------------------------------------------------------
@dataclass
class ResearchSession:
    """研究会话：company + plan + tool_calls + evidence + results + memo。"""

    session_id: str = ""  # RESEARCH-XXXX
    company: str = ""
    stock_code: str = ""
    plan: ResearchPlan | None = None
    phase: str = PHASE_PLANNING
    tasks_status: dict[str, str] = field(default_factory=dict)  # task_type → TASK_STATUSES
    tool_calls: list[ToolCall] = field(default_factory=list)
    findings: list[ResearchFinding] = field(default_factory=list)
    risk_findings: list[RiskFinding] = field(default_factory=list)
    memo: ResearchMemo | None = None
    created_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "company": self.company,
            "stock_code": self.stock_code,
            "plan": self.plan.to_dict() if self.plan else None,
            "phase": self.phase,
            "tasks_status": self.tasks_status,
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "findings": [f.to_dict() for f in self.findings],
            "risk_findings": [r.to_dict() for r in self.risk_findings],
            "memo": self.memo.to_dict() if self.memo else None,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
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


# Memo 禁止词（任务书 §5）
# 注意：免责声明会写"不构成投资建议/股票推荐"，故护栏用 _is_forbidden_memo_text 做上下文判定，
# 仅在文本真正构成禁止词时触发，不误伤"不构成...建议/推荐"类否定式免责声明。
FORBIDDEN_MEMO_KW = (
    "buy", "sell", "target price", "recommendation",
    "买入", "卖出", "目标价", "建议加仓", "建议减仓", "估值预测",
)


def _is_forbidden_memo_text(text: str) -> bool:
    """是否真正构成禁止词（投资建议/股票推荐/估值预测）。

    免责声明会写"不构成投资建议/股票推荐/估值预测"，这是合法的，不应误判：
    - 先剥离所有否定式免责片段（"不构成/不包含/不含/非/不输出 ... 建议/推荐/估值预测"），
      再检查剩余文本是否含禁止词；
    - 仅当文本真正构成禁止词时触发。
    """
    if not text:
        return False
    lowered = text.lower()
    # 先剥离否定式免责片段：不构成/不包含/不含/不输出/非 + 后续最多 40 字（覆盖"投资建议/股票推荐/估值预测"等）
    import re as _re
    stripped = _re.sub(
        r"(不构成|不包含|不含|不输出|不涉及|非|并无|未含|不提供)[^;。；\.]{0,40}",
        "",
        text,
    )
    lowered = stripped.lower()
    # 强禁止词（无歧义）
    strong = ("买入", "卖出", "目标价", "建议加仓", "建议减仓", "估值预测", "buy", "sell", "target price")
    for kw in strong:
        if kw.lower() in lowered:
            return True
    # "推荐"仅在组合成"推荐买入/推荐卖出"时触发（单独"推荐"放行）
    if "推荐买入" in stripped or "推荐卖出" in stripped or "推荐加仓" in stripped or "推荐减仓" in stripped:
        return True
    return False


def contains_forbidden_memo_content(text: str) -> bool:
    """检查文本是否含 Memo 禁止词（投资建议/股票推荐/估值预测）。

    采用 _is_forbidden_memo_text 做上下文判定，避免误伤免责声明。
    """
    return _is_forbidden_memo_text(text)


__all__ = [
    # 阶段
    "PHASE_PLANNING",
    "PHASE_COLLECTING",
    "PHASE_ANALYZING",
    "PHASE_RISK_CHECKING",
    "PHASE_MEMO_GENERATED",
    "PHASE_ORDER",
    # 任务类型
    "TASK_COMPANY_PROFILE",
    "TASK_FINANCIAL_OVERVIEW",
    "TASK_BUSINESS_ANALYSIS",
    "TASK_RISK_DISCOVERY",
    "TASK_COMPETITION_FACTS",
    "TASK_TYPES",
    "TASK_LABELS",
    # 任务状态
    "TASK_PENDING",
    "TASK_RUNNING",
    "TASK_DONE",
    "TASK_SKIPPED",
    "TASK_STATUSES",
    # 数据类
    "ResearchTaskSpec",
    "ResearchPlan",
    "EvidenceRef",
    "ResearchFinding",
    "ToolCall",
    "RiskFinding",
    "ResearchMemo",
    "ResearchSession",
    # 工具
    "_now_iso",
    "risk_level_of",
    "FORBIDDEN_MEMO_KW",
    "contains_forbidden_memo_content",
]
