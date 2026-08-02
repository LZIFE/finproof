"""Knowledge Graph API（Phase 10）。

- POST /api/v1/knowledge-graph/build                 构建知识图谱（实体/关系/事实）
- GET  /api/v1/knowledge-graph/{document_id}         查询知识图谱（实体网络/事实/证据来源）
- POST /api/v1/knowledge-graph/conflicts             冲突推理（Claim vs Graph Fact）
- GET  /api/v1/knowledge-graph/{document_id}/profile 查询 Company Profile
- GET  /api/v1/knowledge-graph/{document_id}/business-map 查询 Business Map
- GET  /api/v1/knowledge-graph/{document_id}/evidence-sources 查询 Evidence Sources
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.knowledge_graph import (
    ConflictDetectRequest,
    KnowledgeGraphBuildRequest,
)
from app.services.knowledge_graph.conflict_reasoner import (
    compute_overall_risk,
    detect_conflicts,
)
from app.services.knowledge_graph.fact_graph import (
    get_business_map,
    get_company_profile,
    get_entity_network,
    get_evidence_sources,
)
from app.services.knowledge_graph.graph_builder import (
    build_graph,
    load_graph,
    save_graph,
)

router = APIRouter(tags=["knowledge_graph"])


# ---------------------------------------------------------------------------
# 辅助：收集 Claims / Evidence / Company Facts
# ---------------------------------------------------------------------------
def _collect_inputs(
    session: Session,
    document_id: int,
    audit_id: int | None,
    intelligence_report_id: int | None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """收集构建知识图谱所需的输入源。

    返回 (claims, evidence, company_facts)。
    """
    import json

    claims: list[dict] = []
    evidence: list[dict] = []
    company_facts: list[dict] = []

    # ---- 1. Claims（从 Claim Extraction）----
    from app.models.claim import Claim, ExtractionRun

    if audit_id is not None:
        # 通过 audit_id 找到对应文档的主张运行
        from app.models.audit import AuditReport

        audit = session.get(AuditReport, audit_id)
        if audit is not None:
            doc_id = audit.document_id
            run = (
                session.query(ExtractionRun)
                .filter(ExtractionRun.document_id == doc_id)
                .order_by(ExtractionRun.id.desc())
                .first()
            )
            if run is not None:
                rows = (
                    session.query(Claim)
                    .filter(Claim.extraction_run_id == run.id)
                    .all()
                )
                for r in rows:
                    claims.append(
                        {
                            "claim_id": r.claim_uid,
                            "claim_uid": r.claim_uid,
                            "original_text": r.source_text,
                            "source_text": r.source_text,
                            "claim_type": r.claim_type,
                            "entity_name": r.entity_name,
                            "stock_code": r.stock_code,
                            "metric": r.metric,
                            "metric_code": r.metric_code,
                            "reported_value": r.reported_value,
                            "value": r.reported_value,
                            "unit": r.unit,
                            "period": r.period,
                        }
                    )
    else:
        # 无 audit_id：尝试通过 document_id 查找主张
        run = (
            session.query(ExtractionRun)
            .filter(ExtractionRun.document_id == document_id)
            .order_by(ExtractionRun.id.desc())
            .first()
        )
        if run is not None:
            rows = (
                session.query(Claim)
                .filter(Claim.extraction_run_id == run.id)
                .all()
            )
            for r in rows:
                claims.append(
                    {
                        "claim_id": r.claim_uid,
                        "claim_uid": r.claim_uid,
                        "original_text": r.source_text,
                        "source_text": r.source_text,
                        "claim_type": r.claim_type,
                        "entity_name": r.entity_name,
                        "stock_code": r.stock_code,
                        "metric": r.metric,
                        "metric_code": r.metric_code,
                        "reported_value": r.reported_value,
                        "value": r.reported_value,
                        "unit": r.unit,
                        "period": r.period,
                    }
                )

    # ---- 2. Evidence（从 Evidence Retrieval）----
    from app.models.evidence import EvidenceCandidate

    evidence_rows = (
        session.query(EvidenceCandidate)
        .filter(EvidenceCandidate.document_id == document_id)
        .limit(50)
        .all()
    )
    for e in evidence_rows:
        evidence.append(
            {
                "page_number": e.page_number,
                "block_id": e.block_id,
                "text": e.text or "",
                "evidence_type": e.evidence_type,
            }
        )

    # ---- 3. Company Facts（从 Intelligence Report）----
    if intelligence_report_id is not None:
        from app.models.intelligence import IntelligenceReportRow

        intel_row = session.get(IntelligenceReportRow, intelligence_report_id)
        if intel_row is not None:
            intel_data = json.loads(intel_row.report_json or "{}")
            company_facts = intel_data.get("verified_facts", [])

    return claims, evidence, company_facts


# ---------------------------------------------------------------------------
# POST /build
# ---------------------------------------------------------------------------
@router.post("/api/v1/knowledge-graph/build", status_code=201)
def build_knowledge_graph(
    body: KnowledgeGraphBuildRequest,
    session: Session = Depends(get_session),
) -> dict:
    """构建知识图谱：从 Claims/Evidence/Company Facts 抽取实体/关系/事实。"""
    try:
        claims, evidence, company_facts = _collect_inputs(
            session,
            body.document_id,
            body.audit_id,
            body.intelligence_report_id,
        )

        # 抽取实体
        from app.services.knowledge_graph.entity_extractor import extract_entities

        entities = extract_entities(claims, evidence, company_facts)

        # 构建图谱
        graph = build_graph(entities, company_facts, claims, evidence)

        # 持久化
        graph = save_graph(session, graph, document_id=body.document_id)

        return {
            "document_id": body.document_id,
            "entity_count": len(graph.entities),
            "relationship_count": len(graph.relationships),
            "fact_count": len(graph.facts),
            "graph": graph.to_dict(),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"构建知识图谱失败: {exc}") from exc


# ---------------------------------------------------------------------------
# GET /{document_id}
# ---------------------------------------------------------------------------
@router.get("/api/v1/knowledge-graph/{document_id}")
def get_knowledge_graph(
    document_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """查询知识图谱：实体网络 + 事实 + 证据来源。"""
    try:
        graph = load_graph(session, document_id=document_id)
        if not graph.entities:
            raise LookupError(f"文档 {document_id} 无知识图谱数据")
        return {
            "document_id": document_id,
            "entity_network": get_entity_network(graph),
            "evidence_sources": get_evidence_sources(graph),
            "fact_count": len(graph.facts),
            "entity_count": len(graph.entities),
            "relationship_count": len(graph.relationships),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /{document_id}/profile
# ---------------------------------------------------------------------------
@router.get("/api/v1/knowledge-graph/{document_id}/profile")
def get_company_profile_endpoint(
    document_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """查询 Company Profile（公司画像）。"""
    try:
        graph = load_graph(session, document_id=document_id)
        if not graph.entities:
            raise LookupError(f"文档 {document_id} 无知识图谱数据")
        profile = get_company_profile(graph)
        return profile.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /{document_id}/business-map
# ---------------------------------------------------------------------------
@router.get("/api/v1/knowledge-graph/{document_id}/business-map")
def get_business_map_endpoint(
    document_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """查询 Business Map（业务图谱）。"""
    try:
        graph = load_graph(session, document_id=document_id)
        if not graph.entities:
            raise LookupError(f"文档 {document_id} 无知识图谱数据")
        business_map = get_business_map(graph)
        return business_map.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /{document_id}/evidence-sources
# ---------------------------------------------------------------------------
@router.get("/api/v1/knowledge-graph/{document_id}/evidence-sources")
def get_evidence_sources_endpoint(
    document_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """查询 Evidence Sources（证据来源）。"""
    try:
        graph = load_graph(session, document_id=document_id)
        if not graph.entities:
            raise LookupError(f"文档 {document_id} 无知识图谱数据")
        return {"sources": get_evidence_sources(graph)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /conflicts
# ---------------------------------------------------------------------------
@router.post("/api/v1/knowledge-graph/conflicts", status_code=200)
def detect_conflicts_endpoint(
    body: ConflictDetectRequest,
    session: Session = Depends(get_session),
) -> dict:
    """冲突推理：Claim vs Graph Fact。

    输入：document_id（需已构建知识图谱）
    输出：ConflictFindings（含 graph_facts / difference / risk_type / risk_score）
    """
    try:
        graph = load_graph(session, document_id=body.document_id)
        if not graph.entities:
            raise LookupError(f"文档 {body.document_id} 无知识图谱数据")

        # 收集 Claims
        claims, _, _ = _collect_inputs(
            session,
            body.document_id,
            audit_id=None,
            intelligence_report_id=None,
        )

        detection = detect_conflicts(claims, graph)
        overall_score, overall_level = compute_overall_risk(detection.findings)

        return {
            "document_id": body.document_id,
            "findings": [f.to_dict() for f in detection.findings],
            "conflict_count": detection.conflict_count,
            "support_count": detection.support_count,
            "overall_risk_score": overall_score,
            "overall_risk_level": overall_level,
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
