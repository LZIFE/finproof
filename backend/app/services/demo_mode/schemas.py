"""FinProof Competition Demo Mode Schemas（Phase 22）。

创建比赛演示模式：让评委无需理解系统结构，通过一次点击看到完整 AI 审计闭环。
**不新增分析能力**，仅编排已有模块。保持 Evidence First。

禁止投资建议 / 股票推荐 / 交易 / 修改 Verification/Risk 核心。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Demo 步骤定义（任务书 §自动执行已有流程 + §执行动画）
# ---------------------------------------------------------------------------
# 后端 8 步（任务书 §自动执行）
STEP_EXTRACT_CLAIMS = "extract_claims"           # ① 提取主张
STEP_RETRIEVE_EVIDENCE = "retrieve_evidence"     # ② 检索证据
STEP_VERIFY_CLAIMS = "verify_claims"            # ③ 验证事实
STEP_ASSESS_RISK = "assess_risk"               # ④ 评估风险
STEP_RUN_REASONING = "run_reasoning"           # ⑤ 逻辑推理
STEP_RUN_ARENA = "run_arena"                   # ⑥ Agent 竞技
STEP_GENERATE_DASHBOARD = "generate_dashboard"  # ⑦ 治理仪表板
STEP_BUILD_REPLAY = "build_replay"             # ⑧ 审计回放

BACKEND_STEPS = [
    STEP_EXTRACT_CLAIMS,
    STEP_RETRIEVE_EVIDENCE,
    STEP_VERIFY_CLAIMS,
    STEP_ASSESS_RISK,
    STEP_RUN_REASONING,
    STEP_RUN_ARENA,
    STEP_GENERATE_DASHBOARD,
    STEP_BUILD_REPLAY,
]

# 前端 6 步动画（任务书 §执行动画）
FRONTEND_STEP_1 = "Understanding AI Report"     # 理解 AI 报告
FRONTEND_STEP_2 = "Finding Evidence"            # 发现证据
FRONTEND_STEP_3 = "Checking Facts"             # 核查事实
FRONTEND_STEP_4 = "Detecting Risks"            # 检测风险
FRONTEND_STEP_5 = "Agent Debate"               # Agent 辩论
FRONTEND_STEP_6 = "Generating Governance Report"  # 生成治理报告

FRONTEND_STEPS = [
    FRONTEND_STEP_1,
    FRONTEND_STEP_2,
    FRONTEND_STEP_3,
    FRONTEND_STEP_4,
    FRONTEND_STEP_5,
    FRONTEND_STEP_6,
]

FRONTEND_STEP_LABELS = {
    FRONTEND_STEP_1: "理解 AI 报告",
    FRONTEND_STEP_2: "发现证据",
    FRONTEND_STEP_3: "核查事实",
    FRONTEND_STEP_4: "检测风险",
    FRONTEND_STEP_5: "Agent 辩论",
    FRONTEND_STEP_6: "生成治理报告",
}

# 后端 8 步 → 前端 6 步映射（前端合并 verify+reasoning 为 Checking Facts）
FRONTEND_TO_BACKEND = {
    FRONTEND_STEP_1: [STEP_EXTRACT_CLAIMS],
    FRONTEND_STEP_2: [STEP_RETRIEVE_EVIDENCE],
    FRONTEND_STEP_3: [STEP_VERIFY_CLAIMS, STEP_RUN_REASONING],
    FRONTEND_STEP_4: [STEP_ASSESS_RISK],
    FRONTEND_STEP_5: [STEP_RUN_ARENA],
    FRONTEND_STEP_6: [STEP_GENERATE_DASHBOARD, STEP_BUILD_REPLAY],
}


# ---------------------------------------------------------------------------
# DemoStep（任务书 §DemoStep）
# ---------------------------------------------------------------------------
@dataclass
class DemoStep:
    """单步演示记录。"""

    step_number: int = 0
    name: str = ""          # 后端步骤名（BACKEND_STEPS）
    frontend_label: str = ""  # 对应前端动画标签
    status: str = "PENDING"  # PENDING / RUNNING / OK / SKIPPED / ERROR
    duration: int = 0       # ms
    input_reference: str = ""   # 输入引用（如 company / report_id / 上步产出）
    output_reference: str = ""  # 输出引用（如 arena_run_id / dashboard_id）
    source: str = ""        # 来源模块
    evidence: str = ""      # 证据摘要
    result: str = ""        # 结果摘要
    error: str = ""
    # Phase 23.6：结构化附加数据，供后续步骤真实串联（claim_ids / evidence_ids / run_id 等）
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step_number": self.step_number,
            "name": self.name,
            "frontend_label": self.frontend_label,
            "status": self.status,
            "duration": self.duration,
            "input_reference": self.input_reference,
            "output_reference": self.output_reference,
            "source": self.source,
            "evidence": self.evidence,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# DemoRun（任务书 §数据库 demo_runs）
# ---------------------------------------------------------------------------
@dataclass
class DemoRun:
    """演示运行：company + report_id + 8 步 + 最终输出。"""

    demo_id: str = ""       # DEMO-XXXX
    company: str = ""
    report_id: str = ""     # 既有报告 id（可选）
    status: str = "PENDING"  # PENDING / RUNNING / DONE / ERROR
    current_step: str = ""   # 当前步骤名
    steps: list[DemoStep] = field(default_factory=list)
    # 最终输出（任务书 §最后展示）
    reliability_score: float = 0.0
    risk_findings: list[dict] = field(default_factory=list)
    audit_replay_id: str = ""
    audit_replay: dict = field(default_factory=dict)
    arena_run_id: str = ""
    dashboard_id: str = ""
    created_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "demo_id": self.demo_id,
            "company": self.company,
            "report_id": self.report_id,
            "status": self.status,
            "current_step": self.current_step,
            "steps": [s.to_dict() for s in self.steps],
            "reliability_score": round(self.reliability_score, 2),
            "risk_findings": self.risk_findings,
            "audit_replay_id": self.audit_replay_id,
            "audit_replay": self.audit_replay,
            "arena_run_id": self.arena_run_id,
            "dashboard_id": self.dashboard_id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "frontend_steps": FRONTEND_STEPS,
            "frontend_labels": FRONTEND_STEP_LABELS,
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


# 固定 Demo Case（任务书 §Demo Case）
DEMO_COMPANY = "美的集团"
DEMO_REPORT_TITLE = "美的集团 AI 研究报告"
DEMO_SCENARIOS = [
    "错误财务增长率",
    "战略夸大",
    "证据不足",
]


__all__ = [
    # 步骤
    "STEP_EXTRACT_CLAIMS", "STEP_RETRIEVE_EVIDENCE", "STEP_VERIFY_CLAIMS",
    "STEP_ASSESS_RISK", "STEP_RUN_REASONING", "STEP_RUN_ARENA",
    "STEP_GENERATE_DASHBOARD", "STEP_BUILD_REPLAY",
    "BACKEND_STEPS",
    "FRONTEND_STEP_1", "FRONTEND_STEP_2", "FRONTEND_STEP_3",
    "FRONTEND_STEP_4", "FRONTEND_STEP_5", "FRONTEND_STEP_6",
    "FRONTEND_STEPS", "FRONTEND_STEP_LABELS", "FRONTEND_TO_BACKEND",
    # 数据类
    "DemoStep", "DemoRun",
    # Demo Case
    "DEMO_COMPANY", "DEMO_REPORT_TITLE", "DEMO_SCENARIOS",
    # 工具
    "_now_iso", "contains_forbidden_content",
]
