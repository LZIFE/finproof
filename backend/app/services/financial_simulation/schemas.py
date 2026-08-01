"""FinProof FinSim — Financial Agent Simulation Environment Schemas（Phase 18）。

评估金融 Agent 在复杂研究任务中的能力（测试完整 workflow，不是单个答案）。

保持 Evidence First：Agent 必须基于证据产出，无依据输出计入 Hallucination Score。

**禁止**：投资建议 / 交易 / 修改 Verification 核心逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 场景类型（任务书 §2）
# ---------------------------------------------------------------------------
SCENARIO_FINANCIAL_MISSTATEMENT = "Financial Misstatement"        # 财务错报
SCENARIO_BUSINESS_OVERSTATEMENT = "Business Overstatement"        # 业务夸大
SCENARIO_GROWTH_QUALITY_PROBLEM = "Growth Quality Problem"        # 增长质量问题
SCENARIO_COMPETITIVE_CLAIM_VERIFICATION = "Competitive Claim Verification"  # 竞争主张验证
SCENARIO_RISK_MONITORING = "Risk Monitoring"                      # 风险监控

SCENARIO_TYPES = {
    SCENARIO_FINANCIAL_MISSTATEMENT,
    SCENARIO_BUSINESS_OVERSTATEMENT,
    SCENARIO_GROWTH_QUALITY_PROBLEM,
    SCENARIO_COMPETITIVE_CLAIM_VERIFICATION,
    SCENARIO_RISK_MONITORING,
}

SCENARIO_LABELS = {
    SCENARIO_FINANCIAL_MISSTATEMENT: "财务错报",
    SCENARIO_BUSINESS_OVERSTATEMENT: "业务夸大",
    SCENARIO_GROWTH_QUALITY_PROBLEM: "增长质量问题",
    SCENARIO_COMPETITIVE_CLAIM_VERIFICATION: "竞争主张验证",
    SCENARIO_RISK_MONITORING: "风险监控",
}


# ---------------------------------------------------------------------------
# 难度（任务书 §5）
# ---------------------------------------------------------------------------
DIFFICULTY_EASY = "Easy"
DIFFICULTY_MEDIUM = "Medium"
DIFFICULTY_HARD = "Hard"

DIFFICULTY_LEVELS = {DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD}

DIFFICULTY_WEIGHTS = {
    DIFFICULTY_EASY: 1.0,
    DIFFICULTY_MEDIUM: 1.2,
    DIFFICULTY_HARD: 1.5,  # Hard 难度乘数加成
}


# ---------------------------------------------------------------------------
# Simulation 阶段（任务书 §3 流程）
# ---------------------------------------------------------------------------
PHASE_SCENARIO = "Scenario"
PHASE_AGENT_INVESTIGATES = "Agent Investigates"
PHASE_COLLECT_EVIDENCE = "Collect Evidence"
PHASE_GENERATE_MEMO = "Generate Memo"
PHASE_COMPARE_AND_SCORE = "Compare and Score"

PHASE_ORDER = [
    PHASE_SCENARIO,
    PHASE_AGENT_INVESTIGATES,
    PHASE_COLLECT_EVIDENCE,
    PHASE_GENERATE_MEMO,
    PHASE_COMPARE_AND_SCORE,
]


# ---------------------------------------------------------------------------
# ExpectedFinding：场景埋点（任务书 §2 expected_findings + hidden_risks）
# ---------------------------------------------------------------------------
@dataclass
class ExpectedFinding:
    """场景埋点：Agent 应发现的事实 / 风险。

    用于评分比对：Agent 的 finding.content 命中 expected.text 关键词即视为检出。
    """

    finding_id: str = ""  # EF-XXXX
    category: str = ""  # fact / risk / logic / contradiction
    text: str = ""  # 预期发现的核心文本（含关键指标/风险词）
    must_find: bool = True  # True=必须检出；False=可选检出
    finding_type: str = ""  # financial / business / growth / competitive / risk

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "category": self.category,
            "text": self.text,
            "must_find": self.must_find,
            "finding_type": self.finding_type,
        }


# ---------------------------------------------------------------------------
# SimulationScenario（任务书 §2）
# ---------------------------------------------------------------------------
@dataclass
class SimulationScenario:
    """模拟场景。

    任务书 §2 字段：scenario_id / company / industry / objective /
    available_documents / hidden_risks / expected_findings / difficulty。
    """

    scenario_id: str = ""  # SCEN-A / SCEN-B ...
    scenario_type: str = ""  # SCENARIO_TYPES
    company: str = ""
    industry: str = ""
    objective: str = ""  # Agent 任务目标（自然语言）
    available_documents: list[dict] = field(default_factory=list)  # 文档清单（id/period/sections）
    hidden_risks: list[str] = field(default_factory=list)  # 隐藏风险（Hard 难度埋点）
    expected_findings: list[ExpectedFinding] = field(default_factory=list)
    difficulty: str = DIFFICULTY_EASY
    task_query: str = ""  # 喂给 Agent 的研究查询（company + objective）

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type,
            "company": self.company,
            "industry": self.industry,
            "objective": self.objective,
            "available_documents": self.available_documents,
            "hidden_risks": self.hidden_risks,
            "expected_findings": [e.to_dict() for e in self.expected_findings],
            "difficulty": self.difficulty,
            "task_query": self.task_query,
        }


# ---------------------------------------------------------------------------
# SimulationStep：Agent 执行步骤记录（任务书 §3 simulation_steps）
# ---------------------------------------------------------------------------
@dataclass
class SimulationStep:
    """模拟步骤：phase / tool / input / output / evidence_count / timestamp。"""

    step_id: str = ""  # STEP-001
    phase: str = ""  # PHASE_ORDER
    tool: str = ""  # research_agent / verification / reasoning / risk / red_team / knowledge_graph
    input_summary: str = ""
    output_summary: str = ""
    evidence_count: int = 0
    findings_count: int = 0
    success: bool = True
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "phase": self.phase,
            "tool": self.tool,
            "input_summary": self.input_summary[:200],
            "output_summary": self.output_summary[:200],
            "evidence_count": self.evidence_count,
            "findings_count": self.findings_count,
            "success": self.success,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# AgentRunRecord：被模拟 Agent 的运行记录（来自 Research Agent）
# ---------------------------------------------------------------------------
@dataclass
class AgentRunRecord:
    """被评估 Agent 的运行记录：tool_calls / findings / evidence / memo。"""

    session_id: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    risk_findings: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    memo: dict = field(default_factory=dict)
    duration_sec: float = 0.0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "tool_calls": self.tool_calls,
            "findings": self.findings,
            "risk_findings": self.risk_findings,
            "evidence": self.evidence,
            "memo": self.memo,
            "duration_sec": round(self.duration_sec, 3),
        }


# ---------------------------------------------------------------------------
# ScoreBreakdown：评分明细（任务书 §4）
# ---------------------------------------------------------------------------
@dataclass
class ScoreBreakdown:
    """单项评分：score 0-100 + 检出明细。"""

    score: float = 0.0
    expected_count: int = 0
    detected_count: int = 0
    missed: list[str] = field(default_factory=list)  # 未检出 expected_id
    false_positives: list[str] = field(default_factory=list)  # Agent 输出但非 expected
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "expected_count": self.expected_count,
            "detected_count": self.detected_count,
            "missed": self.missed,
            "false_positives": self.false_positives,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# SimulationScore（任务书 §4 5 项评分）
# ---------------------------------------------------------------------------
@dataclass
class SimulationScore:
    """模拟评分：5 项子分 + FinAgent Score。"""

    evidence_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)        # 证据覆盖率
    reasoning_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)      # 逻辑漏洞发现率
    risk_detection_score: ScoreBreakdown = field(default_factory=ScoreBreakdown) # 风险识别率
    efficiency_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)     # 工具调用效率
    hallucination_score: ScoreBreakdown = field(default_factory=ScoreBreakdown)  # 无依据输出比例
    fin_agent_score: float = 0.0  # 加权综合 0-100
    difficulty_weight: float = 1.0
    final_score: float = 0.0  # 难度加权后最终得分

    def to_dict(self) -> dict:
        return {
            "evidence_score": self.evidence_score.to_dict(),
            "reasoning_score": self.reasoning_score.to_dict(),
            "risk_detection_score": self.risk_detection_score.to_dict(),
            "efficiency_score": self.efficiency_score.to_dict(),
            "hallucination_score": self.hallucination_score.to_dict(),
            "fin_agent_score": round(self.fin_agent_score, 2),
            "difficulty_weight": self.difficulty_weight,
            "final_score": round(self.final_score, 2),
        }


# ---------------------------------------------------------------------------
# SimulationResult（任务书 §3 simulation_results）
# ---------------------------------------------------------------------------
@dataclass
class SimulationResult:
    """模拟结果：Agent run + 评分 + 命中明细。"""

    result_id: str = ""  # SIMRES-XXXX
    run_id: str = ""  # 关联 SimulationRun
    agent_run: AgentRunRecord = field(default_factory=AgentRunRecord)
    detected_findings: list[str] = field(default_factory=list)  # 检出的 expected_id
    missed_findings: list[str] = field(default_factory=list)  # 未检出
    hallucination_findings: list[str] = field(default_factory=list)  # 无依据输出
    score: SimulationScore = field(default_factory=SimulationScore)
    success: bool = False  # 必须 expected 全检出且无幻觉 → success
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "run_id": self.run_id,
            "agent_run": self.agent_run.to_dict(),
            "detected_findings": self.detected_findings,
            "missed_findings": self.missed_findings,
            "hallucination_findings": self.hallucination_findings,
            "score": self.score.to_dict(),
            "success": self.success,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# SimulationRun（任务书 §3 simulation_runs）
# ---------------------------------------------------------------------------
@dataclass
class SimulationRun:
    """模拟运行：scenario + steps + result。"""

    run_id: str = ""  # SIM-RUN-XXXX
    scenario_id: str = ""
    scenario: SimulationScenario | None = None
    agent_name: str = "FinProof Research Agent"
    phase: str = PHASE_SCENARIO
    steps: list[SimulationStep] = field(default_factory=list)
    result: SimulationResult | None = None
    created_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "scenario": self.scenario.to_dict() if self.scenario else None,
            "agent_name": self.agent_name,
            "phase": self.phase,
            "steps": [s.to_dict() for s in self.steps],
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


def contains_forbidden_content(text: str) -> bool:
    """检查 Agent 输出是否含禁止词（投资建议/股票推荐/估值预测）。"""
    if not text:
        return False
    lowered = text.lower()
    for kw in FORBIDDEN_KW:
        if kw.lower() in lowered:
            return True
    return False


__all__ = [
    # 场景类型
    "SCENARIO_FINANCIAL_MISSTATEMENT",
    "SCENARIO_BUSINESS_OVERSTATEMENT",
    "SCENARIO_GROWTH_QUALITY_PROBLEM",
    "SCENARIO_COMPETITIVE_CLAIM_VERIFICATION",
    "SCENARIO_RISK_MONITORING",
    "SCENARIO_TYPES",
    "SCENARIO_LABELS",
    # 难度
    "DIFFICULTY_EASY",
    "DIFFICULTY_MEDIUM",
    "DIFFICULTY_HARD",
    "DIFFICULTY_LEVELS",
    "DIFFICULTY_WEIGHTS",
    # 阶段
    "PHASE_SCENARIO",
    "PHASE_AGENT_INVESTIGATES",
    "PHASE_COLLECT_EVIDENCE",
    "PHASE_GENERATE_MEMO",
    "PHASE_COMPARE_AND_SCORE",
    "PHASE_ORDER",
    # 数据类
    "ExpectedFinding",
    "SimulationScenario",
    "SimulationStep",
    "AgentRunRecord",
    "ScoreBreakdown",
    "SimulationScore",
    "SimulationResult",
    "SimulationRun",
    # 工具
    "_now_iso",
    "FORBIDDEN_KW",
    "contains_forbidden_content",
]
