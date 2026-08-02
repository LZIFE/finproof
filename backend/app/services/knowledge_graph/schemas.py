"""Financial Knowledge Graph Schemas（Phase 10）。

金融知识图谱层：提高金融事实关联和冲突发现能力。

数据结构：
- Entity            图谱节点（Company/Business/Product/Region/Competitor/Metric/Executive）
- Relationship      图谱边（OWNS/HAS_BUSINESS/COMPETES_WITH/LOCATED_IN/HAS_METRIC/SUPPORTED_BY）
- Fact              图谱事实（source/evidence/confidence/timestamp 必填）
- ConflictFinding   冲突推理结论（claim/graph_facts/difference/risk_type/risk_score）

Evidence First：每个 Fact 必须包含 source / evidence / confidence / timestamp，
不凭空捏造事实。

设计约束（任务书）：
- 不修改已有 Verification 逻辑；
- Knowledge Graph 作为新增层，与已有模块解耦。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Entity 类型（任务书 §2）
# ---------------------------------------------------------------------------
ENTITY_COMPANY = "COMPANY"
ENTITY_BUSINESS = "BUSINESS"
ENTITY_PRODUCT = "PRODUCT"
ENTITY_REGION = "REGION"
ENTITY_COMPETITOR = "COMPETITOR"
ENTITY_METRIC = "METRIC"
ENTITY_EXECUTIVE = "EXECUTIVE"

ENTITY_TYPES = {
    ENTITY_COMPANY,
    ENTITY_BUSINESS,
    ENTITY_PRODUCT,
    ENTITY_REGION,
    ENTITY_COMPETITOR,
    ENTITY_METRIC,
    ENTITY_EXECUTIVE,
}

ENTITY_LABELS = {
    ENTITY_COMPANY: "公司",
    ENTITY_BUSINESS: "业务",
    ENTITY_PRODUCT: "产品",
    ENTITY_REGION: "地区",
    ENTITY_COMPETITOR: "竞争对手",
    ENTITY_METRIC: "财务指标",
    ENTITY_EXECUTIVE: "高管",
}

# ---------------------------------------------------------------------------
# Relationship 类型（任务书 §4）
# ---------------------------------------------------------------------------
REL_OWNS = "OWNS"  # 公司拥有产品/业务
REL_HAS_BUSINESS = "HAS_BUSINESS"  # 公司有业务分部
REL_COMPETES_WITH = "COMPETES_WITH"  # 竞争关系
REL_LOCATED_IN = "LOCATED_IN"  # 业务/产品位于地区
REL_HAS_METRIC = "HAS_METRIC"  # 公司/业务有财务指标
REL_SUPPORTED_BY = "SUPPORTED_BY"  # 事实被证据支持

RELATIONSHIP_TYPES = {
    REL_OWNS,
    REL_HAS_BUSINESS,
    REL_COMPETES_WITH,
    REL_LOCATED_IN,
    REL_HAS_METRIC,
    REL_SUPPORTED_BY,
}

RELATIONSHIP_LABELS = {
    REL_OWNS: "拥有",
    REL_HAS_BUSINESS: "业务分部",
    REL_COMPETES_WITH: "竞争",
    REL_LOCATED_IN: "位于",
    REL_HAS_METRIC: "指标",
    REL_SUPPORTED_BY: "证据支持",
}

# ---------------------------------------------------------------------------
# Conflict Reasoning 类型（任务书 §5）
# ---------------------------------------------------------------------------
CONFLICT_CLAIM_VS_FACT = "CLAIM_VS_FACT"  # Claim 与 Fact 冲突
CONFLICT_BUSINESS_OVERSTATEMENT = "BUSINESS_OVERSTATEMENT"  # Business 描述夸大
CONFLICT_COMPETITIVE_NO_EVIDENCE = "COMPETITIVE_NO_EVIDENCE"  # Competitive 优势缺证据
CONFLICT_GROWTH_INSUFFICIENT = "GROWTH_INSUFFICIENT"  # Growth 逻辑不足
CONFLICT_NO_OPPOSITION = "NO_OPPOSITION"  # 无冲突/支持

CONFLICT_TYPES = {
    CONFLICT_CLAIM_VS_FACT,
    CONFLICT_BUSINESS_OVERSTATEMENT,
    CONFLICT_COMPETITIVE_NO_EVIDENCE,
    CONFLICT_GROWTH_INSUFFICIENT,
    CONFLICT_NO_OPPOSITION,
}

# 冲突类型 → 默认风险分数
CONFLICT_BASE_SCORE = {
    CONFLICT_CLAIM_VS_FACT: 85.0,
    CONFLICT_BUSINESS_OVERSTATEMENT: 70.0,
    CONFLICT_COMPETITIVE_NO_EVIDENCE: 55.0,
    CONFLICT_GROWTH_INSUFFICIENT: 60.0,
    CONFLICT_NO_OPPOSITION: 0.0,
}

# 冲突类型 → 风险类型（与 Phase 6/7/8 口径一致）
CONFLICT_RISK_TYPE = {
    CONFLICT_CLAIM_VS_FACT: "FINANCIAL_ERROR",
    CONFLICT_BUSINESS_OVERSTATEMENT: "SEMANTIC_RISK",
    CONFLICT_COMPETITIVE_NO_EVIDENCE: "EVIDENCE_RISK",
    CONFLICT_GROWTH_INSUFFICIENT: "EVIDENCE_RISK",
    CONFLICT_NO_OPPOSITION: "NONE",
}


# ---------------------------------------------------------------------------
# Entity：图谱节点
# ---------------------------------------------------------------------------
@dataclass
class Entity:
    """图谱节点：金融实体。"""

    entity_id: str  # ENT-XXXXX
    entity_type: str  # ENTITY_TYPES
    name: str  # 实体名称
    aliases: list[str] = field(default_factory=list)  # 别名（用于实体消歧）
    metadata: dict = field(default_factory=dict)  # 额外属性

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "aliases": self.aliases,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Relationship：图谱边
# ---------------------------------------------------------------------------
@dataclass
class Relationship:
    """图谱边：实体间关系。"""

    relationship_id: str  # REL-XXXXX
    source_entity_id: str  # 起点实体
    target_entity_id: str  # 终点实体
    relationship_type: str  # RELATIONSHIP_TYPES
    fact_id: str = ""  # 关联的事实 ID（Evidence First）
    confidence: float = 0.0  # 0-1
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "relationship_id": self.relationship_id,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "relationship_type": self.relationship_type,
            "fact_id": self.fact_id,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Fact：图谱事实（Evidence First）
# ---------------------------------------------------------------------------
@dataclass
class Fact:
    """图谱事实：可追溯的金融事实。

    Evidence First：source / evidence / confidence / timestamp 必填，
    无证据不记录事实。
    """

    fact_id: str  # FACT-XXXXX
    subject_entity_id: str  # 事实主体实体
    predicate: str  # 谓词（如"营业收入"、"海外业务"）
    object_value: Any = None  # 客体值（数值/文本）
    unit: str = ""  # 单位（亿元 / % / ...）
    period: str = ""  # 口径期间（2025FY / 2025Q1 / ...）

    # Evidence First 字段
    source: str = ""  # 来源类型（FINANCIAL_REPORT/ANNOUNCEMENT/NEWS/OFFICIAL_SITE/CLAIM/EVIDENCE）
    source_label: str = ""  # 人类可读来源名
    evidence: str = ""  # 原始证据文本/摘要
    timestamp: str = ""  # 事实发生/披露时间 ISO8601
    confidence: float = 0.0  # 0-1，证据可信度
    document_id: int | None = None  # 关联文档
    page_number: int | None = None  # 财报页码（可选）

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "subject_entity_id": self.subject_entity_id,
            "predicate": self.predicate,
            "object_value": self.object_value,
            "unit": self.unit,
            "period": self.period,
            "source": self.source,
            "source_label": self.source_label,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "document_id": self.document_id,
            "page_number": self.page_number,
        }


# ---------------------------------------------------------------------------
# Knowledge Graph：实体 + 关系 + 事实的聚合视图
# ---------------------------------------------------------------------------
@dataclass
class KnowledgeGraph:
    """知识图谱：实体 + 关系 + 事实的聚合视图。"""

    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "relationships": [r.to_dict() for r in self.relationships],
            "facts": [f.to_dict() for f in self.facts],
            "entity_count": len(self.entities),
            "relationship_count": len(self.relationships),
            "fact_count": len(self.facts),
        }


# ---------------------------------------------------------------------------
# ConflictFinding：冲突推理结论（任务书 §5）
# ---------------------------------------------------------------------------
@dataclass
class ConflictFinding:
    """冲突推理结论。

    结构遵循任务书 §5：
    claim / graph_facts / difference / risk_type / risk_score
    """

    finding_id: str  # CFLT-XXXXX
    claim_id: str  # 关联的 Claim ID
    claim: str  # Claim 原文
    conflict_type: str  # CONFLICT_TYPES
    graph_facts: list[dict] = field(default_factory=list)  # 相关图谱事实（含证据）
    difference: str = ""  # 差异描述（人类可读）
    risk_type: str = ""  # 风险类型
    risk_score: float = 0.0  # 0-100
    risk_level: str = "LOW"  # LOW/MEDIUM/HIGH
    evidence_trace: list[dict] = field(default_factory=list)  # 证据链

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "claim_id": self.claim_id,
            "claim": self.claim,
            "conflict_type": self.conflict_type,
            "graph_facts": self.graph_facts,
            "difference": self.difference,
            "risk_type": self.risk_type,
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "evidence_trace": self.evidence_trace,
        }


# ---------------------------------------------------------------------------
# Company Profile / Business Map / Fact Relationships（任务书 §6）
# ---------------------------------------------------------------------------
@dataclass
class CompanyProfile:
    """公司画像：从知识图谱聚合。"""

    company: str = ""
    stock_code: str = ""
    report_period: str = ""
    businesses: list[str] = field(default_factory=list)  # 业务分部
    products: list[str] = field(default_factory=list)  # 产品
    regions: list[str] = field(default_factory=list)  # 地区
    competitors: list[str] = field(default_factory=list)  # 竞争对手
    executives: list[str] = field(default_factory=list)  # 高管
    metrics: list[dict] = field(default_factory=list)  # 财务指标

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "stock_code": self.stock_code,
            "report_period": self.report_period,
            "businesses": self.businesses,
            "products": self.products,
            "regions": self.regions,
            "competitors": self.competitors,
            "executives": self.executives,
            "metrics": self.metrics,
        }


@dataclass
class BusinessMap:
    """业务图谱：公司 → 业务 → 产品/地区/指标 的关系视图。"""

    company: str = ""
    business_segments: list[dict] = field(default_factory=list)
    # 每条 business_segment: {business, products[], regions[], metrics[]}

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "business_segments": self.business_segments,
        }


@dataclass
class FactRelationships:
    """事实关系：Fact → Entity → Relationship 的追溯视图。"""

    fact_id: str = ""
    fact: dict = field(default_factory=dict)
    subject_entity: dict = field(default_factory=dict)
    related_entities: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "fact": self.fact,
            "subject_entity": self.subject_entity,
            "related_entities": self.related_entities,
            "relationships": self.relationships,
        }


# ---------------------------------------------------------------------------
# 风险分数 → Level（与 Phase 6/7/8/9 阈值一致：LOW<30 / MEDIUM≤65 / HIGH>65）
# ---------------------------------------------------------------------------
def risk_level_of(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 65.0:
        return "MEDIUM"
    return "HIGH"


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


__all__ = [
    # Entity 类型
    "ENTITY_COMPANY",
    "ENTITY_BUSINESS",
    "ENTITY_PRODUCT",
    "ENTITY_REGION",
    "ENTITY_COMPETITOR",
    "ENTITY_METRIC",
    "ENTITY_EXECUTIVE",
    "ENTITY_TYPES",
    "ENTITY_LABELS",
    # Relationship 类型
    "REL_OWNS",
    "REL_HAS_BUSINESS",
    "REL_COMPETES_WITH",
    "REL_LOCATED_IN",
    "REL_HAS_METRIC",
    "REL_SUPPORTED_BY",
    "RELATIONSHIP_TYPES",
    "RELATIONSHIP_LABELS",
    # Conflict 类型
    "CONFLICT_CLAIM_VS_FACT",
    "CONFLICT_BUSINESS_OVERSTATEMENT",
    "CONFLICT_COMPETITIVE_NO_EVIDENCE",
    "CONFLICT_GROWTH_INSUFFICIENT",
    "CONFLICT_NO_OPPOSITION",
    "CONFLICT_TYPES",
    "CONFLICT_BASE_SCORE",
    "CONFLICT_RISK_TYPE",
    # 数据类
    "Entity",
    "Relationship",
    "Fact",
    "KnowledgeGraph",
    "ConflictFinding",
    "CompanyProfile",
    "BusinessMap",
    "FactRelationships",
    # 工具
    "risk_level_of",
    "_now_iso",
]
