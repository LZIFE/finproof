"""FinProof FinSim — Financial Agent Simulation Environment Package（Phase 18）。

评估金融 Agent 在复杂研究任务中的能力（完整 workflow）。

模块：
- schemas              数据结构与常量（5 场景类型 + 3 难度 + 5 阶段 + 评分结构）
- scenario_generator   场景生成器（make_scenario / build_scenario_catalog / make_demo_scenarios）
- simulator            模拟器（run_simulation / run_simulation_by_id）
- evaluator            评估器（evaluate_run / aggregate_metrics）
- scoring              评分（5 项子分 + FinAgent Score 合成）

约束：不输出投资建议；不交易；不修改 Verification 核心。
"""

from app.services.financial_simulation.evaluator import (
    aggregate_metrics,
    evaluate_run,
    print_aggregate,
)
from app.services.financial_simulation.scenario_generator import (
    build_scenario_catalog,
    list_scenario_types,
    make_demo_scenarios,
    make_scenario,
)
from app.services.financial_simulation.scoring import (
    compute_fin_agent_score,
    score_evidence,
    score_efficiency,
    score_hallucination,
    score_reasoning,
    score_risk_detection,
)
from app.services.financial_simulation.simulator import (
    run_simulation,
    run_simulation_by_id,
)
from app.services.financial_simulation.schemas import (
    AgentRunRecord,
    ExpectedFinding,
    SimulationResult,
    SimulationRun,
    SimulationScenario,
    SimulationScore,
    SimulationStep,
    PHASE_ORDER,
    SCENARIO_TYPES,
    SCENARIO_LABELS,
    SCENARIO_BUSINESS_OVERSTATEMENT,
    SCENARIO_COMPETITIVE_CLAIM_VERIFICATION,
    SCENARIO_FINANCIAL_MISSTATEMENT,
    SCENARIO_GROWTH_QUALITY_PROBLEM,
    SCENARIO_RISK_MONITORING,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_LEVELS,
    DIFFICULTY_MEDIUM,
    DIFFICULTY_WEIGHTS,
    contains_forbidden_content,
)

__all__ = [
    # schemas
    "AgentRunRecord",
    "ExpectedFinding",
    "SimulationResult",
    "SimulationRun",
    "SimulationScenario",
    "SimulationScore",
    "SimulationStep",
    "PHASE_ORDER",
    "SCENARIO_TYPES",
    "SCENARIO_LABELS",
    "DIFFICULTY_LEVELS",
    "DIFFICULTY_WEIGHTS",
    "contains_forbidden_content",
    # scenario_generator
    "make_scenario",
    "list_scenario_types",
    "build_scenario_catalog",
    "make_demo_scenarios",
    # simulator
    "run_simulation",
    "run_simulation_by_id",
    # evaluator
    "evaluate_run",
    "aggregate_metrics",
    "print_aggregate",
    # scoring
    "compute_fin_agent_score",
    "score_evidence",
    "score_efficiency",
    "score_hallucination",
    "score_reasoning",
    "score_risk_detection",
]
