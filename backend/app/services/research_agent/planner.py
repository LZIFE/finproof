"""FinProof Research Planner（Phase 17，任务书 §2）。

输入 company → 自动生成研究计划：Financial / Business / Risk / Competition 四类任务。

Financial: revenue / profit / margin / cash flow
Business:  segments / products / regions
Risk:      contradiction / unsupported claims / historical changes
Competition: competitor facts

所有任务均生成 claim_query 以供 Evidence Retrieval。
"""

from __future__ import annotations

from app.services.research_agent.schemas import (
    ResearchPlan,
    ResearchTaskSpec,
    TASK_BUSINESS_ANALYSIS,
    TASK_COMPANY_PROFILE,
    TASK_COMPETITION_FACTS,
    TASK_FINANCIAL_OVERVIEW,
    TASK_RISK_DISCOVERY,
    _now_iso,
)


def _q(company: str, metric: str, period: str = "") -> str:
    """构造 evidence retrieval 查询文本。"""
    period_part = f" {period}" if period else ""
    return f"{company}{period_part} {metric}"


def make_plan(company: str, stock_code: str = "") -> ResearchPlan:
    """为公司自动生成研究计划。

    任务书 §2：
      - Financial: revenue / profit / margin / cash flow
      - Business:  segments / products / regions
      - Risk:      contradiction / unsupported claims / historical changes
      - Competition: competitor facts
    """
    if not company:
        raise ValueError("company 不能为空")

    tasks: list[ResearchTaskSpec] = []

    # === Company Profile（业务画像：segments / products / regions + 重要指标）===
    tasks.append(ResearchTaskSpec(
        task_type=TASK_COMPANY_PROFILE,
        category="Business",
        objective=f"梳理 {company} 业务结构（业务分部、产品、地区）与重要指标",
        claim_query=_q(company, "业务分部 主营产品 地区"),
        metric="segments",
    ))

    # === Financial Overview（revenue / profit / margin / cash flow 趋势）===
    fin_metrics = [
        ("revenue", "营业收入 同比增长"),
        ("profit", "净利润 同比增长"),
        ("margin", "毛利率 利润率"),
        ("cash_flow", "经营现金流 同比"),
    ]
    for metric, query_metric in fin_metrics:
        tasks.append(ResearchTaskSpec(
            task_type=TASK_FINANCIAL_OVERVIEW,
            category="Financial",
            objective=f"梳理 {company} {metric} 趋势",
            claim_query=_q(company, query_metric, period="2025"),
            metric=metric,
        ))

    # === Business Analysis（调用 Knowledge Graph 生成 business map）===
    tasks.append(ResearchTaskSpec(
        task_type=TASK_BUSINESS_ANALYSIS,
        category="Business",
        objective=f"构建 {company} 业务地图（业务分部 + 地区 + 指标事实）",
        claim_query=_q(company, "海外业务 海外收入 业务分部"),
        metric="business_map",
        need_knowledge_graph=True,
    ))

    # === Risk Discovery（调用 Risk Engine + Reasoning + Monitoring）===
    tasks.append(ResearchTaskSpec(
        task_type=TASK_RISK_DISCOVERY,
        category="Risk",
        objective=f"发现 {company} 财务风险、业务风险、逻辑风险、历史观点冲突",
        claim_query=_q(company, "海外收入增长 海外业务利润增长核心"),
        metric="risk",
        need_reasoning=True,
        need_monitoring=True,
    ))

    # === Competition Facts（竞争对手事实）===
    tasks.append(ResearchTaskSpec(
        task_type=TASK_COMPETITION_FACTS,
        category="Competition",
        objective=f"梳理 {company} 主要竞争对手的事实信息（份额/产品/财务对比）",
        claim_query=_q(company, "竞争对手 市场份额 行业排名"),
        metric="competitor",
    ))

    return ResearchPlan(
        company=company,
        stock_code=stock_code,
        tasks=tasks,
        created_at=_now_iso(),
    )


__all__ = ["make_plan"]
