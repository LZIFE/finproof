"""FinProof Copilot Query Planner（Phase 15，任务书 §3）。

根据 Intent 自动规划工具链，调用已有模块生成 ExecutionTrace。

意图 → 工具链路由：
- FACT_QUERY             → [evidence_retrieval, verification, risk_engine]
- RISK_EXPLANATION       → [evidence_retrieval, risk_engine]
- EVIDENCE_QUERY         → [evidence_retrieval, verification]
- COMPARISON_QUERY       → [monitoring_memory, evidence_retrieval, risk_engine]
- INVESTIGATION_REQUEST  → [knowledge_graph, evidence_retrieval, verification, risk_engine]
                            （or autonomous_investigation for 复杂调查）

约束：不修改已有核心验证逻辑；Evidence First。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.copilot.schemas import (
    INTENT_COMPARISON_QUERY,
    INTENT_EVIDENCE_QUERY,
    INTENT_FACT_QUERY,
    INTENT_INVESTIGATION_REQUEST,
    INTENT_REASONING_EXPLANATION,
    INTENT_RISK_EXPLANATION,
    INTENT_UNKNOWN,
    TOOL_AUTONOMOUS_INVESTIGATION,
    TOOL_EVIDENCE_RETRIEVAL,
    TOOL_KNOWLEDGE_GRAPH,
    TOOL_MONITORING_MEMORY,
    TOOL_RISK_ENGINE,
    TOOL_VERIFICATION,
    Intent,
    ToolStep,
    ExecutionTrace,
    _now_iso,
)


# ---------------------------------------------------------------------------
# 意图 → 工具链规划模板
# ---------------------------------------------------------------------------
_PLAN_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    INTENT_FACT_QUERY: [
        (TOOL_EVIDENCE_RETRIEVAL, "检索财务事实证据"),
        (TOOL_VERIFICATION, "核验事实主张"),
        (TOOL_RISK_ENGINE, "评估风险"),
    ],
    INTENT_RISK_EXPLANATION: [
        (TOOL_EVIDENCE_RETRIEVAL, "检索相关证据"),
        (TOOL_RISK_ENGINE, "调用风险引擎评估"),
    ],
    INTENT_EVIDENCE_QUERY: [
        (TOOL_EVIDENCE_RETRIEVAL, "检索证据来源"),
        (TOOL_VERIFICATION, "核验证据支持度"),
    ],
    INTENT_COMPARISON_QUERY: [
        (TOOL_MONITORING_MEMORY, "查询历史投资观点/记忆"),
        (TOOL_EVIDENCE_RETRIEVAL, "检索当前证据"),
        (TOOL_RISK_ENGINE, "评估风险变化"),
    ],
    INTENT_INVESTIGATION_REQUEST: [
        (TOOL_KNOWLEDGE_GRAPH, "查询知识图谱业务结构"),
        (TOOL_EVIDENCE_RETRIEVAL, "检索收入/利润数据"),
        (TOOL_VERIFICATION, "判断支持程度"),
        (TOOL_RISK_ENGINE, "评估风险"),
    ],
    INTENT_REASONING_EXPLANATION: [
        ("financial_reasoning", "调用金融推理引擎：识别逻辑风险/隐含假设/结论跳跃"),
    ],
}


def plan_tools(intent: Intent) -> list[ToolStep]:
    """根据意图生成工具链 ToolStep 列表（未执行，status PENDING）。"""
    template = _PLAN_TEMPLATES.get(intent.intent_type, [])
    steps: list[ToolStep] = []
    for idx, (tool, purpose) in enumerate(template, start=1):
        steps.append(
            ToolStep(
                step=idx,
                tool=tool,
                purpose=purpose,
                input={"query_hint": intent.metric or intent.company},
                output={},
                timestamp=_now_iso(),
            )
        )
    return steps


# ---------------------------------------------------------------------------
# 工具执行器（调用已有模块，不修改其逻辑）
# ---------------------------------------------------------------------------
def execute_step(
    session: Session,
    step: ToolStep,
    query: str,
    intent: Intent,
) -> ToolStep:
    """执行单个 ToolStep，调用对应已有模块。"""
    step.input = {**step.input, "query": query, "company": intent.company, "metric": intent.metric}

    if step.tool == TOOL_EVIDENCE_RETRIEVAL:
        out = _call_evidence_retrieval(session, query, intent)
    elif step.tool == TOOL_VERIFICATION:
        out = _call_verification(session, query, intent)
    elif step.tool == TOOL_RISK_ENGINE:
        out = _call_risk_engine(session, query, intent)
    elif step.tool == TOOL_KNOWLEDGE_GRAPH:
        out = _call_knowledge_graph(session, intent)
    elif step.tool == TOOL_MONITORING_MEMORY:
        out = _call_monitoring_memory(session, intent)
    elif step.tool == "financial_reasoning":
        out = _call_financial_reasoning(session, query, intent)
    else:
        out = {"error": f"未知工具: {step.tool}"}

    step.output = out
    step.evidence_source = out.get("evidence_source", [])
    return step


# ---------------------------------------------------------------------------
# 已有工具封装（薄封装层，不修改原模块）
# ---------------------------------------------------------------------------
def _build_claim(query: str, intent: Intent) -> dict:
    """构造 claim dict 供已有工具调用。"""
    return {
        "claim_id": f"C-COPILOT-{datetime.utcnow().strftime('%H%M%S%f')[:12]}",
        "original_text": query,
        "company": intent.company,
        "metric": intent.metric,
    }


def _call_evidence_retrieval(session: Session, query: str, intent: Intent) -> dict:
    """调用 verification_service.fetch_evidence 检索证据。"""
    try:
        from app.services.verification.verification_service import fetch_evidence

        claim = _build_claim(query, intent)
        evidence = fetch_evidence(session, claim, top_k=5)
        return {
            "evidence_count": len(evidence),
            "evidence": evidence,
            "evidence_source": _extract_sources(evidence),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "evidence_count": 0, "evidence": [], "evidence_source": []}


def _call_verification(session: Session, query: str, intent: Intent) -> dict:
    """调用 verification_service.verify_claim 核验。"""
    try:
        from app.services.verification.verification_service import verify_claim

        claim = _build_claim(query, intent)
        result = verify_claim(session, claim, top_k=5)
        out = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        out["evidence_source"] = _extract_sources(out.get("evidence", []))
        return out
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "verification_status": "INSUFFICIENT_EVIDENCE", "evidence_source": []}


def _call_risk_engine(session: Session, query: str, intent: Intent) -> dict:
    """调用 risk_engine.assess_claim 评估风险。"""
    try:
        from app.services.risk.risk_engine import assess_claim

        claim = _build_claim(query, intent)
        # 简化核验结果：默认 INSUFFICIENT，让 risk_engine 评估
        verification = {
            "claim_id": claim["claim_id"],
            "verification_status": "INSUFFICIENT_EVIDENCE",
            "confidence": 0.5,
        }
        assessment = assess_claim(claim, verification)
        out = assessment.to_dict() if hasattr(assessment, "to_dict") else dict(assessment)
        return {"risk_assessment": out, "evidence_source": []}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "risk_assessment": {"risk_score": 50.0}, "evidence_source": []}


def _call_knowledge_graph(session: Session, intent: Intent) -> dict:
    """调用 knowledge_graph.fact_graph 获取业务结构。"""
    try:
        from app.services.knowledge_graph.fact_graph import get_business_map

        business_map = get_business_map(session, intent.company or "美的集团")
        return {"business_map": business_map, "evidence_source": []}
    except Exception as exc:  # noqa: BLE001
        # 退路：返回简版业务图谱
        return {
            "error": str(exc),
            "business_map": {"company": intent.company, "segments": ["海外业务", "暖通空调", "消费电器"]},
            "evidence_source": [],
        }


def _call_monitoring_memory(session: Session, intent: Intent) -> dict:
    """调用 monitoring detector.list_theses 查询历史观点。"""
    try:
        from app.services.monitoring.detector import list_theses

        theses = list_theses(session)
        # 仅返回与当前公司相关的观点
        related = [t for t in theses if not intent.company or intent.company in t.company]
        return {
            "theses_count": len(related),
            "theses": [t.to_dict() for t in related[:5]],
            "evidence_source": [],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "theses_count": 0, "theses": [], "evidence_source": []}


def _call_financial_reasoning(session: Session, query: str, intent: Intent) -> dict:
    """调用 financial_reasoning.reason_about 识别逻辑风险/隐含假设/结论跳跃。

    将推理结果转为 Copilot 可展示的标准化输出。
    """
    try:
        from app.services.financial_reasoning import reason_about
        from app.services.financial_reasoning.schemas import ReasoningInput

        input_ = ReasoningInput(
            claim_text=query,
            claim={"original_text": query, "company": intent.company},
            company=intent.company,
            period="",
        )
        run = reason_about(session, input_)
        results = [r.to_dict() for r in run.results]
        return {
            "reasoning_run_id": run.run_id,
            "results_count": len(results),
            "results": results,
            "evidence_source": [],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "results_count": 0, "results": [], "evidence_source": []}


# ---------------------------------------------------------------------------
# 主入口：run_plan
# ---------------------------------------------------------------------------
def run_plan(
    session: Session,
    query: str,
    intent: Intent,
) -> ExecutionTrace:
    """根据意图规划并执行工具链，返回 ExecutionTrace。"""
    steps = plan_tools(intent)
    accumulated_evidence: list[dict] = []
    verification: dict = {}
    risk: dict = {}

    for step in steps:
        executed = execute_step(session, step, query, intent)

        # 累积证据
        ev = executed.output.get("evidence", [])
        for e in ev:
            if e not in accumulated_evidence:
                accumulated_evidence.append(e)

        if executed.tool == TOOL_VERIFICATION:
            verification = {
                "verification_status": executed.output.get("verification_status", ""),
                "confidence": executed.output.get("confidence", 0.5),
                "evidence_count": len(executed.output.get("evidence", [])),
            }
        elif executed.tool == TOOL_RISK_ENGINE:
            ra = executed.output.get("risk_assessment", {})
            risk = {
                "risk_score": ra.get("risk_score", 0.0),
                "risk_level": ra.get("risk_level", "LOW"),
                "risk_type": ra.get("risk_type", ""),
                "risk_reason": ra.get("risk_reason", []),
            }

    return ExecutionTrace(
        steps=steps,
        evidence=_summarize_evidence(accumulated_evidence),
        verification=verification,
        risk=risk,
    )


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _extract_sources(evidence: list[dict]) -> list[dict]:
    sources = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        sources.append({
            "block_id": ev.get("block_id") or ev.get("evidence_id"),
            "page_number": ev.get("page_number"),
            "document_id": ev.get("document_id"),
            "text": (ev.get("text") or ev.get("block_text") or "")[:200],
            "score": ev.get("final_score") or ev.get("score") or 0.0,
        })
    return sources


def _summarize_evidence(evidence: list[dict]) -> list[dict]:
    seen = set()
    summary = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        key = ev.get("block_id") or ev.get("evidence_id") or str(ev)
        if key in seen:
            continue
        seen.add(key)
        summary.append({
            "document": ev.get("document_id") or ev.get("source") or "未知文档",
            "page": ev.get("page_number") or ev.get("page") or "?",
            "content": (ev.get("text") or ev.get("block_text") or "")[:300],
            "block_id": ev.get("block_id") or ev.get("evidence_id"),
        })
    return summary


__all__ = [
    "plan_tools",
    "execute_step",
    "run_plan",
]
