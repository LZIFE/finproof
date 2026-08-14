"""通用核验方式自动路由（纯函数，无 DB / 无 I/O）。

按主张特征决定核验方式组合：
- internal：有交叉引用，或同一实体多处出现数字（文档内部自洽）
- cross_doc：用户提供了证据文档且主张含实体/数字（跨文档核验）
- external：无内部依据且无证据时，交由外部知识（LLM 常识 / 用户资料 / 联网）
OPINION / PREDICTION 默认不可核验（与财报系统对 forecast/opinion 的处理一致）。
"""

from __future__ import annotations

ROUTE_INTERNAL = "internal"
ROUTE_CROSS_DOC = "cross_doc"
ROUTE_EXTERNAL = "external"

FORCE_MODES = frozenset({ROUTE_INTERNAL, ROUTE_CROSS_DOC, ROUTE_EXTERNAL})
_NOT_VERIFIABLE_KINDS = frozenset({"OPINION", "PREDICTION"})


def route_claim(claim, has_evidence: bool, force_mode: str | None = None,
                has_internal_basis: bool = False) -> list[str]:
    """返回核验方式列表（去重保序）；空列表表示不可核验。

    has_internal_basis：同一实体/语境的数字在文档多处出现（由 service 层
    基于文档块计算），是内部自洽核验的依据之一。
    """
    if force_mode in FORCE_MODES:
        return [force_mode]
    if claim.claim_kind in _NOT_VERIFIABLE_KINDS:
        return []

    routes: list[str] = []
    if claim.cross_refs or has_internal_basis:
        routes.append(ROUTE_INTERNAL)
    if has_evidence and (claim.entities or claim.numbers):
        routes.append(ROUTE_CROSS_DOC)
    if not routes and claim.claim_kind in {"FACT", "NUMERIC"}:
        routes.append(ROUTE_EXTERNAL)
    return list(dict.fromkeys(routes))
