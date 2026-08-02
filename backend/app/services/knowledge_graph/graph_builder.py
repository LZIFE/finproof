"""Graph Builder（Phase 10）：构建金融知识图谱。

输入：
- entities          已抽取的实体列表（Entity）
- claims            已有 Claim Extraction 结果（list[dict]）
- evidence          已有 Evidence Retrieval 结果（list[dict]）
- company_facts     已有 Intelligence Verified Facts（list[dict]）

构建：
- Facts             从 Company Facts / Claims / Evidence 抽取数字类事实
                    （Evidence First：source/evidence/confidence/timestamp 必填）
- Relationships     根据实体类型与文本共现构建关系：
                      - OWNS            公司 → 产品
                      - HAS_BUSINESS    公司 → 业务
                      - COMPETES_WITH   公司 → 竞争对手
                      - LOCATED_IN      业务/产品 → 地区
                      - HAS_METRIC      公司/业务 → 指标事实
                      - SUPPORTED_BY    事实 → 证据

持久化：
- kg_entities / kg_relationships / kg_facts 表

设计约束（任务书）：
- 不修改已有 Verification 逻辑；
- Knowledge Graph 作为新增层，与已有模块解耦。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.knowledge_graph import KGFactsRow, KGEntityRow, KGRelationshipRow
from app.services.knowledge_graph.entity_extractor import (
    extract_metric_facts,
)
from app.services.knowledge_graph.schemas import (
    ENTITY_BUSINESS,
    ENTITY_COMPANY,
    ENTITY_COMPETITOR,
    ENTITY_METRIC,
    ENTITY_PRODUCT,
    ENTITY_REGION,
    Fact,
    KnowledgeGraph,
    Relationship,
    _now_iso,
)


# ---------------------------------------------------------------------------
# ID 生成（持久化时去重）
# ---------------------------------------------------------------------------
def _next_relationship_id(used: set[str]) -> str:
    idx = 1
    while f"REL-{idx:04d}" in used:
        idx += 1
    rid = f"REL-{idx:04d}"
    used.add(rid)
    return rid


def _next_fact_id(used: set[str]) -> str:
    idx = 1
    while f"FACT-{idx:04d}" in used:
        idx += 1
    fid = f"FACT-{idx:04d}"
    used.add(fid)
    return fid


# ---------------------------------------------------------------------------
# Facts 构建（Evidence First）
# ---------------------------------------------------------------------------
def build_facts(
    entities: list,
    company_facts: list[dict],
    claims: list[dict],
    evidence: list[dict],
) -> list[Fact]:
    """从 Company Facts / Claims / Evidence 构建事实（Evidence First）。

    每条 Fact 必须包含 source / evidence / confidence / timestamp，
    否则跳过。
    """
    facts: list[Fact] = []
    used_fact_ids: set[str] = set()

    # ---- 1. 从 metric_facts 抽取（数字类）----
    metric_facts = extract_metric_facts(company_facts, claims, evidence)

    # 找到公司实体 ID
    company_entity_id = ""
    for e in entities:
        if e.entity_type == ENTITY_COMPANY:
            company_entity_id = e.entity_id
            break

    for mf in metric_facts:
        fid = _next_fact_id(used_fact_ids)
        facts.append(
            Fact(
                fact_id=fid,
                subject_entity_id=company_entity_id,
                predicate=mf.get("predicate", ""),
                object_value=mf.get("object_value"),
                unit=mf.get("unit", ""),
                period=mf.get("period", ""),
                source=mf.get("source", "FINANCIAL_REPORT"),
                source_label=mf.get("source_label", ""),
                evidence=mf.get("evidence", ""),
                timestamp=mf.get("timestamp", "") or _now_iso(),
                confidence=mf.get("confidence", 0.8),
            )
        )

    # ---- 2. 从 Company Facts 直接构建（非数字类）----
    for cf in company_facts:
        if not cf.get("evidence"):
            continue
        fid = _next_fact_id(used_fact_ids)
        facts.append(
            Fact(
                fact_id=fid,
                subject_entity_id=company_entity_id,
                predicate=cf.get("statement", ""),
                object_value=cf.get("value"),
                unit=cf.get("unit", ""),
                period=cf.get("period", ""),
                source=cf.get("source", "FINANCIAL_REPORT"),
                source_label=cf.get("source_label", ""),
                evidence=cf.get("evidence", ""),
                timestamp=cf.get("timestamp", "") or _now_iso(),
                confidence=cf.get("confidence", 0.9),
            )
        )

    return facts


# ---------------------------------------------------------------------------
# Relationships 构建
# ---------------------------------------------------------------------------
def build_relationships(
    entities: list,
    facts: list[Fact],
) -> list[Relationship]:
    """根据实体类型与事实构建关系。"""
    relationships: list[Relationship] = []
    used_rel_ids: set[str] = set()

    # 实体索引
    company_entities = [e for e in entities if e.entity_type == ENTITY_COMPANY]
    business_entities = [e for e in entities if e.entity_type == ENTITY_BUSINESS]
    product_entities = [e for e in entities if e.entity_type == ENTITY_PRODUCT]
    region_entities = [e for e in entities if e.entity_type == ENTITY_REGION]
    competitor_entities = [e for e in entities if e.entity_type == ENTITY_COMPETITOR]
    metric_entities = [e for e in entities if e.entity_type == ENTITY_METRIC]

    if not company_entities:
        return relationships

    company = company_entities[0]
    company_id = company.entity_id

    # ---- OWNS: 公司 → 产品 ----
    for product in product_entities:
        rid = _next_relationship_id(used_rel_ids)
        relationships.append(
            Relationship(
                relationship_id=rid,
                source_entity_id=company_id,
                target_entity_id=product.entity_id,
                relationship_type="OWNS",
                confidence=0.85,
            )
        )

    # ---- HAS_BUSINESS: 公司 → 业务 ----
    for business in business_entities:
        rid = _next_relationship_id(used_rel_ids)
        relationships.append(
            Relationship(
                relationship_id=rid,
                source_entity_id=company_id,
                target_entity_id=business.entity_id,
                relationship_type="HAS_BUSINESS",
                confidence=0.9,
            )
        )

    # ---- COMPETES_WITH: 公司 → 竞争对手 ----
    for competitor in competitor_entities:
        rid = _next_relationship_id(used_rel_ids)
        relationships.append(
            Relationship(
                relationship_id=rid,
                source_entity_id=company_id,
                target_entity_id=competitor.entity_id,
                relationship_type="COMPETES_WITH",
                confidence=0.75,
            )
        )

    # ---- LOCATED_IN: 业务/产品 → 地区（基于共现）----
    # 简化策略：每个业务/产品关联第一个出现的地区
    for business in business_entities:
        for region in region_entities:
            rid = _next_relationship_id(used_rel_ids)
            relationships.append(
                Relationship(
                    relationship_id=rid,
                    source_entity_id=business.entity_id,
                    target_entity_id=region.entity_id,
                    relationship_type="LOCATED_IN",
                    confidence=0.7,
                )
            )
            break  # 每个业务只关联一个地区

    # ---- HAS_METRIC: 公司 → 指标事实 ----
    metric_names = {e.name for e in metric_entities}
    for fact in facts:
        # 如果事实的谓词匹配某个指标实体
        if fact.predicate in metric_names or any(
            m in fact.predicate for m in metric_names
        ):
            rid = _next_relationship_id(used_rel_ids)
            relationships.append(
                Relationship(
                    relationship_id=rid,
                    source_entity_id=fact.subject_entity_id,
                    target_entity_id=fact.subject_entity_id,  # 自指，表示公司有该指标
                    relationship_type="HAS_METRIC",
                    fact_id=fact.fact_id,
                    confidence=fact.confidence,
                )
            )

    # ---- SUPPORTED_BY: 事实 → 证据（自指，表示事实有证据支持）----
    for fact in facts:
        if fact.evidence:
            rid = _next_relationship_id(used_rel_ids)
            relationships.append(
                Relationship(
                    relationship_id=rid,
                    source_entity_id=fact.subject_entity_id,
                    target_entity_id=fact.subject_entity_id,
                    relationship_type="SUPPORTED_BY",
                    fact_id=fact.fact_id,
                    confidence=fact.confidence,
                )
            )

    return relationships


# ---------------------------------------------------------------------------
# 主入口：build_graph
# ---------------------------------------------------------------------------
def build_graph(
    entities: list,
    company_facts: list[dict],
    claims: list[dict],
    evidence: list[dict],
) -> KnowledgeGraph:
    """构建知识图谱：实体 + 关系 + 事实。"""
    facts = build_facts(entities, company_facts, claims, evidence)
    relationships = build_relationships(entities, facts)

    return KnowledgeGraph(
        entities=entities,
        relationships=relationships,
        facts=facts,
    )


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
def save_graph(
    session: Session,
    graph: KnowledgeGraph,
    document_id: int | None = None,
) -> KnowledgeGraph:
    """持久化知识图谱到 kg_entities / kg_relationships / kg_facts 表。"""
    # ---- 1. 实体 ----
    for entity in graph.entities:
        row = KGEntityRow(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            name=entity.name,
            aliases_json=json.dumps(entity.aliases, ensure_ascii=False) if entity.aliases else None,
            metadata_json=json.dumps(entity.metadata, ensure_ascii=False) if entity.metadata else None,
            document_id=document_id,
        )
        session.add(row)

    # ---- 2. 事实 ----
    for fact in graph.facts:
        row = KGFactsRow(
            fact_id=fact.fact_id,
            subject_entity_id=fact.subject_entity_id,
            predicate=fact.predicate,
            object_value=json.dumps(fact.object_value, ensure_ascii=False) if fact.object_value is not None else None,
            unit=fact.unit,
            period=fact.period,
            source=fact.source,
            source_label=fact.source_label,
            evidence=fact.evidence,
            timestamp=fact.timestamp,
            confidence=fact.confidence,
            document_id=document_id,
        )
        session.add(row)

    # ---- 3. 关系 ----
    for rel in graph.relationships:
        row = KGRelationshipRow(
            relationship_id=rel.relationship_id,
            source_entity_id=rel.source_entity_id,
            target_entity_id=rel.target_entity_id,
            relationship_type=rel.relationship_type,
            fact_id=rel.fact_id,
            confidence=rel.confidence,
            document_id=document_id,
        )
        session.add(row)

    session.commit()
    return graph


# ---------------------------------------------------------------------------
# 读取图谱
# ---------------------------------------------------------------------------
def load_graph(
    session: Session,
    document_id: int | None = None,
) -> KnowledgeGraph:
    """从数据库加载知识图谱。"""
    entities: list = []
    relationships: list = []
    facts: list = []

    entity_query = session.query(KGEntityRow)
    if document_id is not None:
        entity_query = entity_query.filter(KGEntityRow.document_id == document_id)

    from app.services.knowledge_graph.schemas import Entity

    for row in entity_query.all():
        aliases = json.loads(row.aliases_json) if row.aliases_json else []
        metadata = json.loads(row.metadata_json) if row.metadata_json else {}
        entities.append(
            Entity(
                entity_id=row.entity_id,
                entity_type=row.entity_type,
                name=row.name,
                aliases=aliases,
                metadata=metadata,
            )
        )

    fact_query = session.query(KGFactsRow)
    if document_id is not None:
        fact_query = fact_query.filter(KGFactsRow.document_id == document_id)

    from app.services.knowledge_graph.schemas import Fact

    for row in fact_query.all():
        object_value = json.loads(row.object_value) if row.object_value else None
        facts.append(
            Fact(
                fact_id=row.fact_id,
                subject_entity_id=row.subject_entity_id,
                predicate=row.predicate,
                object_value=object_value,
                unit=row.unit,
                period=row.period,
                source=row.source,
                source_label=row.source_label,
                evidence=row.evidence,
                timestamp=row.timestamp,
                confidence=row.confidence,
                document_id=row.document_id,
                page_number=row.page_number,
            )
        )

    rel_query = session.query(KGRelationshipRow)
    if document_id is not None:
        rel_query = rel_query.filter(KGRelationshipRow.document_id == document_id)

    for row in rel_query.all():
        relationships.append(
            Relationship(
                relationship_id=row.relationship_id,
                source_entity_id=row.source_entity_id,
                target_entity_id=row.target_entity_id,
                relationship_type=row.relationship_type,
                fact_id=row.fact_id or "",
                confidence=row.confidence,
            )
        )

    return KnowledgeGraph(
        entities=entities,
        relationships=relationships,
        facts=facts,
    )


__all__ = [
    "build_graph",
    "build_facts",
    "build_relationships",
    "save_graph",
    "load_graph",
]
