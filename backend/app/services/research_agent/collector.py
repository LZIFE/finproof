"""FinProof Research Collector（Phase 17，任务书 §3）。

按 ResearchPlan 依次执行任务，调用 Evidence Retrieval / Knowledge Graph 收集证据。
所有事实必须绑定 Evidence；无证据 → SKIPPED（不凭空生成）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.evidence_retrieval.service import retrieve_for_claim
from app.services.knowledge_graph.entity_extractor import extract_entities
from app.services.knowledge_graph.graph_builder import build_graph
from app.services.knowledge_graph.fact_graph import get_business_map, get_company_profile
from app.services.research_agent.schemas import (
    EvidenceRef,
    ResearchPlan,
    ResearchTaskSpec,
    TASK_BUSINESS_ANALYSIS,
    TASK_COMPANY_PROFILE,
    TASK_COMPETITION_FACTS,
    TASK_FINANCIAL_OVERVIEW,
    TASK_RISK_DISCOVERY,
    TASK_DONE,
    TASK_PENDING,
    TASK_RUNNING,
    TASK_SKIPPED,
    ToolCall,
    _now_iso,
)


def collect_evidence(
    session: Session,
    plan: ResearchPlan,
    tasks_status: dict[str, str],
    tool_calls: list[ToolCall],
) -> dict[str, list[EvidenceRef]]:
    """按计划收集证据，返回 task_type → evidence 列表。

    无证据的任务标记 SKIPPED（不凭空生成）。
    """
    evidence_by_task: dict[str, list[EvidenceRef]] = {}

    for spec in plan.tasks:
        tasks_status[spec.task_type] = TASK_RUNNING
        evidence_list: list[EvidenceRef] = []

        if spec.need_knowledge_graph:
            # 业务分析：先 retrieve evidence → build graph → business map
            ev_blocks = _retrieve(session, spec, top_k=12)
            evidence_list.extend(ev_blocks)
            kg_result = _build_knowledge_graph(session, plan.company, ev_blocks)
            tool_calls.append(ToolCall(
                tool="knowledge_graph",
                task_type=spec.task_type,
                input_summary=f"build_graph for {plan.company}",
                output_summary=f"entities={kg_result.get('entities_count', 0)} facts={kg_result.get('facts_count', 0)}",
                evidence_count=len(ev_blocks),
                timestamp=_now_iso(),
            ))
        else:
            ev_blocks = _retrieve(session, spec, top_k=8)
            evidence_list.extend(ev_blocks)

        # Competition Facts：再补一条对"竞争对手"的检索
        if spec.task_type == TASK_COMPETITION_FACTS:
            extra = _retrieve(session, ResearchTaskSpec(
                task_type=TASK_COMPETITION_FACTS,
                category="Competition",
                objective=spec.objective,
                claim_query=f"{plan.company} 行业份额 排名",
                metric="competitor",
            ), top_k=6)
            evidence_list.extend(extra)

        evidence_by_task[spec.task_type] = evidence_list
        tasks_status[spec.task_type] = TASK_DONE if evidence_list else TASK_SKIPPED
        tool_calls.append(ToolCall(
            tool="evidence_retrieval",
            task_type=spec.task_type,
            input_summary=spec.claim_query,
            output_summary=f"retrieved {len(evidence_list)} evidence blocks",
            evidence_count=len(evidence_list),
            success=bool(evidence_list),
            timestamp=_now_iso(),
        ))

    return evidence_by_task


# ---------------------------------------------------------------------------
# 内部：证据检索
# ---------------------------------------------------------------------------
def _retrieve(session: Session, spec: ResearchTaskSpec, top_k: int = 8) -> list[EvidenceRef]:
    """对一条任务规格执行 evidence retrieval，返回 EvidenceRef 列表。"""
    claim = {
        "original_text": spec.claim_query,
        "company": "",
        "metric": spec.metric,
    }
    try:
        blocks = retrieve_for_claim(session, claim, top_k=top_k)
    except Exception:  # noqa: BLE001
        return []
    out: list[EvidenceRef] = []
    for b in blocks:
        out.append(EvidenceRef(
            block_id=b.get("block_id") or "",
            document_id=b.get("document_id") or "",
            page_number=b.get("page_number") or "",
            text=b.get("block_text") or b.get("text") or "",
            final_score=float(b.get("final_score") or 0.0),
            evidence_type=b.get("evidence_type") or "",
            evidence_tier=b.get("evidence_tier") or "",
        ))
    return out


def _build_knowledge_graph(session: Session, company: str, evidence: list[EvidenceRef]) -> dict:
    """从证据构建知识图谱（业务地图）。"""
    if not evidence:
        return {"entities_count": 0, "facts_count": 0, "business_map": None, "company_profile": None}
    try:
        # 以证据文本为事实来源，抽取实体
        texts = [{"text": e.text, "block_id": e.block_id, "document_id": e.document_id} for e in evidence]
        entities = extract_entities(texts, company_hint=company)
        company_facts: list[dict] = []
        claims: list[dict] = []
        evidence_dicts = [{"block_id": e.block_id, "document_id": e.document_id, "page_number": e.page_number, "text": e.text} for e in evidence]
        graph = build_graph(entities, company_facts, claims, evidence_dicts)
        try:
            profile = get_company_profile(graph)
            profile_dict = profile.to_dict() if hasattr(profile, "to_dict") else {}
        except Exception:  # noqa: BLE001
            profile_dict = {}
        try:
            bmap = get_business_map(graph)
            bmap_dict = bmap.to_dict() if hasattr(bmap, "to_dict") else {}
        except Exception:  # noqa: BLE001
            bmap_dict = {}
        return {
            "entities_count": len(entities),
            "facts_count": len(graph.facts) if hasattr(graph, "facts") else 0,
            "business_map": bmap_dict,
            "company_profile": profile_dict,
        }
    except Exception as exc:  # noqa: BLE001
        return {"entities_count": 0, "facts_count": 0, "business_map": None, "company_profile": None, "error": str(exc)}


__all__ = ["collect_evidence"]
