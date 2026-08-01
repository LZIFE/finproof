"""FinProof Analyst Agent（Phase 19，任务书 §1 Analyst Agent）。

负责：分析公司业务、提取财务事实、建立研究观点。
必须：每个观点绑定 Evidence。

调用：Research Agent / Evidence Retrieval / Knowledge Graph。
约束：不输出投资建议；所有结论来自 Evidence。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.agent_arena.schemas import (
    AnalystViewpoint,
    EvidenceRef,
    PHASE_ANALYST,
    ROLE_ANALYST,
    _now_iso,
    contains_forbidden_content,
)
from app.services.agent_arena.schemas import ArenaMessage  # noqa: F401


def generate_viewpoints(
    session: Session,
    company: str,
    research_question: str,
) -> tuple[list[AnalystViewpoint], list[EvidenceRef], ArenaMessage]:
    """Analyst 生成研究观点：每个观点绑定 Evidence。

    流程：
      1. 调用 Research Agent 收集证据与事实
      2. 将事实转为 AnalystViewpoint（claim + evidence + confidence）
      3. 无证据的事实 → unsupported=True（将被 Skeptic 抓出）
    """
    from app.services.research_agent.orchestrator import run_research

    viewpoints: list[AnalystViewpoint] = []
    all_evidence: list[EvidenceRef] = []

    try:
        rs = run_research(session, company, "")
    except Exception as exc:  # noqa: BLE001
        # Research Agent 失败 → Analyst 至少产出一条 unsupported 观点（不凭空生成事实）
        viewpoints.append(AnalystViewpoint(
            viewpoint_id="AV-001",
            claim=f"由于研究工具失败，{company} {research_question} 暂无证据支持的观点。",
            evidence=[],
            confidence=0.0,
            unsupported=True,
        ))
        msg = ArenaMessage(
            message_id="MSG-001",
            role=ROLE_ANALYST,
            phase=PHASE_ANALYST,
            content=f"Analyst 启动但 Research Agent 失败：{exc}",
            viewpoints=viewpoints,
            timestamp=_now_iso(),
        )
        return viewpoints, all_evidence, msg

    # 从 Research Agent findings 抽取观点
    finding_idx = 0
    for f in rs.findings:
        finding_idx += 1
        claim_text = f.content
        # 护栏：观点不含禁止词
        if contains_forbidden_content(claim_text):
            continue
        ev_refs = [
            EvidenceRef(
                block_id=e.block_id,
                document_id=e.document_id,
                page_number=e.page_number,
                text=e.text,
                final_score=e.final_score,
                evidence_type=e.evidence_type,
                evidence_tier=e.evidence_tier,
            )
            for e in f.evidence
        ]
        all_evidence.extend(ev_refs)
        unsupported = not ev_refs or not f.supported
        confidence = 0.9 if ev_refs else 0.3
        viewpoints.append(AnalystViewpoint(
            viewpoint_id=f"AV-{finding_idx:03d}",
            claim=claim_text,
            evidence=ev_refs,
            confidence=confidence,
            metric=f.metric,
            unsupported=unsupported,
        ))

    # 若 Research Agent 无产出，至少一条占位观点
    if not viewpoints:
        viewpoints.append(AnalystViewpoint(
            viewpoint_id="AV-001",
            claim=f"{company} {research_question}：Research Agent 未检索到证据，列入待验证。",
            evidence=[],
            confidence=0.0,
            unsupported=True,
        ))

    msg = ArenaMessage(
        message_id="MSG-001",
        role=ROLE_ANALYST,
        phase=PHASE_ANALYST,
        content=f"Analyst 基于 {len(all_evidence)} 条证据提出 {len(viewpoints)} 个观点（其中 {sum(1 for v in viewpoints if v.unsupported)} 个无证据支持）。",
        viewpoints=viewpoints,
        evidence=all_evidence,
        timestamp=_now_iso(),
    )
    return viewpoints, all_evidence, msg


__all__ = ["generate_viewpoints"]
