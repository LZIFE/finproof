"""FinProof Competition Demo Mode Package（Phase 22）。

比赛演示模式：让评委无需理解系统结构，通过一次点击看到完整 AI 审计闭环。
**不新增分析能力**，仅编排已有模块。保持 Evidence First。
禁止投资建议 / 股票推荐 / 交易 / 修改 Verification/Risk 核心。
"""

from app.services.demo_mode.demo_runner import get_demo, get_demo_steps, list_demos, start_demo
from app.services.demo_mode.demo_steps import (
    step_assess_risk,
    step_build_replay,
    step_extract_claims,
    step_generate_dashboard,
    step_retrieve_evidence,
    step_run_arena,
    step_run_reasoning,
    step_verify_claims,
)
from app.services.demo_mode.schemas import (
    BACKEND_STEPS,
    DEMO_COMPANY,
    DEMO_REPORT_TITLE,
    DEMO_SCENARIOS,
    DemoRun,
    DemoStep,
    FRONTEND_STEPS,
    FRONTEND_STEP_LABELS,
    FRONTEND_TO_BACKEND,
    contains_forbidden_content,
)

__all__ = [
    # schemas
    "BACKEND_STEPS", "FRONTEND_STEPS", "FRONTEND_STEP_LABELS",
    "FRONTEND_TO_BACKEND", "DemoRun", "DemoStep",
    "DEMO_COMPANY", "DEMO_REPORT_TITLE", "DEMO_SCENARIOS",
    "contains_forbidden_content",
    # steps
    "step_extract_claims", "step_retrieve_evidence", "step_verify_claims",
    "step_assess_risk", "step_run_reasoning", "step_run_arena",
    "step_generate_dashboard", "step_build_replay",
    # runner
    "start_demo", "get_demo", "get_demo_steps", "list_demos",
]
