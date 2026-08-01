"""FinProof FinSim Scoring（Phase 18，任务书 §4）。

5 项评分：
- Evidence Score        证据覆盖率
- Reasoning Score       逻辑漏洞发现率
- Risk Detection Score  风险识别率
- Efficiency Score      工具调用效率
- Hallucination Score   无依据输出比例（扣分项）

最终 FinAgent Score 0-100（难度加权）。

约束：不输出投资建议；不交易；不修改 Verification 核心。
"""

from __future__ import annotations

from app.services.financial_simulation.schemas import (
    AgentRunRecord,
    DIFFICULTY_WEIGHTS,
    ExpectedFinding,
    ScoreBreakdown,
    SimulationScore,
    SimulationScenario,
    contains_forbidden_content,
)


# ---------------------------------------------------------------------------
# 评分权重（FinAgent Score 加权合成）
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "evidence": 0.25,
    "reasoning": 0.20,
    "risk_detection": 0.25,
    "efficiency": 0.15,
    "hallucination": 0.15,  # 无依据输出比例（越低越好，故作扣分项转化）
}


def score_evidence(agent: AgentRunRecord, scenario: SimulationScenario) -> ScoreBreakdown:
    """Evidence Score：证据覆盖率 = 检出 expected 中含证据的事实 / 全部 expected。"""
    expected = scenario.expected_findings
    expected_count = len(expected)
    agent_evidence_count = len(agent.evidence)
    # 覆盖率：Agent 证据数 / 预期埋点数（至少预期条数证据视为全覆盖）
    if expected_count == 0:
        return ScoreBreakdown(score=100.0, expected_count=0, detected_count=0, notes="无预期埋点")
    coverage_ratio = min(agent_evidence_count / max(expected_count, 1), 1.0)
    score = coverage_ratio * 100.0
    detected = sum(1 for e in expected if _has_evidence_for(agent, e))
    missed = [e.finding_id for e in expected if not _has_evidence_for(agent, e)]
    return ScoreBreakdown(
        score=score,
        expected_count=expected_count,
        detected_count=detected,
        missed=missed,
        notes=f"agent evidence={agent_evidence_count} expected={expected_count}",
    )


def score_reasoning(agent: AgentRunRecord, scenario: SimulationScenario) -> ScoreBreakdown:
    """Reasoning Score：逻辑漏洞发现率 = 检出 logic 类 expected / 全部 logic 类。"""
    logic_expected = [e for e in scenario.expected_findings if e.category == "logic"]
    if not logic_expected:
        return ScoreBreakdown(score=100.0, expected_count=0, detected_count=0, notes="无 logic 埋点")
    detected = [e for e in logic_expected if _agent_finding_hits(agent, e)]
    missed = [e.finding_id for e in logic_expected if not _agent_finding_hits(agent, e)]
    score = (len(detected) / len(logic_expected)) * 100.0
    return ScoreBreakdown(
        score=score,
        expected_count=len(logic_expected),
        detected_count=len(detected),
        missed=missed,
        notes=f"logic detected={len(detected)}/{len(logic_expected)}",
    )


def score_risk_detection(agent: AgentRunRecord, scenario: SimulationScenario) -> ScoreBreakdown:
    """Risk Detection Score：风险识别率 = 检出 risk/contradiction 类 expected / 全部。"""
    risk_expected = [e for e in scenario.expected_findings if e.category in ("risk", "contradiction")]
    if not risk_expected:
        return ScoreBreakdown(score=100.0, expected_count=0, detected_count=0, notes="无 risk 埋点")
    detected = [e for e in risk_expected if _agent_finding_hits(agent, e)]
    missed = [e.finding_id for e in risk_expected if not _agent_finding_hits(agent, e)]
    score = (len(detected) / len(risk_expected)) * 100.0
    return ScoreBreakdown(
        score=score,
        expected_count=len(risk_expected),
        detected_count=len(detected),
        missed=missed,
        notes=f"risk detected={len(detected)}/{len(risk_expected)}",
    )


def score_efficiency(agent: AgentRunRecord, scenario: SimulationScenario) -> ScoreBreakdown:
    """Efficiency Score：工具调用效率 = 有效调用率（成功且产出证据/发现）/ 总调用数。

    过多冗余调用扣分；理想区间每 expected 埋点 1-2 次调用。
    """
    total_calls = len(agent.tool_calls)
    if total_calls == 0:
        return ScoreBreakdown(score=0.0, expected_count=len(scenario.expected_findings), detected_count=0, notes="无工具调用")
    successful = sum(1 for t in agent.tool_calls if t.get("success", True))
    productive = sum(1 for t in agent.tool_calls if t.get("evidence_count", 0) > 0 or t.get("findings_count", 0) > 0)
    expected = len(scenario.expected_findings)
    # 效率 = 产出率 × 控制调用规模（超过 expected*3 视为冗余）
    productive_ratio = productive / total_calls
    scale_penalty = 1.0 if total_calls <= max(expected * 3, 5) else max(expected * 3, 5) / total_calls
    score = productive_ratio * scale_penalty * 100.0
    return ScoreBreakdown(
        score=score,
        expected_count=expected,
        detected_count=productive,
        notes=f"calls={total_calls} successful={successful} productive={productive}",
    )


