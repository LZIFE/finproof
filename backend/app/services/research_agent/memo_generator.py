"""FinProof Research Memo Generator（Phase 17，任务书 §5）。

生成 Evidence First Research Memo，结构：
  1. Company Overview
  2. Key Facts
  3. Financial Facts
  4. Business Facts
  5. Risk Findings
  6. Evidence Chain
  7. Open Questions

**禁止**：buy/sell、target price、recommendation（投资建议/股票推荐/估值预测）。
无证据事实 → Open Questions。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.research_agent.schemas import (
    EvidenceRef,
    PHASE_MEMO_GENERATED,
    ResearchFinding,
    ResearchMemo,
    ResearchPlan,
    ResearchSession,
    RiskFinding,
    TASK_BUSINESS_ANALYSIS,
    TASK_COMPANY_PROFILE,
    TASK_COMPETITION_FACTS,
    TASK_FINANCIAL_OVERVIEW,
    TASK_RISK_DISCOVERY,
    TASK_DONE,
    TASK_SKIPPED,
    ToolCall,
    _now_iso,
    contains_forbidden_memo_content,
)


def generate_memo(
    plan: ResearchPlan,
    findings: list[ResearchFinding],
    risk_findings: list[RiskFinding],
    tasks_status: dict[str, str],
    tool_calls: list[ToolCall],
) -> ResearchMemo:
    """从研究发现组装 Research Memo。"""
    # ① Company Overview
    overview = _company_overview(plan, tasks_status)

    # 分类事实
    key_facts = [f for f in findings if f.task_type == TASK_COMPANY_PROFILE]
    financial_facts = [f for f in findings if f.task_type == TASK_FINANCIAL_OVERVIEW]
    business_facts = [f for f in findings if f.task_type in (TASK_BUSINESS_ANALYSIS, TASK_COMPETITION_FACTS)]
    # 风险发现作为 findings 的也归入 risk_findings（已单独传入）

    # ⑥ Evidence Chain（去重汇总）
    evidence_chain = _dedup_evidence(findings, risk_findings)

    # ⑦ Open Questions：无证据事实 + 待验证事项
    open_questions: list[str] = []
    for f in findings:
        if not f.supported or not f.evidence:
            open_questions.append(f"{f.task_type}({f.metric})：{f.content}")
    for r in risk_findings:
        if r.logical_gap:
            open_questions.append(f"逻辑风险待验证：{r.logical_gap}")
    # 跳过的任务也列入 Open Questions
    for task_type, status in tasks_status.items():
        if status == TASK_SKIPPED:
            open_questions.append(f"{task_type}：未检索到证据，需补充数据源。")

    # 评测指标
    evidence_coverage = _evidence_coverage(findings)
    unsupported_claim_rate = _unsupported_claim_rate(findings)
    task_completion_rate = _task_completion_rate(tasks_status)

    memo = ResearchMemo(
        company=plan.company,
        stock_code=plan.stock_code,
        company_overview=overview,
        key_facts=key_facts,
        financial_facts=financial_facts,
        business_facts=business_facts,
        risk_findings=risk_findings,
        evidence_chain=evidence_chain,
        open_questions=open_questions,
        evidence_coverage=evidence_coverage,
        unsupported_claim_rate=unsupported_claim_rate,
        task_completion_rate=task_completion_rate,
        generated_at=_now_iso(),
    )

    # 终极护栏：检查 Memo 全文不含禁止词
    _assert_no_forbidden(memo)
    return memo


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------
def _company_overview(plan: ResearchPlan, tasks_status: dict[str, str]) -> str:
    """① Company Overview：公司 + 代码 + 任务执行概况。"""
    parts = [f"公司：{plan.company}"]
    if plan.stock_code:
        parts.append(f"股票代码：{plan.stock_code}")
    done = sum(1 for s in tasks_status.values() if s == TASK_DONE)
    skipped = sum(1 for s in tasks_status.values() if s == TASK_SKIPPED)
    total = len(tasks_status)
    parts.append(
        f"研究任务：共 {total} 项，已完成 {done} 项，因无证据跳过 {skipped} 项。"
    )
    parts.append("本 Memo 仅含事实、证据、风险与待验证事项，不构成投资建议、股票推荐或估值预测。")
    return "；".join(parts) + "。"


def _dedup_evidence(
    findings: list[ResearchFinding],
    risk_findings: list[RiskFinding],
) -> list[EvidenceRef]:
    """去重汇总所有证据引用。"""
    seen: set[str] = set()
    out: list[EvidenceRef] = []
    for f in findings:
        for e in f.evidence:
            key = str(e.block_id) or str(e.document_id) + str(e.page_number)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(e)
    for r in risk_findings:
        for e in r.evidence:
            key = str(e.block_id) or str(e.document_id) + str(e.page_number)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(e)
    return out


def _evidence_coverage(findings: list[ResearchFinding]) -> float:
    """有证据事实占比。"""
    if not findings:
        return 0.0
    grounded = sum(1 for f in findings if f.evidence and f.supported)
    return round(grounded / len(findings), 3)


def _unsupported_claim_rate(findings: list[ResearchFinding]) -> float:
    """无证据事实占比。"""
    if not findings:
        return 0.0
    unsupported = sum(1 for f in findings if not f.evidence or not f.supported)
    return round(unsupported / len(findings), 3)


def _task_completion_rate(tasks_status: dict[str, str]) -> float:
    """已完成任务占比（DONE / (DONE + SKIPPED + RUNNING)）。"""
    if not tasks_status:
        return 0.0
    done = sum(1 for s in tasks_status.values() if s == TASK_DONE)
    return round(done / len(tasks_status), 3)


def _assert_no_forbidden(memo: ResearchMemo) -> None:
    """终极护栏：检查 Memo 全文不含禁止词（投资建议/股票推荐/估值预测）。"""
    texts = [memo.company_overview, memo.generated_at or ""]
    for f in memo.key_facts + memo.financial_facts + memo.business_facts:
        texts.append(f.content)
        texts.append(f.notes)
    for r in memo.risk_findings:
        texts.append(r.content)
        texts.append(r.logical_gap)
    texts.extend(memo.open_questions)
    for t in texts:
        if contains_forbidden_memo_content(t):
            raise ValueError(f"Memo 含禁止词（投资建议/股票推荐/估值预测），违反 Evidence First 边界：{t[:80]}")


__all__ = ["generate_memo"]
