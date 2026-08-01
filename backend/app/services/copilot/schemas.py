"""FinProof Copilot Schemas（Phase 15）。

面向投资经理的交互式 AI 审计助手：自然语言查询 → 意图识别 → 工具规划 → 证据接地回答。

约束（任务书）：
- 基于已有 Evidence First 架构回答；禁止直接生成未经证据支持的信息。
- 不输出投资建议；不推荐股票；不买卖判断。
- 不修改已有核心验证逻辑。

数据结构：
- Intent              用户意图（FACT_QUERY / RISK_EXPLANATION / EVIDENCE_QUERY /
                                    COMPARISON_QUERY / INVESTIGATION_REQUEST）
- ToolStep            工具调用步骤（tool / purpose / input / output / evidence_source）
- ExecutionTrace      执行轨迹（steps / evidence / verification / risk）
- CopilotResponse     Copilot 回答（answer / evidence / verification / risk_score / tool_trace）
- ConversationMessage 会话消息（user / assistant / tools / evidence / timestamp）
- ConversationSession 会话（session_id / messages / created_at）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 用户意图类型（任务书 §2）
# ---------------------------------------------------------------------------
INTENT_FACT_QUERY = "FACT_QUERY"  # 事实查询：调用 Evidence Retrieval
INTENT_RISK_EXPLANATION = "RISK_EXPLANATION"  # 风险解释：调用 Risk Engine
INTENT_EVIDENCE_QUERY = "EVIDENCE_QUERY"  # 证据查询：调用 Evidence Chain
INTENT_COMPARISON_QUERY = "COMPARISON_QUERY"  # 比较查询：调用 Monitoring Memory
INTENT_INVESTIGATION_REQUEST = "INVESTIGATION_REQUEST"  # 调查请求：调用 Autonomous Agent
INTENT_REASONING_EXPLANATION = "REASONING_EXPLANATION"  # 推理解释：调用 Financial Reasoning Engine
INTENT_UNKNOWN = "UNKNOWN"

INTENT_TYPES = {
    INTENT_FACT_QUERY,
    INTENT_RISK_EXPLANATION,
    INTENT_EVIDENCE_QUERY,
    INTENT_COMPARISON_QUERY,
    INTENT_INVESTIGATION_REQUEST,
    INTENT_REASONING_EXPLANATION,
    INTENT_UNKNOWN,
}

INTENT_LABELS = {
    INTENT_FACT_QUERY: "事实查询",
    INTENT_RISK_EXPLANATION: "风险解释",
    INTENT_EVIDENCE_QUERY: "证据查询",
    INTENT_COMPARISON_QUERY: "比较查询",
    INTENT_INVESTIGATION_REQUEST: "调查请求",
    INTENT_REASONING_EXPLANATION: "推理解释",
    INTENT_UNKNOWN: "未知意图",
}


# ---------------------------------------------------------------------------
# 工具名称（路由到已有模块）
# ---------------------------------------------------------------------------
TOOL_EVIDENCE_RETRIEVAL = "evidence_retrieval"
TOOL_VERIFICATION = "verification"
TOOL_RISK_ENGINE = "risk_engine"
TOOL_KNOWLEDGE_GRAPH = "knowledge_graph"
TOOL_MONITORING_MEMORY = "monitoring_memory"
TOOL_AUTONOMOUS_INVESTIGATION = "autonomous_investigation"

TOOL_NAMES = {
    TOOL_EVIDENCE_RETRIEVAL,
    TOOL_VERIFICATION,
    TOOL_RISK_ENGINE,
    TOOL_KNOWLEDGE_GRAPH,
    TOOL_MONITORING_MEMORY,
    TOOL_AUTONOMOUS_INVESTIGATION,
}

TOOL_LABELS = {
    TOOL_EVIDENCE_RETRIEVAL: "证据检索",
    TOOL_VERIFICATION: "核验引擎",
    TOOL_RISK_ENGINE: "风险引擎",
    TOOL_KNOWLEDGE_GRAPH: "知识图谱",
    TOOL_MONITORING_MEMORY: "监控记忆",
    TOOL_AUTONOMOUS_INVESTIGATION: "自主调查",
}


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------
@dataclass
class Intent:
    """识别出的用户意图。"""

    intent_type: str  # INTENT_TYPES
    confidence: float = 0.0
    keywords: list[str] = field(default_factory=list)
    company: str = ""
    metric: str = ""

    def to_dict(self) -> dict:
        return {
            "intent_type": self.intent_type,
            "confidence": round(self.confidence, 3),
            "keywords": self.keywords,
            "company": self.company,
            "metric": self.metric,
        }


# ---------------------------------------------------------------------------
# ToolStep / ExecutionTrace
# ---------------------------------------------------------------------------
@dataclass
class ToolStep:
    """工具调用步骤。"""

    step: int
    tool: str  # TOOL_NAMES
    purpose: str = ""
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    evidence_source: list[dict] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "tool": self.tool,
            "purpose": self.purpose,
            "input": self.input,
            "output": self.output,
            "evidence_source": self.evidence_source,
            "timestamp": self.timestamp,
        }


@dataclass
class ExecutionTrace:
    """执行轨迹：工具链调用 + 证据 + 核验 + 风险。"""

    steps: list[ToolStep] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "evidence": self.evidence,
            "verification": self.verification,
            "risk": self.risk,
        }


# ---------------------------------------------------------------------------
# CopilotResponse（任务书 §4 格式）
# ---------------------------------------------------------------------------
@dataclass
class CopilotResponse:
    """Copilot 回答。

    任务书 §4 必须包含：Summary / Evidence / Reasoning Result / Risk / Source。
    格式：{answer, evidence:[{document,page,content}], verification, risk_score}
    """

    answer: str = ""  # Summary
    evidence: list[dict] = field(default_factory=list)  # [{document, page, content}]
    verification: str = ""  # Reasoning Result / 核验结论
    risk_score: float = 0.0  # Risk
    risk_level: str = "LOW"
    risk_type: str = ""
    source: str = ""  # Source（来源工具链）
    tool_trace: list[ToolStep] = field(default_factory=list)  # 调用过程
    intent: Intent | None = None

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "evidence": self.evidence,
            "verification": self.verification,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "risk_type": self.risk_type,
            "source": self.source,
            "tool_trace": [s.to_dict() for s in self.tool_trace],
            "intent": self.intent.to_dict() if self.intent else None,
        }


# ---------------------------------------------------------------------------
# ConversationMessage / ConversationSession（任务书 §5）
# ---------------------------------------------------------------------------
@dataclass
class ConversationMessage:
    """会话消息。"""

    id: int | None = None
    session_id: str = ""
    role: str = "user"  # user / assistant
    content: str = ""  # 用户问题或助手回答
    intent_type: str = ""
    tools_called: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    risk_score: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "intent_type": self.intent_type,
            "tools_called": self.tools_called,
            "evidence": self.evidence,
            "risk_score": round(self.risk_score, 1),
            "timestamp": self.timestamp,
        }


@dataclass
class ConversationSession:
    """会话：支持连续追问。"""

    session_id: str = ""
    user_id: str = "default"
    messages: list[ConversationMessage] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
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


__all__ = [
    # 意图
    "INTENT_FACT_QUERY",
    "INTENT_RISK_EXPLANATION",
    "INTENT_EVIDENCE_QUERY",
    "INTENT_COMPARISON_QUERY",
    "INTENT_INVESTIGATION_REQUEST",
    "INTENT_UNKNOWN",
    "INTENT_TYPES",
    "INTENT_LABELS",
    # 工具
    "TOOL_EVIDENCE_RETRIEVAL",
    "TOOL_VERIFICATION",
    "TOOL_RISK_ENGINE",
    "TOOL_KNOWLEDGE_GRAPH",
    "TOOL_MONITORING_MEMORY",
    "TOOL_AUTONOMOUS_INVESTIGATION",
    "TOOL_NAMES",
    "TOOL_LABELS",
    # 数据类
    "Intent",
    "ToolStep",
    "ExecutionTrace",
    "CopilotResponse",
    "ConversationMessage",
    "ConversationSession",
    # 工具
    "_now_iso",
    "risk_level_of",
]
