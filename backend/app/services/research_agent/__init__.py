"""FinProof Autonomous Financial Research Agent Package（Phase 17）。

从企业名称/股票代码出发的自主金融研究流程，输出 Evidence First Research Memo。

模块：
- schemas          数据结构与常量（5 任务类型 + 4 阶段 + Memo 禁止词）
- planner          研究规划器（make_plan：Financial / Business / Risk / Competition）
- collector        证据收集器（collect_evidence：Evidence Retrieval + Knowledge Graph）
- analyst          事实分析师（analyze_findings：ResearchFinding + RiskFinding）
- memo_generator   Memo 生成器（generate_memo：7 段结构 + 禁止词护栏）

约束：不生成投资建议；不做股票推荐；不做自动交易；不修改 Verification 核心逻辑。
"""

from app.services.research_agent.analyst import analyze_findings
from app.services.research_agent.collector import collect_evidence
from app.services.research_agent.memo_generator import generate_memo
from app.services.research_agent.planner import make_plan
from app.services.research_agent.schemas import (
    EvidenceRef,
    ResearchFinding,
    ResearchMemo,
    ResearchPlan,
    ResearchSession,
    ResearchTaskSpec,
    RiskFinding,
    ToolCall,
    PHASE_ORDER,
    TASK_TYPES,
    TASK_LABELS,
    contains_forbidden_memo_content,
)

__all__ = [
    # schemas
    "EvidenceRef",
    "ResearchFinding",
    "ResearchMemo",
    "ResearchPlan",
    "ResearchSession",
    "ResearchTaskSpec",
    "RiskFinding",
    "ToolCall",
    "PHASE_ORDER",
    "TASK_TYPES",
    "TASK_LABELS",
    "contains_forbidden_memo_content",
    # 模块
    "make_plan",
    "collect_evidence",
    "analyze_findings",
    "generate_memo",
]
