"""FinProof Copilot Response Generator（Phase 15，任务书 §4）。

基于 ExecutionTrace 生成 Evidence First 回答。

要求（任务书 §4）：
- 回答必须包含：Summary / Evidence / Reasoning Result / Risk / Source
- 格式：{answer, evidence:[{document, page, content}], verification, risk_score}
- 禁止：投资建议 / 股票推荐 / 买卖判断

约束：不修改已有核心验证逻辑。
"""

from __future__ import annotations

from app.services.copilot.schemas import (
    CopilotResponse,
    ExecutionTrace,
    Intent,
    INTENT_COMPARISON_QUERY,
    INTENT_EVIDENCE_QUERY,
    INTENT_FACT_QUERY,
    INTENT_INVESTIGATION_REQUEST,
    INTENT_RISK_EXPLANATION,
    INTENT_UNKNOWN,
)


# ---------------------------------------------------------------------------
# 禁止输出类别（任务书 §4）
# ---------------------------------------------------------------------------
_FORBIDDEN_KW = ("建议买入", "建议卖出", "推荐股票", "应该买入", "应该卖出", "买卖判断")


def generate_response(
    query: str,
    intent: Intent,
    trace: ExecutionTrace,
) -> CopilotResponse:
    """根据意图与执行轨迹生成 CopilotResponse。

    所有结论必须基于 trace.evidence / trace.verification / trace.risk，
    不直接生成未经证据支持的信息。
    """
    answer = _build_answer(query, intent, trace)
    answer = _sanitize(answer)

    evidence = trace.evidence
    verification = trace.verification.get("verification_status", "INSUFFICIENT_EVIDENCE")
    risk_score = trace.risk.get("risk_score", 0.0)
    risk_level = trace.risk.get("risk_level", "LOW")
    risk_type = trace.risk.get("risk_type", "")
    source = _build_source(trace)

    return CopilotResponse(
        answer=answer,
        evidence=evidence,
        verification=verification,
        risk_score=risk_score,
        risk_level=risk_level,
        risk_type=risk_type,
        source=source,
        tool_trace=trace.steps,
        intent=intent,
    )


# ---------------------------------------------------------------------------
# Answer 生成（按意图分支，全部基于 trace）
# ---------------------------------------------------------------------------
def _build_answer(query: str, intent: Intent, trace: ExecutionTrace) -> str:
    """构造可解释回答（Summary）。"""
    evidence_count = len(trace.evidence)
    v_status = trace.verification.get("verification_status", "")
    risk_score = trace.risk.get("risk_score", 0.0)
    risk_level = trace.risk.get("risk_level", "LOW")
    company = intent.company or "该公司"

    if intent.intent_type == INTENT_FACT_QUERY:
        if evidence_count == 0:
            return f"针对「{query}」：未检索到直接证据支持，无法基于证据给出具体数值。建议查阅该公司年报原文。"
        # 取首条证据内容作为事实依据
        first_ev = trace.evidence[0] if trace.evidence else {}
        content_hint = (first_ev.get("content") or "")[:80]
        return (
            f"针对「{query}」：基于 {evidence_count} 条证据，"
            f"在{first_ev.get('document', '文档')}第{first_ev.get('page', '?')}页"
            f"检索到相关表述：「{content_hint}…」。"
            f"核验结论：{v_status or '待核验'}。"
        )

    if intent.intent_type == INTENT_RISK_EXPLANATION:
        reason = trace.risk.get("risk_reason", [])
        reason_str = "；".join(reason[:3]) if reason else "无具体风险原因"
        return (
            f"针对「{query}」：风险评分 {risk_score}（{risk_level}），"
            f"风险类型 {trace.risk.get('risk_type', '-') or '-'}。"
            f"风险原因：{reason_str}。"
            f"基于 {evidence_count} 条证据。"
        )

    if intent.intent_type == INTENT_EVIDENCE_QUERY:
        if evidence_count == 0:
            return f"针对「{query}」：未检索到证据来源，该结论暂无证据支持。"
        sources = ", ".join(
            f"{ev.get('document', '?')}第{ev.get('page', '?')}页"
            for ev in trace.evidence[:3]
        )
        return (
            f"针对「{query}」：该结论依据 {evidence_count} 条证据，"
            f"来源：{sources}。核验结论：{v_status or '待核验'}。"
        )

    if intent.intent_type == INTENT_COMPARISON_QUERY:
        theses_count = 0
        for step in trace.steps:
            if step.output.get("theses_count"):
                theses_count = step.output.get("theses_count", 0)
                break
        return (
            f"针对「{query}」：查询历史投资观点 {theses_count} 条，"
            f"当前风险评分 {risk_score}（{risk_level}）。"
            f"基于 {evidence_count} 条证据对比。"
        )

    if intent.intent_type == INTENT_INVESTIGATION_REQUEST:
        segments = []
        for step in trace.steps:
            if step.output.get("business_map"):
                bm = step.output["business_map"]
                segs = bm.get("segments", []) if isinstance(bm, dict) else []
                segments = segs
                break
        seg_str = "、".join(segments[:3]) if segments else "未识别业务分部"
        return (
            f"针对「{query}」：调查{company}业务结构（{seg_str}），"
            f"检索 {evidence_count} 条证据，"
            f"核验结论 {v_status or '待核验'}，"
            f"风险评分 {risk_score}（{risk_level}）。"
            f"调查基于证据，不输出投资建议。"
        )

    # INTENT_UNKNOWN 兜底
    return (
        f"针对「{query}」：未明确识别意图，"
        f"基于 {evidence_count} 条证据，核验结论 {v_status or '待核验'}，"
        f"风险评分 {risk_score}（{risk_level}）。"
    )


def _build_source(trace: ExecutionTrace) -> str:
    """构造来源说明（Source）：工具链 + 证据数。"""
    tools = [s.tool for s in trace.steps]
    return f"工具链：{', '.join(tools)}；证据数：{len(trace.evidence)}"


def _sanitize(text: str) -> str:
    """禁止输出投资建议/股票推荐/买卖判断（任务书 §4）。

    若检测到禁止关键词，替换为中性表述。
    """
    out = text
    for kw in _FORBIDDEN_KW:
        if kw in out:
            out = out.replace(kw, "[不输出投资建议]")
    return out


__all__ = ["generate_response"]
