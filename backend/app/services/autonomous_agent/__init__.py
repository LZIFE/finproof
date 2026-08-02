"""Autonomous Investigation Agent Package（Phase 13）。

升级 Supervisor：根据风险类型自主规划调查路径。

模块：
- schemas        数据结构与常量
- planner        调查路径规划
- tool_registry  已有工具封装
- executor       调查执行 + execution_trace 持久化
- memory         Agent 记忆（供 Continuous Monitoring 调用）

约束：
- 不修改已有 Verification 核心逻辑；保持 Evidence First。
- Agent 根据计划选择调用工具；禁止直接生成事实。
- 不输出投资建议；不自动交易；不替代投资经理。
"""

from app.services.autonomous_agent.executor import (
    get_investigation,
    list_investigations,
    run_investigation,
)
from app.services.autonomous_agent.memory import (
    get_memory,
    list_memories,
    resolve_issue,
    upsert_memory,
)
from app.services.autonomous_agent.planner import classify_claim_type, make_plan
from app.services.autonomous_agent.schemas import (
    AgentMemory,
    ClaimContext,
    InvestigationPlan,
    InvestigationRun,
    InvestigationStep,
)
from app.services.autonomous_agent.tool_registry import build_registry, call_tool

__all__ = [
    # executor
    "run_investigation",
    "get_investigation",
    "list_investigations",
    # memory
    "get_memory",
    "upsert_memory",
    "resolve_issue",
    "list_memories",
    # planner
    "classify_claim_type",
    "make_plan",
    # schemas
    "AgentMemory",
    "ClaimContext",
    "InvestigationPlan",
    "InvestigationRun",
    "InvestigationStep",
    # tool_registry
    "build_registry",
    "call_tool",
]
