"""审计智能体（Phase 5）：将 Claim→Evidence→Verification→Conclusion 组合为完整审计工作流。

- 不新增核心算法：仅编排已有模块（claim_service / evidence_retrieval / verification_service）；
- 遵守 Evidence First：不凭空判断、不编造证据、不输出投资建议；
- 不自动修改研报、不推荐股票。
"""

from .planner import build_audit_plan
from .executor import run_audit

__all__ = ["build_audit_plan", "run_audit"]
