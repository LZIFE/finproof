"""Autonomous Investigation Agent Schemas（Phase 13）。

升级 Supervisor：根据风险类型自主规划调查路径。

数据结构：
- ClaimContext          调查输入（claim / claim_type / risk_type / verification_result）
- InvestigationStep     单步调查（step / tool / input / output / timestamp / reasoning）
- InvestigationPlan     调查计划（steps / objective / risk_type / claim_type）
- InvestigationRun      完整调查运行（plan / steps / evidence / conclusion / trace）
- AgentMemory           Agent 记忆（company / historical_risk / previous_findings / resolved_issues）

约束（任务书）：
- 不修改已有 Verification 核心逻辑；保持 Evidence First。
- Agent 根据计划选择调用工具；禁止直接生成事实。
- 不输出投资建议；不自动交易；不替代投资经理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Claim Type（任务书 §2）
# ---------------------------------------------------------------------------
CLAIM_FINANCIAL = "FINANCIAL"  # 财务数据主张
CLAIM_BUSINESS = "BUSINESS"  # 业务主张
CLAIM_COMPETITIVE = "COMPETITIVE"  # 竞争优势主张
CLAIM_GROWTH = "GROWTH"  # 增长主张
CLAIM_STRATEGIC = "STRATEGIC"  # 战略主张（如"海外业务成为利润增长核心"）
CLAIM_FORECAST = "FORECAST"  # 预测主张

CLAIM_TYPES = {
    CLAIM_FINANCIAL,
    CLAIM_BUSINESS,
    CLAIM_COMPETITIVE,
    CLAIM_GROWTH,
    CLAIM_STRATEGIC,
    CLAIM_FORECAST,
}

CLAIM_TYPE_LABELS = {
    CLAIM_FINANCIAL: "财务数据主张",
    CLAIM_BUSINESS: "业务主张",
    CLAIM_COMPETITIVE: "竞争优势主张",
    CLAIM_GROWTH: "增长主张",
    CLAIM_STRATEGIC: "战略主张",
    CLAIM_FORECAST: "预测主张",
}


# ---------------------------------------------------------------------------
# Risk Type（与 Phase 6/7/9 一致）
# ---------------------------------------------------------------------------
RISK_FINANCIAL_ERROR = "FINANCIAL_ERROR"
RISK_EVIDENCE_RISK = "EVIDENCE_RISK"
RISK_SEMANTIC_RISK = "SEMANTIC_RISK"
RISK_FORECAST_RISK = "FORECAST_RISK"
RISK_BUSINESS_RISK = "BUSINESS_RISK"
RISK_NONE = "NONE"


# ---------------------------------------------------------------------------
# Tool Name（任务书 §3）
# ---------------------------------------------------------------------------
TOOL_RETRIEVE_EVIDENCE = "retrieve_evidence"
TOOL_VERIFY_CLAIM = "verify_claim"
TOOL_GET_COMPANY_PROFILE = "get_company_profile"
TOOL_GET_BUSINESS_MAP = "get_business_map"
TOOL_DETECT_CONFLICTS = "detect_conflicts"
TOOL_ASSESS_RISK = "assess_risk"

TOOL_NAMES = {
    TOOL_RETRIEVE_EVIDENCE,
    TOOL_VERIFY_CLAIM,
    TOOL_GET_COMPANY_PROFILE,
    TOOL_GET_BUSINESS_MAP,
    TOOL_DETECT_CONFLICTS,
    TOOL_ASSESS_RISK,
}

TOOL_LABELS = {
    TOOL_RETRIEVE_EVIDENCE: "检索证据",
    TOOL_VERIFY_CLAIM: "核验主张",
    TOOL_GET_COMPANY_PROFILE: "获取公司画像",
    TOOL_GET_BUSINESS_MAP: "获取业务图谱",
    TOOL_DETECT_CONFLICTS: "检测冲突",
    TOOL_ASSESS_RISK: "评估风险",
}


# ---------------------------------------------------------------------------
# Step Status
# ---------------------------------------------------------------------------
STEP_PENDING = "PENDING"
STEP_RUNNING = "RUNNING"
STEP_DONE = "DONE"
STEP_FAILED = "FAILED"

STEP_STATUSES = {STEP_PENDING, STEP_RUNNING, STEP_DONE, STEP_FAILED}


# ---------------------------------------------------------------------------
# ClaimContext：调查输入
# ---------------------------------------------------------------------------
@dataclass
class ClaimContext:
    """调查输入上下文。"""

    claim_text: str  # 主张文本
    claim_type: str = ""  # CLAIM_TYPES
    risk_type: str = ""  # RISK_*  or ""
    company: str = ""
    stock_code: str = ""
    claim: dict = field(default_factory=dict)  # 原始 claim dict（用于工具调用）
    verification_result: dict = field(default_factory=dict)  # 已有核验结果（可选）

    def to_dict(self) -> dict:
        return {
            "claim_text": self.claim_text,
            "claim_type": self.claim_type,
            "risk_type": self.risk_type,
            "company": self.company,
            "stock_code": self.stock_code,
            "claim": self.claim,
            "verification_result": self.verification_result,
        }


# ---------------------------------------------------------------------------
# InvestigationStep：单步调查
# ---------------------------------------------------------------------------
@dataclass
class InvestigationStep:
    """单步调查：工具调用 + 输入/输出 + 推理。"""

    step: int  # 1-based
    tool: str  # TOOL_NAMES
    purpose: str = ""  # 本步目的（可解释）
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    reasoning: str = ""  # 为什么选择此步（任务书要求不展示隐藏思维链，仅展示 Action/Tool/Evidence）
    status: str = STEP_PENDING
    evidence_source: list[dict] = field(default_factory=list)  # 本步引用的证据来源
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "tool": self.tool,
            "purpose": self.purpose,
            "input": self.input,
            "output": self.output,
            "reasoning": self.reasoning,
            "status": self.status,
            "evidence_source": self.evidence_source,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# InvestigationPlan
# ---------------------------------------------------------------------------
@dataclass
class InvestigationPlan:
    """调查计划：根据 claim_type / risk_type 动态生成 steps。"""

    objective: str = ""  # 调查目标
    claim_type: str = ""
    risk_type: str = ""
    steps: list[InvestigationStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "claim_type": self.claim_type,
            "risk_type": self.risk_type,
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# InvestigationRun：完整调查运行
# ---------------------------------------------------------------------------
@dataclass
class InvestigationRun:
    """完整调查运行：plan → 执行 → evidence → conclusion。"""

    trace_id: str  # TRACE-XXXX
    run_id: str = ""  # INV-XXXX（数据库 id 映射）
    claim_context: ClaimContext = field(default_factory=ClaimContext)
    plan: InvestigationPlan = field(default_factory=InvestigationPlan)
    steps: list[InvestigationStep] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)  # 汇总证据
    conclusion: dict = field(default_factory=dict)  # verification_status / risk_score / risk_type / summary
    memory_used: bool = False  # 是否调用了 Agent Memory
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "claim_context": self.claim_context.to_dict(),
            "plan": self.plan.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "evidence": self.evidence,
            "conclusion": self.conclusion,
            "memory_used": self.memory_used,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# AgentMemory
# ---------------------------------------------------------------------------
@dataclass
class AgentMemory:
    """Agent 记忆：保存公司历史风险 / 前序发现 / 已解决问题。"""

    id: int | None = None
    company: str = ""
    stock_code: str = ""
    historical_risk: dict = field(default_factory=dict)  # {risk_score, risk_level, risk_type}
    previous_findings: list[dict] = field(default_factory=list)  # 前序调查发现
    resolved_issues: list[dict] = field(default_factory=list)  # 已解决问题
    last_investigation_id: int | None = None
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company": self.company,
            "stock_code": self.stock_code,
            "historical_risk": self.historical_risk,
            "previous_findings": self.previous_findings,
            "resolved_issues": self.resolved_issues,
            "last_investigation_id": self.last_investigation_id,
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
    # Claim Type
    "CLAIM_FINANCIAL",
    "CLAIM_BUSINESS",
    "CLAIM_COMPETITIVE",
    "CLAIM_GROWTH",
    "CLAIM_STRATEGIC",
    "CLAIM_FORECAST",
    "CLAIM_TYPES",
    "CLAIM_TYPE_LABELS",
    # Risk Type
    "RISK_FINANCIAL_ERROR",
    "RISK_EVIDENCE_RISK",
    "RISK_SEMANTIC_RISK",
    "RISK_FORECAST_RISK",
    "RISK_BUSINESS_RISK",
    "RISK_NONE",
    # Tool Name
    "TOOL_RETRIEVE_EVIDENCE",
    "TOOL_VERIFY_CLAIM",
    "TOOL_GET_COMPANY_PROFILE",
    "TOOL_GET_BUSINESS_MAP",
    "TOOL_DETECT_CONFLICTS",
    "TOOL_ASSESS_RISK",
    "TOOL_NAMES",
    "TOOL_LABELS",
    # Step Status
    "STEP_PENDING",
    "STEP_RUNNING",
    "STEP_DONE",
    "STEP_FAILED",
    "STEP_STATUSES",
    # 数据类
    "ClaimContext",
    "InvestigationStep",
    "InvestigationPlan",
    "InvestigationRun",
    "AgentMemory",
    # 工具
    "_now_iso",
    "risk_level_of",
]
