"""Fact Graph Query（Phase 10）：查询知识图谱。

提供查询接口（任务书 §6）：
- get_company_profile    Company Profile（公司画像）
- get_business_map       Business Map（业务图谱）
- get_fact_relationships Fact Relationships（事实追溯）
- get_evidence_sources   Evidence Source（证据来源）

查询基于已构建的 KnowledgeGraph（实体 + 关系 + 事实）。

设计约束（任务书）：
- 不修改已有 Verification 逻辑；
- Knowledge Graph 作为新增层，与已有模块解耦。
"""

from __future__ import annotations

from app.services.knowledge_graph.schemas import (
    ENTITY_BUSINESS,
    ENTITY_COMPANY,
    ENTITY_COMPETITOR,
    ENTITY_EXECUTIVE,
    ENTITY_METRIC,
    ENTITY_PRODUCT,
    ENTITY_REGION,
    BusinessMap,
    CompanyProfile,
    FactRelationships,
    KnowledgeGraph,
)


# ---------------------------------------------------------------------------
# 1. Company Profile（公司画像）
# ---------------------------------------------------------------------------
def get_company_profile(graph: KnowledgeGraph) -> CompanyProfile:
    """从知识图谱聚合公司画像。

    聚合：
    - businesses        HAS_BUSINESS 关系的业务实体
    - products          OWNS 关系的产品实体
    - regions           LOCATED_IN 关系的地区实体
    - competitors       COMPETES_WITH 关系的竞争对手实体
    - executives        EXECUTIVE 类型实体
    - metrics           METRIC 类型实体 + HAS_METRIC 关联事实
    """
    # 找到公司实体
    company_entity = None
    for e in graph.entities:
        if e.entity_type == ENTITY_COMPANY:
            company_entity = e
            break

    if company_entity is None:
        return CompanyProfile()

    company_id = company_entity.entity_id

    # 关系索引
    relationships_from_company = [
        r for r in graph.relationships if r.source_entity_id == company_id
    ]

    # 实体索引
    entities_by_id = {e.entity_id: e for e in graph.entities}

    # 聚合各类实体
    businesses: list[str] = []
    products: list[str] = []
    regions: list[str] = []
    competitors: list[str] = []
    executives: list[str] = []
    metrics: list[dict] = []

    for rel in relationships_from_company:
        target = entities_by_id.get(rel.target_entity_id)
        if target is None:
            continue
        if rel.relationship_type == "HAS_BUSINESS":
            businesses.append(target.name)
        elif rel.relationship_type == "OWNS":
            products.append(target.name)
        elif rel.relationship_type == "COMPETES_WITH":
            competitors.append(target.name)
        elif rel.relationship_type == "LOCATED_IN":
            regions.append(target.name)

    # 高管/指标实体
    for e in graph.entities:
        if e.entity_type == ENTITY_EXECUTIVE:
            executives.append(e.name)
        elif e.entity_type == ENTITY_METRIC:
            metrics.append({"name": e.name, "entity_id": e.entity_id})

    # HAS_METRIC 关联的事实
    metric_facts: list[dict] = []
    for rel in graph.relationships:
        if rel.relationship_type != "HAS_METRIC":
            continue
        # 找到关联的事实
        for f in graph.facts:
            if f.fact_id == rel.fact_id:
                metric_facts.append(
                    {
                        "fact_id": f.fact_id,
                        "predicate": f.predicate,
                        "object_value": f.object_value,
                        "unit": f.unit,
                        "period": f.period,
                        "source": f.source,
                        "source_label": f.source_label,
                        "evidence": f.evidence,
                        "timestamp": f.timestamp,
                        "confidence": f.confidence,
                    }
                )
                break

    return CompanyProfile(
        company=company_entity.name,
        stock_code=company_entity.metadata.get("stock_code", ""),
        report_period=company_entity.metadata.get("report_period", ""),
        businesses=businesses,
        products=products,
        regions=regions,
        competitors=competitors,
        executives=executives,
        metrics=metric_facts if metric_facts else metrics,
    )


# ---------------------------------------------------------------------------
# 2. Business Map（业务图谱）
# ---------------------------------------------------------------------------
def get_business_map(graph: KnowledgeGraph) -> BusinessMap:
    """构建业务图谱：公司 → 业务分部 → 产品/地区/指标。

    每条 business_segment:
    {
        "business": str,           # 业务名称
        "business_id": str,        # 业务实体 ID
        "products": list[str],     # 业务下的产品
        "regions": list[str],      # 业务覆盖地区
        "metrics": list[dict],     # 业务指标事实
    }
    """
    # 找到公司实体
    company_entity = None
    for e in graph.entities:
        if e.entity_type == ENTITY_COMPANY:
            company_entity = e
            break

    if company_entity is None:
        return BusinessMap()

    company_id = company_entity.entity_id
    entities_by_id = {e.entity_id: e for e in graph.entities}

    # 业务分部：HAS_BUSINESS 关系
    business_segments: list[dict] = []
    business_rels = [
        r for r in graph.relationships
        if r.source_entity_id == company_id and r.relationship_type == "HAS_BUSINESS"
    ]

    for rel in business_rels:
        business_entity = entities_by_id.get(rel.target_entity_id)
        if business_entity is None:
            continue

        business_id = business_entity.entity_id

        # 该业务下的产品（OWNS 关系，简化：所有产品）
        products: list[str] = []
        for p_rel in graph.relationships:
            if (
                p_rel.relationship_type == "OWNS"
                and p_rel.source_entity_id == company_id
            ):
                product_entity = entities_by_id.get(p_rel.target_entity_id)
                if product_entity:
                    products.append(product_entity.name)

        # 该业务覆盖的地区（LOCATED_IN 关系）
        regions: list[str] = []
        for loc_rel in graph.relationships:
            if (
                loc_rel.relationship_type == "LOCATED_IN"
                and loc_rel.source_entity_id == business_id
            ):
                region_entity = entities_by_id.get(loc_rel.target_entity_id)
                if region_entity:
                    regions.append(region_entity.name)

        # 该业务的指标事实（HAS_METRIC 关系）
        metrics: list[dict] = []
        for m_rel in graph.relationships:
            if (
                m_rel.relationship_type == "HAS_METRIC"
                and m_rel.source_entity_id == business_id
            ):
                for f in graph.facts:
                    if f.fact_id == m_rel.fact_id:
                        metrics.append(
                            {
                                "fact_id": f.fact_id,
                                "predicate": f.predicate,
                                "object_value": f.object_value,
                                "unit": f.unit,
                                "period": f.period,
                                "source": f.source,
                                "source_label": f.source_label,
                                "evidence": f.evidence,
                                "timestamp": f.timestamp,
                                "confidence": f.confidence,
                            }
                        )
                        break

        business_segments.append(
            {
                "business": business_entity.name,
                "business_id": business_id,
                "products": products,
                "regions": regions,
                "metrics": metrics,
            }
        )

    return BusinessMap(
        company=company_entity.name,
        business_segments=business_segments,
    )


