"""FinProof Copilot Service Package（Phase 15）。

面向投资经理的交互式 AI 审计助手。

模块：
- schemas              数据结构与常量
- intent_classifier    意图识别
- query_planner        工具链规划与执行
- response_generator   Evidence First 回答生成
- router               主调度器（chat / get_history）

约束：基于已有 Evidence First 架构回答；禁止直接生成未经证据支持的信息；
不输出投资建议；不自动交易；不修改已有核心验证逻辑。
"""

from app.services.copilot.intent_classifier import classify_intent
from app.services.copilot.query_planner import plan_tools, run_plan
from app.services.copilot.response_generator import generate_response
from app.services.copilot.router import chat, get_history, list_sessions

__all__ = [
    # intent
    "classify_intent",
    # planner
    "plan_tools",
    "run_plan",
    # response
    "generate_response",
    # router
    "chat",
    "get_history",
    "list_sessions",
]
