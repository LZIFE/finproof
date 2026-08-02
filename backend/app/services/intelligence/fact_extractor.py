"""Fact Extractor（Phase 8）：从外部来源提取公司事实。

Evidence First 原则：
- 每条 Company Fact 必须包含 source / evidence / timestamp / confidence；
- 无证据不记录事实；
- 优先使用既有 Evidence Retrieval 的财报证据，避免重复检索。

来源（任务书 §2）：
- 财报（FINANCIAL_REPORT）
- 公告（ANNOUNCEMENT）
- 新闻（NEWS）
- 官网（OFFICIAL_SITE）

实现策略（确定性 + 可解释）：
1. 财报事实：从已解析的财报文档块中按关键词/数字模式抽取
   （营业收入/净利润/海外业务/市场份额/产品/竞争对手等）；
2. 公告/新闻/官网事实：作为外部事实输入直接登记
   （由调用方提供，extractor 仅做 Evidence First 校验）。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import Document, DocumentBlock
from app.services.intelligence.schemas import (
    CONFLICT_NO_OPPOSITION,
    FACT_DIM_BUSINESS,
    FACT_DIM_COMPANY,
    FACT_DIM_COMPETITION,
    FACT_DIM_FINANCIAL,
    FACT_DIM_MARKET,
    FACT_DIM_PRODUCT,
    FACT_SOURCE_ANNOUNCEMENT,
    FACT_SOURCE_FINANCIAL_REPORT,
    FACT_SOURCE_NEWS,
    FACT_SOURCE_OFFICIAL_SITE,
    CompanyFact,
)

# ---------------------------------------------------------------------------
# Evidence First 校验：缺任一必填字段即拒绝
# ---------------------------------------------------------------------------
_REQUIRED_FACT_FIELDS = ("source", "evidence", "timestamp", "confidence")

# 财报事实抽取规则：关键字 → 维度
_FINANCIAL_KEYWORDS = (
    "营业收入",
    "营业总收入",
    "净利润",
    "归母净利润",
    "毛利率",
    "经营性现金流",
)

_BUSINESS_KEYWORDS = ("主营业务", "业务结构", "分部", "暖通空调", "消费电器", "机器人")

_MARKET_KEYWORDS = ("海外", "境外", "北美", "欧洲", "东南亚", "OBM", "Midea")

_PRODUCT_KEYWORDS = ("空调", "冰箱", "洗衣机", "COLMO", "东芝", "KUKA", "库卡")

_COMPETITION_KEYWORDS = ("海尔", "格力", "海信", "市场份额", "行业第一", "龙头")

# 数字抽取正则：匹配 "营业收入 4,564.52 亿元" / "归母净利润439.45亿元"
_NUMBER_PATTERN = re.compile(
    r"(?P<metric>[^\s，。、：]{2,12}?)"
    r"\s*[为达约共]?\s*(?P<value>\d[\d,]*\.?\d*)\s*"
    r"(?P<unit>亿元|万元|元|%)"
)

# 中文数字清洗
_UNIT_NORMALIZE = {"亿": "亿元", "万": "万元"}


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _next_fact_id(existing: Iterable[str]) -> str:
    used = {x for x in existing}
    idx = 1
    while True:
        fid = f"FACT-{idx:04d}"
        if fid not in used:
            return fid
        idx += 1


# ---------------------------------------------------------------------------
# Evidence First：外部事实登记校验
# ---------------------------------------------------------------------------
def validate_fact_evidence(fact: CompanyFact) -> list[str]:
    """校验单条 Fact 是否满足 Evidence First；返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    if not fact.source:
        errors.append("source 缺失（Evidence First 要求每条事实可追溯）")
    if not fact.evidence:
        errors.append("evidence 缺失（事实必须附原始证据）")
    if not fact.timestamp:
        errors.append("timestamp 缺失（事实必须有时间戳）")
    if fact.confidence < 0 or fact.confidence > 1:
        errors.append("confidence 必须在 [0, 1] 区间")
    return errors


