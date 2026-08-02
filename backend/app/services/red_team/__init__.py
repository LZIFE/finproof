"""FinProof Red Team Service Package（Phase 14）。

金融 AI 可靠性测试模块：自动生成金融 AI 常见错误，调用已有核验链路检测。

模块：
- schemas            数据结构与常量
- attack_generator   攻击生成器（5 种攻击类型）
- hallucination_detector  幻觉检测器
- stress_test        压力测试引擎 + Reliability Score

约束：不修改已有核心模块；保持 Evidence First。
"""

from app.services.red_team.attack_generator import (
    generate_attack,
    generate_attacks,
    attack_distribution,
)
from app.services.red_team.hallucination_detector import (
    detect_hallucination,
    detect_batch,
)
from app.services.red_team.stress_test import (
    compute_metrics,
    compute_reliability_score,
    run_stress_test,
    get_run,
    list_runs,
)

__all__ = [
    # attack_generator
    "generate_attack",
    "generate_attacks",
    "attack_distribution",
    # hallucination_detector
    "detect_hallucination",
    "detect_batch",
    # stress_test
    "compute_metrics",
    "compute_reliability_score",
    "run_stress_test",
    "get_run",
    "list_runs",
]
