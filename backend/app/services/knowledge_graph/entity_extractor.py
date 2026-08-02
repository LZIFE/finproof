"""Entity Extractor（Phase 10）：从 Claims/Evidence/Company Facts 抽取金融实体。

抽取实体类型（任务书 §2）：
- Company        公司
- Business       业务
- Product        产品
- Region         地区
- Competitor     竞争对手
- Metric         财务指标
- Executive      高管

Evidence First：抽取的实体来自已有 Claims/Evidence/Company Facts，
不引入未核验的信息。每个实体可关联 Fact（含 source/evidence/confidence/timestamp）。

输入源：
- claims          已有 Claim Extraction 结果（list[dict]）
- evidence        已有 Evidence Retrieval 结果（list[dict]）
- company_facts   已有 Intelligence Verified Facts（list[dict]）

设计约束（任务书）：
- 不修改已有 Verification 逻辑；
- Knowledge Graph 作为新增层，与已有模块解耦。
"""

from __future__ import annotations

import re
from typing import Iterable

from app.services.knowledge_graph.schemas import (
    ENTITY_BUSINESS,
    ENTITY_COMPANY,
    ENTITY_COMPETITOR,
    ENTITY_EXECUTIVE,
    ENTITY_METRIC,
    ENTITY_PRODUCT,
    ENTITY_REGION,
    Entity,
)

# ---------------------------------------------------------------------------
# 实体词典（按优先级排列；匹配时去重）
# ---------------------------------------------------------------------------
# 公司：美的集团（演示）
_COMPANY_KW = ["美的集团", "美的"]

# 业务分部
_BUSINESS_KW = ["暖通空调", "消费电器", "机器人与自动化", "智能建筑科技", "新能源及工业技术"]

# 产品
_PRODUCT_KW = ["空调", "冰箱", "洗衣机", "COLMO", "东芝", "KUKA", "库卡", "压缩机", "微波炉"]

# 地区
_REGION_KW = ["海外", "境外", "北美", "欧洲", "东南亚", "中国", "OBM", "Midea"]

# 竞争对手
_COMPETITOR_KW = ["海尔", "格力", "海信", "西门子", "三星", "LG", "惠而浦"]

# 财务指标
_METRIC_KW = ["营业收入", "营业总收入", "净利润", "归母净利润", "毛利率", "经营性现金流"]

# 高管
_EXECUTIVE_KW = ["方洪波", "董事长", "总裁", "CEO"]

# 数字抽取正则：匹配 "营业收入 4,564.52 亿元"
_NUMBER_PATTERN = re.compile(
    r"(?P<metric>[^\s，。、：]{2,12}?)"
    r"\s*[为达约共]?\s*(?P<value>\d[\d,]*\.?\d*)\s*"
    r"(?P<unit>亿元|万元|元|%)"
)


# ---------------------------------------------------------------------------
# 实体 ID 生成（去重）
# ---------------------------------------------------------------------------
def _entity_id_seq(existing: Iterable[str], prefix: str) -> int:
    used = {x for x in existing}
    idx = 1
    while f"{prefix}-{idx:04d}" in used:
        idx += 1
    return idx


