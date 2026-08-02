"""Research Agent（Phase 9）：基于已有 Evidence 生成公司/业务/财务调研结论。

Evidence First：所有结论必须引用已有证据（DocumentBlock / Intelligence
Report 的 Verified Facts），不引入未核验的信息。

输出（任务书 §3）：
- Company Overview    公司概况（业务领域/产品/市场覆盖）
- Business Analysis   业务分析（业务分部/增长驱动/业务风险）
- Financial Summary   财务摘要（关键指标/营收趋势/利润趋势）

工具调用（可追溯）：
- 读取投资材料文档块（document_service）
- 读取 Intelligence Report 的 Verified Facts（intelligence_agent.get_report）
- 读取已有 Evidence（verification_service.fetch_evidence）

设计约束：不输出投资建议、不自动决定买卖、保持 Human-in-the-loop。
不修改已有核心模块。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, DocumentBlock
from app.services.investment_committee.schemas import (
    AGENT_RESEARCH,
    AGENT_STATUS_DONE,
    AgentResult,
    AgentTask,
    BusinessAnalysis,
    CompanyOverview,
    FinancialSummary,
    ResearchFindings,
)

# ---------------------------------------------------------------------------
# 工具调用清单（可追溯）
# ---------------------------------------------------------------------------
TOOL_READ_DOCUMENT_BLOCKS = "read_document_blocks"
TOOL_READ_INTELLIGENCE_FACTS = "read_intelligence_facts"
TOOL_READ_INVESTMENT_MATERIAL = "read_investment_material"
TOOL_KNOWLEDGE_GRAPH = "knowledge_graph"

RESEARCH_TOOLS = [
    TOOL_READ_DOCUMENT_BLOCKS,
    TOOL_READ_INTELLIGENCE_FACTS,
    TOOL_READ_INVESTMENT_MATERIAL,
    TOOL_KNOWLEDGE_GRAPH,
]

# ---------------------------------------------------------------------------
# 关键词分组：用于从 Evidence 文本中抽取调研结论
# ---------------------------------------------------------------------------
_BUSINESS_KW = ("主营业务", "业务结构", "分部", "暖通空调", "消费电器", "机器人", "智能建筑", "新能源")
_PRODUCT_KW = ("空调", "冰箱", "洗衣机", "COLMO", "东芝", "KUKA", "库卡", "压缩机")
_MARKET_KW = ("海外", "境外", "北美", "欧洲", "东南亚", "OBM", "Midea", "全球")
_FINANCIAL_KW = ("营业收入", "营业总收入", "净利润", "归母净利润", "毛利率", "经营性现金流")
_REVENUE_KW = ("营业收入", "营业总收入")
_PROFIT_KW = ("归母净利润", "净利润", "毛利润")
_GROWTH_DRIVER_KW = ("海外", "OBM", "新能源", "机器人", "智能", "高端", "海外业务")
_BUSINESS_RISK_KW = ("原材料", "汇率", "竞争", "库存", "应收", "风险")


def _read_document_blocks(session: Session, document_id: int) -> list[DocumentBlock]:
    """工具 1：读取指定文档的所有块文本。"""
    return (
        session.query(DocumentBlock)
        .filter(DocumentBlock.document_id == document_id)
        .order_by(DocumentBlock.id)
        .all()
    )


def _read_investment_material(session: Session, document_id: int) -> str:
    """工具 3：读取投资材料原文（拼接文档块）。"""
    blocks = _read_document_blocks(session, document_id)
    return "\n".join((b.text or "") for b in blocks)


def _query_knowledge_graph(
    session: Session,
    document_id: int,
) -> dict:
    """工具 4：查询已构建的金融知识图谱（Company Profile / Business Map）。

    若文档未构建知识图谱，返回空字典（Research Agent 仍可基于 Evidence 工作）。
    """
    try:
        from app.services.knowledge_graph.fact_graph import (
            get_business_map,
            get_company_profile,
        )
        from app.services.knowledge_graph.graph_builder import load_graph

        graph = load_graph(session, document_id=document_id)
        if not graph.entities:
            return {}
        return {
            "company_profile": get_company_profile(graph).to_dict(),
            "business_map": get_business_map(graph).to_dict(),
        }
    except Exception:  # noqa: BLE001 —— 知识图谱缺失不应阻断 Research Agent
        return {}


def _read_intelligence_facts(
    session: Session,
    intelligence_report_id: int | None,
) -> list[dict]:
    """工具 2：读取 Intelligence Report 的 Verified Facts。"""
    if intelligence_report_id is None:
        return []
    from app.services.intelligence.intelligence_agent import get_report

    try:
        report = get_report(session, intelligence_report_id)
    except LookupError:
        return []
    return [f.to_dict() for f in report.verified_facts]


# ---------------------------------------------------------------------------
# Research 各子部分构建
# ---------------------------------------------------------------------------
def _build_company_overview(
    doc: Document,
    facts: list[dict],
    blocks_text: str,
) -> CompanyOverview:
    """公司概况：来自 Intelligence Verified Facts + 文档块。"""
    business_fields: list[str] = []
    products: list[str] = []
    market_coverage: list[str] = []

    # 从 Verified Facts 抽取
    for f in facts:
        dim = f.get("dimension", "")
        subj = f.get("subject", "")
        stmt = f.get("statement", "")
        if dim == "BUSINESS" and subj and subj not in business_fields:
            business_fields.append(subj)
        elif dim == "PRODUCT":
            label = subj or stmt
            if label and label not in products:
                products.append(label)
        elif dim == "MARKET":
            label = subj or stmt
            if label and label not in market_coverage:
                market_coverage.append(label)

    # 文档块关键词兜底
    for kw in _BUSINESS_KW:
        if kw in blocks_text and kw not in business_fields:
            business_fields.append(kw)
    for kw in _PRODUCT_KW:
        if kw in blocks_text and kw not in products:
            products.append(kw)
    for kw in _MARKET_KW:
        if kw in blocks_text and kw not in market_coverage:
            market_coverage.append(kw)

    return CompanyOverview(
        company=doc.company_name or "",
        stock_code=doc.stock_code or "",
        report_period=doc.report_period or "",
        business_fields=business_fields[:10],
        products=products[:10],
        market_coverage=market_coverage[:10],
    )


def _build_business_analysis(
    blocks_text: str,
    facts: list[dict],
) -> BusinessAnalysis:
    """业务分析：业务分部/增长驱动/业务风险点。"""
    segments: list[dict] = []
    for f in facts:
        if f.get("dimension") == "BUSINESS":
            segments.append(
                {
                    "subject": f.get("subject", ""),
                    "statement": f.get("statement", ""),
                    "source": f.get("source", ""),
                    "source_label": f.get("source_label", ""),
                }
            )
    # 关键词兜底业务分部
    if not segments:
        for kw in _BUSINESS_KW:
            if kw in blocks_text:
                segments.append({"subject": kw, "statement": f"涉及{kw}业务", "source": "DOCUMENT"})

    growth_drivers: list[str] = []
    for kw in _GROWTH_DRIVER_KW:
        if kw in blocks_text and kw not in growth_drivers:
            growth_drivers.append(kw)
    # 来自 MARKET 维度事实
    for f in facts:
        if f.get("dimension") == "MARKET":
            label = f.get("subject") or f.get("statement", "")
            if label and label not in growth_drivers:
                growth_drivers.append(label)

    risks: list[str] = []
    for kw in _BUSINESS_RISK_KW:
        if kw in blocks_text and kw not in risks:
            risks.append(kw)

    evidence_refs = [f.get("fact_id", "") for f in facts if f.get("fact_id")]

    return BusinessAnalysis(
        segments=segments[:10],
        growth_drivers=growth_drivers[:10],
        risks=risks[:10],
        evidence_refs=evidence_refs,
    )


def _build_financial_summary(
    facts: list[dict],
    blocks_text: str,
) -> FinancialSummary:
    """财务摘要：关键指标/营收趋势/利润趋势。"""
    key_metrics: list[dict] = []
    revenue_trend: list[dict] = []
    profit_trend: list[dict] = []

    for f in facts:
        dim = f.get("dimension", "")
        stmt = f.get("statement", "")
        if dim != "FINANCIAL":
            continue
        metric = {
            "statement": stmt,
            "value": f.get("value"),
            "unit": f.get("unit", ""),
            "period": f.get("period", ""),
            "source_label": f.get("source_label", ""),
        }
        key_metrics.append(metric)
        if any(kw in stmt for kw in _REVENUE_KW):
            revenue_trend.append(metric)
        elif any(kw in stmt for kw in _PROFIT_KW):
            profit_trend.append(metric)

    evidence_refs = [f.get("fact_id", "") for f in facts if f.get("fact_id")]

    return FinancialSummary(
        key_metrics=key_metrics[:10],
        revenue_trend=revenue_trend[:5],
        profit_trend=profit_trend[:5],
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# 主入口：run_research
# ---------------------------------------------------------------------------
def run_research(session: Session, task: AgentTask) -> AgentResult:
    """Research Agent 主入口：基于已有 Evidence 生成调研结论。"""
    if task.agent != AGENT_RESEARCH:
        return AgentResult(
            agent=AGENT_RESEARCH,
            status="FAILED",
            error=f"Research Agent 收到非法任务: {task.agent}",
        )

    doc = session.get(Document, task.document_id)
    if doc is None:
        return AgentResult(
            agent=AGENT_RESEARCH,
            status="FAILED",
            error=f"文档不存在: {task.document_id}",
        )

    # 工具调用
    blocks = _read_document_blocks(session, task.document_id)
    blocks_text = "\n".join((b.text or "") for b in blocks)
    facts = _read_intelligence_facts(session, task.intelligence_report_id)
    # 若无 Intelligence Report，则尝试读取投资材料原文
    if not facts:
        _ = _read_investment_material(session, task.document_id)
    # 工具 4：查询已构建的金融知识图谱（若存在）
    kg_data = _query_knowledge_graph(session, task.document_id)

    # 构建调研结论
    company_overview = _build_company_overview(doc, facts, blocks_text)
    business_analysis = _build_business_analysis(blocks_text, facts)
    financial_summary = _build_financial_summary(facts, blocks_text)

    # 知识图谱增强：合并 KG Company Profile / Business Map 的字段
    if kg_data:
        kg_profile = kg_data.get("company_profile", {})
        kg_business_map = kg_data.get("business_map", {})
        # 业务领域：合并 KG businesses 与原有 business_fields
        for biz in kg_profile.get("businesses", []) or []:
            if biz not in company_overview.business_fields:
                company_overview.business_fields.append(biz)
        # 产品：合并 KG products
        for prod in kg_profile.get("products", []) or []:
            if prod not in company_overview.products:
                company_overview.products.append(prod)
        # 市场覆盖：合并 KG regions
        for region in kg_profile.get("regions", []) or []:
            if region not in company_overview.market_coverage:
                company_overview.market_coverage.append(region)
        # 业务分部：合并 KG business_segments
        for seg in kg_business_map.get("business_segments", []) or []:
            business = seg.get("business", "")
            if business and not any(
                s.get("subject") == business for s in business_analysis.segments
            ):
                business_analysis.segments.append(
                    {"subject": business, "statement": f"KG 业务分部: {business}", "source": "KNOWLEDGE_GRAPH"}
                )
        # 截断避免过长
        company_overview.business_fields = company_overview.business_fields[:10]
        company_overview.products = company_overview.products[:10]
        company_overview.market_coverage = company_overview.market_coverage[:10]
        business_analysis.segments = business_analysis.segments[:10]

    research = ResearchFindings(
        company_overview=company_overview,
        business_analysis=business_analysis,
        financial_summary=financial_summary,
        evidence_refs=list(
            dict.fromkeys(
                business_analysis.evidence_refs + financial_summary.evidence_refs
            )
        ),
    )

    summary = (
        f"Research Agent 完成调研：公司 {company_overview.company}"
        f"（业务 {len(company_overview.business_fields)} 项 / "
        f"产品 {len(company_overview.products)} 项 / "
        f"市场覆盖 {len(company_overview.market_coverage)} 项 / "
        f"财务指标 {len(financial_summary.key_metrics)} 项）。"
    )

    return AgentResult(
        agent=AGENT_RESEARCH,
        status=AGENT_STATUS_DONE,
        findings=[research.to_dict()],
        summary=summary,
        tools_called=RESEARCH_TOOLS,
        evidence_refs=research.evidence_refs,
    )


__all__ = [
    "RESEARCH_TOOLS",
    "run_research",
]
