"""FinProof Arena Judge（Phase 19，任务书 §4 Judge）。

综合：Analyst 质量 / Skeptic 发现能力 / Auditor 可靠性。
评分权重：Evidence 30% / Reasoning 25% / Risk Detection 25% / Efficiency 10% / Safety 10%。
输出 ArenaScore 0-100。
"""

from __future__ import annotations

from typing import Any

from app.services.agent_arena.schemas import (
    AnalystViewpoint,
    ArenaScore,
    AuditorReport,
    ScoreBreakdown,
    SkepticChallenge,
    _now_iso,
    contains_forbidden_content,
)


# 评分权重（任务书 §4）
SCORE_WEIGHTS = {
    "evidence": 0.30,
    "reasoning": 0.25,
    "risk_detection": 0.25,
    "efficiency": 0.10,
    "safety": 0.10,
}


def score_arena(
    viewpoints: list[AnalystViewpoint],
    challenges: list[SkepticChallenge],
    auditor: AuditorReport,
    tool_call_count: int,
) -> ArenaScore:
    """评判综合评分：5 项子分 + Final Arena Score。"""

    # Evidence Score：Analyst 观点证据覆盖率 × 100
    grounded = sum(1 for v in viewpoints if v.evidence and not v.unsupported)
    evidence_ratio = grounded / len(viewpoints) if viewpoints else 0.0
    evidence_score = ScoreBreakdown(
        score=evidence_ratio * 100.0,
        notes=f"grounded viewpoints {grounded}/{len(viewpoints)}",
    )

    # Reasoning Score：Auditor logical_consistency × 100 + Skeptic 命中逻辑类挑战加成
    logic_challenges = sum(1 for c in challenges if c.valid and c.challenge_type in ("Overstatement", "Missing Evidence"))
    reasoning_score = ScoreBreakdown(
        score=auditor.logical_consistency * 80.0 + min(logic_challenges * 10.0, 20.0),
        notes=f"logical_consistency={auditor.logical_consistency:.2f} logic_challenges={logic_challenges}",
    )

    # Risk Detection Score：Auditor risk_completeness × 100 + Skeptic 命中风险类挑战加成
    risk_challenges = sum(1 for c in challenges if c.valid and c.challenge_type in ("Unsupported Claim", "Contradictory Facts", "Growth Quality Problem"))
    risk_detection_score = ScoreBreakdown(
        score=auditor.risk_completeness * 70.0 + min(risk_challenges * 15.0, 30.0),
        notes=f"risk_completeness={auditor.risk_completeness:.2f} risk_challenges={risk_challenges}",
    )

    # Efficiency Score：工具调用效率（合理区间 5-15 次为满分，过多冗余扣分）
    if tool_call_count == 0:
        eff_score = 0.0
        eff_notes = "无工具调用"
    elif tool_call_count <= 15:
        eff_score = 100.0
        eff_notes = f"calls={tool_call_count}（合理区间）"
    else:
        eff_score = max(0.0, 100.0 - (tool_call_count - 15) * 5.0)
        eff_notes = f"calls={tool_call_count}（冗余扣分）"
    efficiency_score = ScoreBreakdown(score=eff_score, notes=eff_notes)

    # Safety Score：禁止词零容忍 + 无幻觉
    all_texts = []
    for v in viewpoints:
        all_texts.append(v.claim)
    for c in challenges:
        all_texts.append(c.counter_claim)
        all_texts.append(c.risk)
    for i in auditor.issues:
        all_texts.append(i.description)
    forbidden_hits = sum(1 for t in all_texts if contains_forbidden_content(t))
    hallucination_vp = sum(1 for v in viewpoints if v.unsupported and not v.evidence)
    if forbidden_hits > 0:
        safety_score = ScoreBreakdown(score=0.0, notes=f"禁止词命中 {forbidden_hits} 次（零容忍）")
    else:
        safety_score = ScoreBreakdown(
            score=max(0.0, 100.0 - hallucination_vp * 20.0),
            notes=f"无禁止词 · 无依据观点 {hallucination_vp}",
        )

    # Analyst 质量：证据覆盖 + 置信度合理
    avg_confidence = sum(v.confidence for v in viewpoints) / len(viewpoints) if viewpoints else 0.0
    analyst_quality = ScoreBreakdown(
        score=evidence_ratio * 70.0 + avg_confidence * 30.0,
        notes=f"evidence_ratio={evidence_ratio:.2f} avg_confidence={avg_confidence:.2f}",
    )

    # Skeptic 发现能力：成立挑战数 / 可挑战观点数
    challengeable = sum(1 for v in viewpoints if v.unsupported or any(kw in v.claim for kw in ("核心", "增长", "领先", "利润")))
    valid_count = sum(1 for c in challenges if c.valid)
    skeptic_detection = ScoreBreakdown(
        score=(valid_count / challengeable * 100.0) if challengeable else 50.0,
        notes=f"valid_challenges={valid_count}/{challengeable}",
    )

    # Auditor 可靠性：audit_score
    auditor_reliability = ScoreBreakdown(
        score=auditor.audit_score,
        notes=f"audit_score={auditor.audit_score:.2f} issues={len(auditor.issues)}",
    )

    # Final Arena Score = 5 项加权
    final = (
        evidence_score.score * SCORE_WEIGHTS["evidence"]
        + reasoning_score.score * SCORE_WEIGHTS["reasoning"]
        + risk_detection_score.score * SCORE_WEIGHTS["risk_detection"]
        + efficiency_score.score * SCORE_WEIGHTS["efficiency"]
        + safety_score.score * SCORE_WEIGHTS["safety"]
    )

    return ArenaScore(
        analyst_quality=analyst_quality,
        skeptic_detection=skeptic_detection,
        auditor_reliability=auditor_reliability,
        evidence_score=evidence_score,
        reasoning_score=reasoning_score,
        risk_detection_score=risk_detection_score,
        efficiency_score=efficiency_score,
        safety_score=safety_score,
        final_arena_score=final,
    )


def decide_winner(score: ArenaScore, viewpoints: list[AnalystViewpoint], challenges: list[SkepticChallenge], auditor: AuditorReport) -> str:
    """判定辩论胜负（仅辩论胜负，非投资建议）。

    Skeptic 命中率高（成立挑战多）→ skeptic；Analyst 证据覆盖高且挑战少 → analyst；否则 tie。
    """
    challengeable = sum(1 for v in viewpoints if v.unsupported or any(kw in v.claim for kw in ("核心", "增长", "领先", "利润")))
    valid_count = len(auditor.valid_challenges)
    if challengeable and valid_count / challengeable >= 0.5:
        return "skeptic"
    if score.evidence_score.score >= 80.0 and valid_count <= 1:
        return "analyst"
    return "tie"


__all__ = ["SCORE_WEIGHTS", "score_arena", "decide_winner"]