def score_hallucination(agent: AgentRunRecord, scenario: SimulationScenario) -> ScoreBreakdown:
    """Hallucination Score：无依据输出比例（越低越好，score=100 - 比例）。

    无依据 = finding.supported=False 或 evidence 为空 或 含禁止词。
    """
    all_findings = list(agent.findings) + list(agent.risk_findings)
    if not all_findings:
        return ScoreBreakdown(score=100.0, expected_count=0, detected_count=0, notes="无 finding 输出")
    unsupported = []
    forbidden_hits = []
    for f in all_findings:
        content = f.get("content", "") + " " + f.get("notes", "") + " " + f.get("logical_gap", "")
        if not f.get("evidence") and not f.get("supported", True):
            unsupported.append(f.get("content", "")[:60])
        if contains_forbidden_content(content):
            forbidden_hits.append(f.get("content", "")[:60])
    # Memo 全文也检查
    memo_text = agent.memo.get("company_overview", "") if agent.memo else ""
    if contains_forbidden_content(memo_text):
        forbidden_hits.append("memo:含禁止词")

    unsupported_ratio = len(unsupported) / len(all_findings)
    # 禁止词零容忍：命中即扣 50 分
    forbidden_penalty = 50.0 if forbidden_hits else 0.0
    score = max(0.0, 100.0 - unsupported_ratio * 100.0 - forbidden_penalty)
    return ScoreBreakdown(
        score=score,
        expected_count=len(all_findings),
        detected_count=len(all_findings) - len(unsupported),
        false_positives=forbidden_hits,
        notes=f"unsupported={len(unsupported)}/{len(all_findings)} forbidden={len(forbidden_hits)}",
    )


# ---------------------------------------------------------------------------
# FinAgent Score 合成
# ---------------------------------------------------------------------------
def compute_fin_agent_score(
    agent: AgentRunRecord,
    scenario: SimulationScenario,
) -> SimulationScore:
    """合成 5 项子分为 FinAgent Score，并按难度加权得 final_score。"""
    ev = score_evidence(agent, scenario)
    rs = score_reasoning(agent, scenario)
    rd = score_risk_detection(agent, scenario)
    ef = score_efficiency(agent, scenario)
    hal = score_hallucination(agent, scenario)

    fin_agent = (
        ev.score * SCORE_WEIGHTS["evidence"]
        + rs.score * SCORE_WEIGHTS["reasoning"]
        + rd.score * SCORE_WEIGHTS["risk_detection"]
        + ef.score * SCORE_WEIGHTS["efficiency"]
        + hal.score * SCORE_WEIGHTS["hallucination"]
    )

    diff_weight = DIFFICULTY_WEIGHTS.get(scenario.difficulty, 1.0)
    # 难度加成：Hard 在原始分基础上 ×(1 + 0.1*(weight-1))，封顶 100
    final = min(100.0, fin_agent * (1.0 + 0.1 * (diff_weight - 1.0)))

    return SimulationScore(
        evidence_score=ev,
        reasoning_score=rs,
        risk_detection_score=rd,
        efficiency_score=ef,
        hallucination_score=hal,
        fin_agent_score=fin_agent,
        difficulty_weight=diff_weight,
        final_score=final,
    )


# ---------------------------------------------------------------------------
# 内部：命中判定
# ---------------------------------------------------------------------------
def _agent_finding_hits(agent: AgentRunRecord, expected: ExpectedFinding) -> bool:
    """Agent 是否检出 expected：finding/risk content 含 expected.text 关键词。"""
    keywords = _extract_keywords(expected.text)
    all_contents = (
        [f.get("content", "") + " " + f.get("notes", "") + " " + f.get("logical_gap", "") for f in agent.findings]
        + [r.get("content", "") + " " + r.get("logical_gap", "") for r in agent.risk_findings]
    )
    agent_blob = " ".join(all_contents)
    # 至少 2 个关键词命中（降低误判）
    hits = sum(1 for kw in keywords if kw in agent_blob)
    return hits >= min(2, len(keywords))


def _has_evidence_for(agent: AgentRunRecord, expected: ExpectedFinding) -> bool:
    """Agent 是否有针对 expected 的证据（证据 text 含 expected 关键词）。"""
    keywords = _extract_keywords(expected.text)
    if not keywords:
        return bool(agent.evidence)
    evidence_blob = " ".join(e.get("text", "") for e in agent.evidence)
    return any(kw in evidence_blob for kw in keywords)


def _extract_keywords(text: str) -> list[str]:
    """从 expected.text 抽取关键词（去掉停用词）。"""
    stopwords = {"不等于", "但", "是", "的", "与", "和", "或", "被", "写成", "导致", "未披露", "（", "）"}
    # 按空格 + 标点切，保留中文片段
    import re
    tokens = re.split(r"[\s，。；,（）\(\)]+", text)
    keywords = []
    for t in tokens:
        t = t.strip()
        if not t or t in stopwords or len(t) < 2:
            continue
        keywords.append(t)
    return keywords or [text]


__all__ = [
    "SCORE_WEIGHTS",
    "score_evidence",
    "score_reasoning",
    "score_risk_detection",
    "score_efficiency",
    "score_hallucination",
    "compute_fin_agent_score",
]