# ---------------------------------------------------------------------------
# 3. Fact Relationships（事实追溯）
# ---------------------------------------------------------------------------
def get_fact_relationships(graph: KnowledgeGraph, fact_id: str) -> FactRelationships:
    """查询指定事实的实体、关系与证据追溯。

    返回：
    - fact              事实详情（含 source/evidence/confidence/timestamp）
    - subject_entity    事实主体实体
    - related_entities  与该事实关联的实体
    - relationships     关联的关系（SUPPORTED_BY / HAS_METRIC）
    """
    target_fact = None
    for f in graph.facts:
        if f.fact_id == fact_id:
            target_fact = f
            break

    if target_fact is None:
        return FactRelationships()

    # 主体实体
    subject_entity = None
    for e in graph.entities:
        if e.entity_id == target_fact.subject_entity_id:
            subject_entity = e
            break

    # 关联关系
    related_rels = [
        r for r in graph.relationships
        if r.fact_id == fact_id
        or r.source_entity_id == target_fact.subject_entity_id
        or r.target_entity_id == target_fact.subject_entity_id
    ]

    # 关联实体
    related_entity_ids: set[str] = set()
    for r in related_rels:
        related_entity_ids.add(r.source_entity_id)
        related_entity_ids.add(r.target_entity_id)
    related_entity_ids.discard(target_fact.subject_entity_id)

    related_entities = []
    entities_by_id = {e.entity_id: e for e in graph.entities}
    for eid in related_entity_ids:
        entity = entities_by_id.get(eid)
        if entity:
            related_entities.append(entity.to_dict())

    return FactRelationships(
        fact_id=fact_id,
        fact=target_fact.to_dict(),
        subject_entity=subject_entity.to_dict() if subject_entity else {},
        related_entities=related_entities,
        relationships=[r.to_dict() for r in related_rels],
    )


# ---------------------------------------------------------------------------
# 4. Evidence Sources（证据来源）
# ---------------------------------------------------------------------------
def get_evidence_sources(graph: KnowledgeGraph) -> list[dict]:
    """汇总知识图谱中的证据来源。

    返回：
    [
        {
            "source": str,           # 来源类型
            "source_label": str,     # 来源标签
            "fact_count": int,       # 该来源的事实数
            "facts": list[dict],     # 该来源的事实列表
        },
        ...
    ]
    """
    source_map: dict[str, dict] = {}

    for f in graph.facts:
        source_key = f.source or "UNKNOWN"
        if source_key not in source_map:
            source_map[source_key] = {
                "source": source_key,
                "source_label": f.source_label or source_key,
                "fact_count": 0,
                "facts": [],
            }
        source_map[source_key]["fact_count"] += 1
        source_map[source_key]["facts"].append(
            {
                "fact_id": f.fact_id,
                "predicate": f.predicate,
                "object_value": f.object_value,
                "unit": f.unit,
                "period": f.period,
                "evidence": f.evidence,
                "timestamp": f.timestamp,
                "confidence": f.confidence,
            }
        )

    return list(source_map.values())


# ---------------------------------------------------------------------------
# 5. Entity Network（实体网络，供前端可视化）
# ---------------------------------------------------------------------------
def get_entity_network(graph: KnowledgeGraph) -> dict:
    """返回实体网络结构（nodes + edges）供前端可视化。

    nodes: [{id, type, name, label}]
    edges: [{source, target, type, label, fact_id, confidence}]
    """
    nodes: list[dict] = []
    for e in graph.entities:
        from app.services.knowledge_graph.schemas import ENTITY_LABELS

        nodes.append(
            {
                "id": e.entity_id,
                "type": e.entity_type,
                "name": e.name,
                "label": ENTITY_LABELS.get(e.entity_type, e.entity_type),
            }
        )

    edges: list[dict] = []
    from app.services.knowledge_graph.schemas import RELATIONSHIP_LABELS

    for r in graph.relationships:
        edges.append(
            {
                "source": r.source_entity_id,
                "target": r.target_entity_id,
                "type": r.relationship_type,
                "label": RELATIONSHIP_LABELS.get(r.relationship_type, r.relationship_type),
                "fact_id": r.fact_id,
                "confidence": r.confidence,
            }
        )

    return {"nodes": nodes, "edges": edges}


__all__ = [
    "get_company_profile",
    "get_business_map",
    "get_fact_relationships",
    "get_evidence_sources",
    "get_entity_network",
]
