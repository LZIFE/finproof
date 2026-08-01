"""FinProof Skeptic Agent（Phase 19，任务书 §2 Skeptic Agent）。

挑战 Analyst，寻找：
- Unsupported Claim      无依据主张
- Overstatement          夸大
- Missing Evidence        缺证据
- Contradictory Facts    事实冲突
- Growth Quality Problem  增长质量

调用：Verification / Reasoning / Risk。
输出：counter_claim / missing_evidence / risk。
所有反驳必须基于 Evidence。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.agent_arena.schemas import (
    AnalystViewpoint,
    ArenaMessage,
    CHALLENGE_CONTRADICTORY_FACTS,
    CHALLENGE_GROWTH_QUALITY,
    CHALLENGE_MISSING_EVIDENCE,
    CHALLENGE_OVERSTATEMENT,
    CHALLENGE_UNSUPPORTED_CLAIM,
    EvidenceRef,
    PHASE_SKEPTIC_ATTACKS,
    ROLE_SKEPTIC,
    SkepticChallenge,
    _now_iso,
    contains_forbidden_content,
    risk_level_of,
)


# 启发词库
_OVERSTATEMENT_KW = ("核心", "引擎", "支柱", "领先", "长期优势", "确定性增长", "持续增长")
_GROWTH_RISK_KW = ("现金流下降", "现金流同比下降", "应收上升", "应收增", "存货增", "毛利率下降", "利润率下降")
_CONTRADICTION_NEG_KW = ("下降", "下滑", "减少", "收缩", "恶化", "回落", "降低")


def challenge_viewpoints(
    session: Session,
    viewpoints: list[AnalystViewpoint],
    company: str,
) -> tuple[list[SkepticChallenge], ArenaMessage]:
    """Skeptic 挑战 Analyst 观点：调用 Verification / Reasoning / Risk。"""
    challenges: list[SkepticChallenge] = []
    challenge_idx = 0

    for vp in viewpoints:
        # ① Unsupported Claim：无证据观点
        if vp.unsupported or not vp.evidence:
            challenge_idx += 1
            challenges.append(SkepticChallenge(
                challenge_id=f"SC-{challenge_idx:03d}",
                target_viewpoint_id=vp.viewpoint_id,
                challenge_type=CHALLENGE_UNSUPPORTED_CLAIM,
                counter_claim=f"观点「{vp.claim[:50]}」缺乏证据支持，不应作为研究结论。",
                missing_evidence="该观点未绑定任何 Evidence",
                risk="无依据主张",
                risk_score=70.0,
                valid=True,
            ))
            continue

        # ② Overstatement：含强表述但证据弱
        if any(kw in vp.claim for kw in _OVERSTATEMENT_KW) and vp.confidence < 0.85:
            challenge_idx += 1
            challenges.append(SkepticChallenge(
                challenge_id=f"SC-{challenge_idx:03d}",
                target_viewpoint_id=vp.viewpoint_id,
                challenge_type=CHALLENGE_OVERSTATEMENT,
                counter_claim=f"观点含强表述但证据置信度仅 {vp.confidence}，构成夸大。",
                missing_evidence="需更强证据支撑强表述",
                risk="夸大风险",
                risk_score=60.0,
                evidence=vp.evidence,
                valid=True,
            ))

        # ③ Missing Evidence：claim 含指标但证据 text 不含对应指标
        missing_metric = _detect_missing_metric(vp)
        if missing_metric:
            challenge_idx += 1
            challenges.append(SkepticChallenge(
                challenge_id=f"SC-{challenge_idx:03d}",
                target_viewpoint_id=vp.viewpoint_id,
                challenge_type=CHALLENGE_MISSING_EVIDENCE,
                counter_claim=f"观点提及「{missing_metric}」但证据未覆盖该指标。",
                missing_evidence=f"缺「{missing_metric}」指标证据",
                risk="证据缺失",
                risk_score=55.0,
                evidence=vp.evidence,
                valid=True,
            ))

        # ④ Contradictory Facts：证据 text 含负向词（与 claim 正向冲突）
        contradiction = _detect_contradiction(vp)
        if contradiction:
            challenge_idx += 1
            challenges.append(SkepticChallenge(
                challenge_id=f"SC-{challenge_idx:03d}",
                target_viewpoint_id=vp.viewpoint_id,
                challenge_type=CHALLENGE_CONTRADICTORY_FACTS,
                counter_claim=f"证据含反向表述：{contradiction[:60]}",
                missing_evidence="需核对同口径数据",
                risk="事实冲突",
                risk_score=75.0,
                evidence=vp.evidence,
                valid=True,
            ))

        # ⑤ Growth Quality Problem：claim 含增长但证据含现金流/应收/存货恶化
        if "增长" in vp.claim or "营收" in vp.claim:
            growth_risk = _detect_growth_quality_risk(vp)
            if growth_risk:
                challenge_idx += 1
                challenges.append(SkepticChallenge(
                    challenge_id=f"SC-{challenge_idx:03d}",
                    target_viewpoint_id=vp.viewpoint_id,
                    challenge_type=CHALLENGE_GROWTH_QUALITY,
                    counter_claim=f"营收增长但 {growth_risk}，增长质量存疑。",
                    missing_evidence="需现金流/应收/存货/毛利率多期数据",
                    risk="增长质量低",
                    risk_score=80.0,
                    evidence=vp.evidence,
                    valid=True,
                ))

    # 调用 Reasoning Engine 做逻辑层补充挑战
    reasoning_challenges = _reasoning_challenges(session, viewpoints, company)
    challenges.extend(reasoning_challenges)

    # 护栏：反驳不含禁止词
    valid_challenges = []
    for c in challenges:
        if contains_forbidden_content(c.counter_claim) or contains_forbidden_content(c.risk):
            c.valid = False
        valid_challenges.append(c)

    msg = ArenaMessage(
        message_id="MSG-002",
        role=ROLE_SKEPTIC,
        phase=PHASE_SKEPTIC_ATTACKS,
        content=f"Skeptic 对 {len(viewpoints)} 个观点发起 {len(valid_challenges)} 次挑战（{sum(1 for c in valid_challenges if c.valid)} 次成立）。",
        challenges=valid_challenges,
        timestamp=_now_iso(),
    )
    return valid_challenges, msg


# ---------------------------------------------------------------------------
# 内部：调用 Reasoning Engine
# ---------------------------------------------------------------------------
def _reasoning_challenges(
    session: Session,
    viewpoints: list[AnalystViewpoint],
    company: str,
) -> list[SkepticChallenge]:
    """调用 Financial Reasoning Engine 识别逻辑漏洞转为挑战。"""
    out: list[SkepticChallenge] = []
    try:
        from app.services.financial_reasoning import reason_about
        from app.services.financial_reasoning.schemas import ReasoningInput

        for vp in viewpoints[:3]:  # 仅对前3个观点做深度推理
            if not vp.evidence:
                continue
            inp = ReasoningInput(
                claim_text=vp.claim,
                claim={"original_text": vp.claim, "company": company},
                evidence_candidates=[
                    {"block_id": e.block_id, "text": e.text, "document_id": e.document_id}
                    for e in vp.evidence
                ],
                company=company,
            )
            run = reason_about(session, inp)
            idx_base = len(out) + 100
            for r in run.results:
                if r.status in ("OK",) and not r.logical_gap:
                    continue
                out.append(SkepticChallenge(
                    challenge_id=f"SC-R{idx_base:03d}",
                    target_viewpoint_id=vp.viewpoint_id,
                    challenge_type=CHALLENGE_OVERSTATEMENT if r.reasoning_type == "CONCLUSION_OVERREACH" else CHALLENGE_MISSING_EVIDENCE,
                    counter_claim=r.explanation or r.logical_gap,
                    missing_evidence=r.logical_gap,
                    risk=r.reasoning_type,
                    risk_score=float(r.confidence) * 100.0,
                    evidence=[EvidenceRef(block_id=eid) for eid in r.evidence_ids[:2]],
                    valid=True,
                ))
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------------------
# 内部：启发式检测
# ---------------------------------------------------------------------------
def _detect_missing_metric(vp: AnalystViewpoint) -> str:
    """claim 含某指标词但证据 text 不含 → 缺证据。"""
    metrics = ("现金流", "毛利率", "净利润", "应收", "存货", "海外利润", "海外业务利润")
    ev_blob = " ".join(e.text for e in vp.evidence)
    for m in metrics:
        if m in vp.claim and m not in ev_blob:
            return m
    return ""


def _detect_contradiction(vp: AnalystViewpoint) -> str:
    """证据含负向词且 claim 含正向词 → 冲突。"""
    claim_positive = any(k in vp.claim for k in ("增长", "上升", "改善", "提升", "增加"))
    if not claim_positive:
        return ""
    for e in vp.evidence:
        if any(k in e.text for k in _CONTRADICTION_NEG_KW):
            return e.text
    return ""


def _detect_growth_quality_risk(vp: AnalystViewpoint) -> str:
    """证据含现金流/应收/存货/毛利率恶化 → 增长质量风险。"""
    for e in vp.evidence:
        if any(k in e.text for k in _GROWTH_RISK_KW):
            return e.text[:60]
    return ""


__all__ = ["challenge_viewpoints"]
