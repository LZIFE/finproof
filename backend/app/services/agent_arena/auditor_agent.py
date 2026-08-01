"""FinProof Auditor Agent（Phase 19，任务书 §3 Auditor Agent）。

最终审计，检查：
- Evidence Coverage        证据覆盖率
- Logical Consistency      逻辑一致性
- Risk Completeness        风险完整性

输出：audit_score + issues。
验证双方（Analyst 观点 vs Skeptic 挑战），判定 SkepticChallenge 是否成立。
"""

from __future__ import annotations

from typing import Any

from app.services.agent_arena.schemas import (
    AnalystViewpoint,
    ArenaMessage,
    AuditorIssue,
    AuditorReport,
    EvidenceRef,
    PHASE_AUDITOR_VERIFIES,
    ROLE_AUDITOR,
    SkepticChallenge,
    _now_iso,
)


def audit_debate(
    viewpoints: list[AnalystViewpoint],
    challenges: list[SkepticChallenge],
    all_evidence: list[EvidenceRef],
) -> tuple[AuditorReport, ArenaMessage]:
    """Auditor 审计：验证双方，判定挑战成立性，产出 audit_score + issues。"""
    issues: list[AuditorIssue] = []
    valid_challenges: list[str] = []
    invalid_challenges: list[str] = []

    # ① Evidence Coverage：Analyst 观点证据覆盖率
    grounded_vp = sum(1 for v in viewpoints if v.evidence and not v.unsupported)
    evidence_coverage = grounded_vp / len(viewpoints) if viewpoints else 0.0
    if evidence_coverage < 1.0:
        issues.append(AuditorIssue(
            issue_id="AI-001",
            issue_type="evidence_coverage",
            description=f"Analyst 观点证据覆盖率 {evidence_coverage:.2f}，存在无依据观点。",
            affected="analyst",
        ))

    # ② Logical Consistency：观点间是否存在逻辑冲突
    inconsistency = _detect_viewpoint_inconsistency(viewpoints)
    if inconsistency:
        issues.append(AuditorIssue(
            issue_id="AI-002",
            issue_type="logical_consistency",
            description=inconsistency,
            affected="analyst",
        ))
    logical_consistency = 1.0 if not inconsistency else 0.5

    # ③ 判定 SkepticChallenge 成立性
    for c in challenges:
        if not c.counter_claim and not c.missing_evidence:
            invalid_challenges.append(c.challenge_id)
            c.valid = False
            continue
        # 针对无证据观点的挑战 → 成立
        target_vp = next((v for v in viewpoints if v.viewpoint_id == c.target_viewpoint_id), None)
        if c.challenge_type == "Unsupported Claim" and target_vp and target_vp.unsupported:
            valid_challenges.append(c.challenge_id)
            c.valid = True
        elif c.evidence or c.missing_evidence:
            valid_challenges.append(c.challenge_id)
            c.valid = True
        else:
            invalid_challenges.append(c.challenge_id)
            c.valid = False

    # ④ Risk Completeness：Skeptic 是否覆盖全部可挑战观点
    challengeable_vp = sum(1 for v in viewpoints if v.unsupported or any(kw in v.claim for kw in ("核心", "增长", "领先", "利润")))
    challenged_vp = sum(1 for v in viewpoints if any(c.target_viewpoint_id == v.viewpoint_id for c in challenges))
    risk_completeness = challenged_vp / challengeable_vp if challengeable_vp else 1.0
    if risk_completeness < 1.0:
        issues.append(AuditorIssue(
            issue_id="AI-003",
            issue_type="risk_completeness",
            description=f"Skeptic 仅覆盖 {challenged_vp}/{challengeable_vp} 个可挑战观点。",
            affected="skeptic",
        ))

    # ⑤ 无效挑战也记 issue
    if invalid_challenges:
        issues.append(AuditorIssue(
            issue_id="AI-004",
            issue_type="logical_consistency",
            description=f"Skeptic 有 {len(invalid_challenges)} 次无效挑战（无反驳内容）。",
            affected="skeptic",
        ))

    # audit_score = 三项加权
    audit_score = (
        evidence_coverage * 40.0
        + logical_consistency * 30.0
        + risk_completeness * 30.0
    )

    report = AuditorReport(
        audit_score=audit_score,
        issues=issues,
        evidence_coverage=evidence_coverage,
        logical_consistency=logical_consistency,
        risk_completeness=risk_completeness,
        valid_challenges=valid_challenges,
        invalid_challenges=invalid_challenges,
    )

    msg = ArenaMessage(
        message_id="MSG-003",
        role=ROLE_AUDITOR,
        phase=PHASE_AUDITOR_VERIFIES,
        content=f"Auditor 审计：覆盖率 {evidence_coverage:.2f} · 一致性 {logical_consistency:.2f} · 风险完整性 {risk_completeness:.2f} · 挑战成立 {len(valid_challenges)}/{len(challenges)} · issues {len(issues)}。",
        audit=report,
        timestamp=_now_iso(),
    )
    return report, msg


# ---------------------------------------------------------------------------
# 内部：观点间一致性检测
# ---------------------------------------------------------------------------
def _detect_viewpoint_inconsistency(viewpoints: list[AnalystViewpoint]) -> str:
    """检测 Analyst 观点间是否存在同一指标的正/负向冲突。"""
    pos_metrics: dict[str, str] = {}
    neg_metrics: dict[str, str] = {}
    neg_kw = ("下降", "下滑", "减少", "收缩", "恶化", "回落", "降低")
    pos_kw = ("增长", "上升", "改善", "提升", "增加")
    for v in viewpoints:
        for m in ("海外利润", "净利润", "现金流", "毛利率"):
            if m not in v.claim:
                continue
            if any(k in v.claim for k in pos_kw):
                pos_metrics[m] = v.viewpoint_id
            if any(k in v.claim for k in neg_kw):
                neg_metrics[m] = v.viewpoint_id
    for m in pos_metrics:
        if m in neg_metrics:
            return f"指标「{m}」在观点 {pos_metrics[m]}（正向）与 {neg_metrics[m]}（负向）间存在冲突"
    return ""


__all__ = ["audit_debate"]