def _make_entity(
    existing_ids: list[str],
    entity_type: str,
    name: str,
    aliases: list[str] | None = None,
    metadata: dict | None = None,
) -> Entity:
    """创建实体并分配 ID（ENT-XXXXX）。"""
    prefix = "ENT"
    idx = _entity_id_seq(existing_ids, prefix)
    eid = f"{prefix}-{idx:04d}"
    existing_ids.append(eid)
    return Entity(
        entity_id=eid,
        entity_type=entity_type,
        name=name,
        aliases=aliases or [],
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 关键词匹配抽取
# ---------------------------------------------------------------------------
def _extract_by_keywords(
    text: str,
    keywords: list[str],
    entity_type: str,
    existing_ids: list[str],
    existing_names: dict[str, str],  # name → entity_id（去重）
) -> list[Entity]:
    """从文本按关键词抽取实体（同名去重）。"""
    out: list[Entity] = []
    for kw in keywords:
        if kw not in text:
            continue
        if kw in existing_names:
            continue  # 已抽取
        entity = _make_entity(existing_ids, entity_type, kw)
        existing_names[kw] = entity.entity_id
        out.append(entity)
    return out


# ---------------------------------------------------------------------------
# 数字类指标抽取
# ---------------------------------------------------------------------------
def _extract_metric_facts_from_text(
    text: str,
    company_name: str,
) -> list[dict]:
    """从文本抽取"指标 数值 单位"三元组。"""
    out: list[dict] = []
    for m in _NUMBER_PATTERN.finditer(text):
        metric = m.group("metric").strip()
        value_str = m.group("value").replace(",", "")
        unit = m.group("unit")
        try:
            value: float | None = float(value_str)
        except ValueError:
            value = None
        # 仅保留已知指标关键词
        if not any(kw in metric for kw in _METRIC_KW):
            continue
        out.append(
            {
                "predicate": metric,
                "object_value": value,
                "unit": unit,
                "evidence": text[:200],
            }
        )
    return out


# ---------------------------------------------------------------------------
# 主入口：extract_entities
# ---------------------------------------------------------------------------
def extract_entities(
    claims: list[dict],
    evidence: list[dict],
    company_facts: list[dict],
) -> list[Entity]:
    """从 Claims/Evidence/Company Facts 抽取金融实体。

    返回去重后的实体列表（含 Entity ID）。
    """
    entities: list[Entity] = []
    existing_ids: list[str] = []
    existing_names: dict[str, str] = {}

    # ---- 1. 公司实体 ----
    company_name = ""
    for c in claims:
        if c.get("entity_name"):
            company_name = c["entity_name"]
            break
    if not company_name:
        for f in company_facts:
            if f.get("dimension") == "COMPANY" and f.get("subject"):
                company_name = f["subject"]
                break
    if not company_name:
        company_name = _COMPANY_KW[0]  # 默认美的集团

    company_entity = _make_entity(
        existing_ids,
        ENTITY_COMPANY,
        company_name,
        aliases=_COMPANY_KW if company_name in _COMPANY_KW else [],
        metadata={"is_primary": True},
    )
    entities.append(company_entity)
    existing_names[company_name] = company_entity.entity_id

    # ---- 2. 收集所有文本 ----
    texts: list[str] = []
    for c in claims:
        t = c.get("original_text") or c.get("source_text") or ""
        if t:
            texts.append(t)
    for e in evidence:
        t = e.get("text") or ""
        if t:
            texts.append(t)
    for f in company_facts:
        t = f"{f.get('statement', '')} {f.get('evidence', '')}"
        if t.strip():
            texts.append(t)

    all_text = "\n".join(texts)

    # ---- 3. 按关键词抽取各类实体 ----
    # 业务
    entities.extend(
        _extract_by_keywords(
            all_text, _BUSINESS_KW, ENTITY_BUSINESS, existing_ids, existing_names
        )
    )
    # 产品
    entities.extend(
        _extract_by_keywords(
            all_text, _PRODUCT_KW, ENTITY_PRODUCT, existing_ids, existing_names
        )
    )
    # 地区
    entities.extend(
        _extract_by_keywords(
            all_text, _REGION_KW, ENTITY_REGION, existing_ids, existing_names
        )
    )
    # 竞争对手
    entities.extend(
        _extract_by_keywords(
            all_text, _COMPETITOR_KW, ENTITY_COMPETITOR, existing_ids, existing_names
        )
    )
    # 财务指标
    entities.extend(
        _extract_by_keywords(
            all_text, _METRIC_KW, ENTITY_METRIC, existing_ids, existing_names
        )
    )
    # 高管
    entities.extend(
        _extract_by_keywords(
            all_text, _EXECUTIVE_KW, ENTITY_EXECUTIVE, existing_ids, existing_names
        )
    )

    return entities


# ---------------------------------------------------------------------------
# 辅助：从 Company Facts 抽取数字事实（供 graph_builder 使用）
# ---------------------------------------------------------------------------
def extract_metric_facts(
    company_facts: list[dict],
    claims: list[dict],
    evidence: list[dict],
) -> list[dict]:
    """从 Company Facts + Claims/Evidence 文本抽取数字类事实。

    返回事实字典列表（含 predicate/object_value/unit/evidence）。
    """
    out: list[dict] = []

    # 从 Company Facts 的 evidence 字段抽取
    for f in company_facts:
        evidence_text = f.get("evidence", "")
        if not evidence_text:
            continue
        facts = _extract_metric_facts_from_text(evidence_text, f.get("subject", ""))
        for fact in facts:
            fact["source"] = f.get("source", "FINANCIAL_REPORT")
            fact["source_label"] = f.get("source_label", "")
            fact["timestamp"] = f.get("timestamp", "")
            fact["confidence"] = f.get("confidence", 0.9)
            out.append(fact)

    # 从 Claims 原文抽取（补充）
    for c in claims:
        text = c.get("original_text") or c.get("source_text") or ""
        if not text:
            continue
        facts = _extract_metric_facts_from_text(text, "")
        for fact in facts:
            fact["source"] = "CLAIM"
            fact["source_label"] = f"Claim {c.get('claim_id', '')}"
            fact["timestamp"] = ""
            fact["confidence"] = 0.7
            out.append(fact)

    # 从 Evidence 文本抽取（补充）
    for e in evidence:
        text = e.get("text", "")
        if not text:
            continue
        facts = _extract_metric_facts_from_text(text, "")
        for fact in facts:
            fact["source"] = "EVIDENCE"
            fact["source_label"] = f"Evidence p{e.get('page_number', '?')}"
            fact["timestamp"] = ""
            fact["confidence"] = 0.85
            out.append(fact)

    return out


__all__ = [
    "extract_entities",
    "extract_metric_facts",
]