def register_external_fact(
    existing_ids: Iterable[str],
    dimension: str,
    subject: str,
    statement: str,
    source: str,
    source_label: str,
    evidence: str,
    timestamp: str,
    confidence: float,
    value=None,
    unit: str = "",
    period: str = "",
) -> CompanyFact:
    """登记一条外部事实（公告/新闻/官网），并做 Evidence First 校验。

    用于 conflict_detector 比对的"外部事实"输入。
    """
    fact = CompanyFact(
        fact_id=_next_fact_id(existing_ids),
        dimension=dimension,
        subject=subject,
        statement=statement,
        value=value,
        unit=unit,
        period=period,
        source=source,
        source_label=source_label,
        evidence=evidence,
        timestamp=timestamp,
        confidence=confidence,
    )
    errors = validate_fact_evidence(fact)
    if errors:
        raise ValueError("Evidence First 校验失败: " + "; ".join(errors))
    return fact


# ---------------------------------------------------------------------------
# 财报事实抽取：从 DocumentBlock 文本中按模式抽取
# ---------------------------------------------------------------------------
def _classify_dimension(metric_or_text: str) -> str:
    text = metric_or_text
    if any(kw in text for kw in _FINANCIAL_KEYWORDS):
        return FACT_DIM_FINANCIAL
    if any(kw in text for kw in _MARKET_KEYWORDS):
        return FACT_DIM_MARKET
    if any(kw in text for kw in _PRODUCT_KEYWORDS):
        return FACT_DIM_PRODUCT
    if any(kw in text for kw in _COMPETITION_KEYWORDS):
        return FACT_DIM_COMPETITION
    if any(kw in text for kw in _BUSINESS_KEYWORDS):
        return FACT_DIM_BUSINESS
    return FACT_DIM_COMPANY


def extract_facts_from_financial_report(
    session: Session,
    document_id: int,
    max_facts: int = 30,
) -> list[CompanyFact]:
    """从已解析的财报文档抽取事实。

    步骤：
    1. 拉取该文档所有块文本；
    2. 用数字模式正则匹配"指标 数值 单位"三元组；
    3. 同时抽取业务/市场/产品/竞争关键词所在段落作为定性事实；
    4. 每条事实附 evidence（原文片段）/ source=FINANCIAL_REPORT /
       timestamp=文档创建时间 / confidence（财报默认 0.95）。
    """
    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError(f"文档不存在: {document_id}")

    facts: list[CompanyFact] = []
    used_ids: list[str] = []

    blocks = (
        session.query(DocumentBlock)
        .filter(DocumentBlock.document_id == document_id)
        .order_by(DocumentBlock.id)
        .all()
    )

    seen_statements: set[str] = set()

    # ---- 数字类事实 ----
    for blk in blocks:
        text = (blk.text or "").strip()
        if not text:
            continue
        for m in _NUMBER_PATTERN.finditer(text):
            metric = m.group("metric").strip()
            value_str = m.group("value").replace(",", "")
            unit = m.group("unit")
            try:
                value: float | None = float(value_str)
            except ValueError:
                value = None
            dimension = _classify_dimension(metric)
            statement = f"{metric} {value_str}{unit}"
            if statement in seen_statements:
                continue
            seen_statements.add(statement)
            fact = CompanyFact(
                fact_id=_next_fact_id(used_ids),
                dimension=dimension,
                subject=doc.company_name or "",
                statement=statement,
                value=value,
                unit=unit,
                period=doc.report_period or "",
                source=FACT_SOURCE_FINANCIAL_REPORT,
                source_label=f"{doc.company_name or '公司'} 财报",
                evidence=text[:200],
                page_number=getattr(blk, "page_id", None),
                timestamp=doc.publication_date or _now_iso(),
                confidence=0.95,
            )
            facts.append(fact)
            used_ids.append(fact.fact_id)
            if len(facts) >= max_facts:
                return facts

    # ---- 定性事实（业务/市场/产品/竞争关键词）----
    for blk in blocks:
        text = (blk.text or "").strip()
        if not text:
            continue
        matched_kws: list[tuple[str, str]] = []
        for kw in _BUSINESS_KEYWORDS:
            if kw in text:
                matched_kws.append((FACT_DIM_BUSINESS, kw))
        for kw in _MARKET_KEYWORDS:
            if kw in text:
                matched_kws.append((FACT_DIM_MARKET, kw))
        for kw in _PRODUCT_KEYWORDS:
            if kw in text:
                matched_kws.append((FACT_DIM_PRODUCT, kw))
        for kw in _COMPETITION_KEYWORDS:
            if kw in text:
                matched_kws.append((FACT_DIM_COMPETITION, kw))
        if not matched_kws:
            continue
        # 取第一个匹配维度
        dimension, kw = matched_kws[0]
        statement = f"涉及{dimension.lower()}关键词「{kw}」"
        if statement in seen_statements:
            continue
        seen_statements.add(statement)
        fact = CompanyFact(
            fact_id=_next_fact_id(used_ids),
            dimension=dimension,
            subject=doc.company_name or "",
            statement=statement,
            period=doc.report_period or "",
            source=FACT_SOURCE_FINANCIAL_REPORT,
            source_label=f"{doc.company_name or '公司'} 财报",
            evidence=text[:200],
            timestamp=doc.publication_date or _now_iso(),
            confidence=0.85,
        )
        facts.append(fact)
        used_ids.append(fact.fact_id)
        if len(facts) >= max_facts:
            return facts

    return facts


# ---------------------------------------------------------------------------
# 组合：财报事实 + 外部事实
# ---------------------------------------------------------------------------
def build_company_facts(
    session: Session,
    financial_doc_id: int,
    external_facts: list[CompanyFact] | None = None,
) -> list[CompanyFact]:
    """汇总公司事实：财报抽取 + 外部输入（公告/新闻/官网）。

    顺序：财报事实在前（高置信），外部事实在后；
    每条均通过 Evidence First 校验。
    """
    report_facts = extract_facts_from_financial_report(session, financial_doc_id)
    all_facts = list(report_facts)

    external = external_facts or []
    for ef in external:
        errors = validate_fact_evidence(ef)
        if errors:
            raise ValueError("Evidence First 校验失败: " + "; ".join(errors))
        all_facts.append(ef)

    return all_facts


# ---------------------------------------------------------------------------
# 便捷构造器：从字典列表登记外部事实
# ---------------------------------------------------------------------------
def register_external_facts_from_dicts(
    existing_ids: Iterable[str],
    records: list[dict],
) -> list[CompanyFact]:
    """从字典列表批量登记外部事实。

    字典字段对齐 register_external_fact 入参。
    """
    existing = list(existing_ids)
    out: list[CompanyFact] = []
    for rec in records:
        fact = register_external_fact(
            existing_ids=existing,
            dimension=rec["dimension"],
            subject=rec.get("subject", ""),
            statement=rec["statement"],
            source=rec["source"],
            source_label=rec.get("source_label", rec["source"]),
            evidence=rec["evidence"],
            timestamp=rec["timestamp"],
            confidence=float(rec.get("confidence", 0.8)),
            value=rec.get("value"),
            unit=rec.get("unit", ""),
            period=rec.get("period", ""),
        )
        existing.append(fact.fact_id)
        out.append(fact)
    return out


__all__ = [
    "FACT_SOURCE_FINANCIAL_REPORT",
    "FACT_SOURCE_ANNOUNCEMENT",
    "FACT_SOURCE_NEWS",
    "FACT_SOURCE_OFFICIAL_SITE",
    "validate_fact_evidence",
    "register_external_fact",
    "extract_facts_from_financial_report",
    "build_company_facts",
    "register_external_facts_from_dicts",
]
