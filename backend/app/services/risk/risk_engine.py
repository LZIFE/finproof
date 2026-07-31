"""Risk Engine（Phase 6）：将 Verification Result 转换为 Risk Score + Risk Level + Risk Explanation。

- 不改变已有 Verification 逻辑（Verification 判断事实，Risk 解释风险程度）；
- Evidence First：评分仅基于 verification_status / verification_type / confidence /
  evidence_quality / calculation_detail / claim importance，规则可解释；
- 不使用 LLM 自由判断。
"""

import json

from sqlalchemy.orm import Session

from app.models.audit import AuditReport
from app.services.risk.risk_rules import (
    FINANCIAL_TYPES,
    IMPORTANCE_ADJUST,
    RISK_EVIDENCE,
    RISK_FINANCIAL,
    RISK_FORECAST,
    RISK_SEMANTIC,
    SEMANTIC_TYPES,
    claim_importance_of,
    classify_risk_type,
    is_forecast_claim,
    score_range,
)
from app.services.risk.schemas import AuditRiskReport, RiskAssessment
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)

# 证据质量代理（基于核验类型：财务表核验 = 高质量证据；语义核验 = 叙述性证据；无 = 0.3）
_EVIDENCE_QUALITY_BY_TYPE = {t: 1.0 for t in FINANCIAL_TYPES}
for t in SEMANTIC_TYPES:
    _EVIDENCE_QUALITY_BY_TYPE[t] = 0.6

_LEVEL_THRESHOLDS = (30.0, 65.0)  # <30 LOW, 30-65 MEDIUM, >65 HIGH


def _evidence_quality_of(verification_type: str) -> float:
    return _EVIDENCE_QUALITY_BY_TYPE.get(verification_type, 0.3)


def _level_of(score: float) -> str:
    if score < _LEVEL_THRESHOLDS[0]:
        return "LOW"
    if score <= _LEVEL_THRESHOLDS[1]:
        return "MEDIUM"
    return "HIGH"


def assess_claim(
    claim: dict,
    verification: dict,
) -> RiskAssessment:
    """单条主张风险评分：base（按状态区间）→ 调整（重要性/置信度/证据质量/预测）→ clamp → 可解释 reason。"""
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or verification.get("claim_id") or "?"
    status = verification.get("verification_status") or STATUS_INSUFFICIENT
    vtype = verification.get("verification_type") or ""
    confidence = verification.get("confidence") or 0.5
    calc = verification.get("calculation_detail") or {}

    lo, hi = score_range(status)
    score = (lo + hi) / 2.0
    reasons: list[str] = []
    reasons.append(f"核验结论 {status}（{vtype}），基准风险 {score:.0f}")

    # 主张重要性调整
    importance = claim_importance_of(claim)
    imp_adj = IMPORTANCE_ADJUST[importance]
    score += imp_adj
    if imp_adj:
        reasons.append(f"主张重要性 {importance}（调整 {imp_adj:+.0f}）")

    # 置信度调整：高置信的判定更确定（REFUTED 风险确认、SUPPORTED 风险缓解）
    conf_adj = round((confidence - 0.5) * 24.0, 1)
    if status in (STATUS_REFUTED, STATUS_INSUFFICIENT, STATUS_UNABLE):
        score += max(conf_adj, 0.0)
        if conf_adj > 0:
            reasons.append(f"核验置信度 {confidence:.2f}（风险确认 {conf_adj:+.1f}）")
    elif status == STATUS_SUPPORTED:
        score += min(conf_adj, 0.0)
        if conf_adj < 0:
            reasons.append(f"核验置信度 {confidence:.2f}（风险缓解 {conf_adj:+.1f}）")

    # 证据质量调整（证据越扎实，判定越可信）
    eq = _evidence_quality_of(vtype)
    if status in (STATUS_REFUTED,):
        eq_adj = round((eq - 0.6) * 12.0, 1)  # 强证据 → 错误确凿 +；弱证据 → 判定存疑 -
        score += eq_adj
        if eq_adj:
            reasons.append(f"证据质量 {eq:.1f}（调整 {eq_adj:+.1f}）")
    elif status in (STATUS_INSUFFICIENT, STATUS_UNABLE):
        eq_adj = round((0.6 - eq) * 12.0, 1)  # 弱证据 → 证据风险 +；强证据缺席更可疑
        score += max(eq_adj, 0.0)

    # 预测类主张：被描述为事实 / 缺历史支持 → FORECAST_RISK 加分
    forecast = is_forecast_claim(claim)
    if forecast:
        score += 15.0
        reasons.append("预测类主张（缺少历史支持或被描述为事实）")

    # clamp 到状态的合法区间
    score = max(lo, min(hi, round(score, 1)))

    # 风险类型
    rtype = RISK_FORECAST if (forecast and status in (STATUS_PARTIALLY_SUPPORTED, STATUS_SUPPORTED)) else classify_risk_type(claim, verification)

    # 计算明细可解释
    if calc.get("calculated_growth_pp") is not None and calc.get("claimed_growth_pp") is not None:
        diff = abs(calc["calculated_growth_pp"] - calc["claimed_growth_pp"])
        reasons.append(f"计算增长率 {calc['calculated_growth_pp']}% 与主张 {calc['claimed_growth_pp']}% 偏差 {diff:.2f}pp")

    return RiskAssessment(
        claim_id=claim_id,
        risk_score=score,
        risk_level=_level_of(score),
        risk_type=rtype,
        risk_reason=reasons,
        verification_status=status,
        verification_type=vtype,
        confidence=confidence,
        evidence_quality=eq,
        claim_importance=importance,
    )


def assess_audit(session: Session, audit_id: int, persist: bool = True) -> AuditRiskReport:
    """对一次审计的所有核验结果生成风险评分，并计算整体风险。"""
    row = session.get(AuditReport, audit_id)
    if row is None:
        raise LookupError(f"审计任务不存在: {audit_id}")
    report = json.loads(row.report_json or "{}")
    verification_results = report.get("verification_results", [])

    assessments: list[RiskAssessment] = []
    for v in verification_results:
        claim = {"claim_id": v.get("claim_id")}
        # 重要性兜底：数字类核验 → HIGH
        vtype = v.get("verification_type") or ""
        if vtype in FINANCIAL_TYPES:
            claim["claim_type"] = "FINANCIAL_VALUE"
        elif vtype in SEMANTIC_TYPES:
            claim["claim_type"] = "OPINION"
        assessments.append(assess_claim(claim, v))

    if persist:
        from app.models.risk import RiskAssessmentRow

        for a in assessments:
            session.add(
                RiskAssessmentRow(
                    audit_id=audit_id,
                    claim_id=a.claim_id,
                    verification_status=a.verification_status,
                    verification_type=a.verification_type,
                    risk_score=a.risk_score,
                    risk_level=a.risk_level,
                    risk_type=a.risk_type,
                    risk_reason=json.dumps(a.risk_reason, ensure_ascii=False),
                )
            )
        session.commit()

    # 整体风险：0.5 × 最高单项 + 0.5 × 风险点（非 SUPPORTED）平均（可解释公式）
    scores = [a.risk_score for a in assessments]
    risk_points = [a.risk_score for a in assessments if a.verification_status != STATUS_SUPPORTED]
    if not scores:
        overall = 0.0
    elif not risk_points:
        overall = max(scores)
    else:
        overall = 0.5 * max(scores) + 0.5 * (sum(risk_points) / len(risk_points))

    distribution = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for a in assessments:
        distribution[a.risk_level] = distribution.get(a.risk_level, 0) + 1

    top_risks = sorted(assessments, key=lambda a: -a.risk_score)[:10]

    return AuditRiskReport(
        audit_id=audit_id,
        overall_risk_score=round(overall, 1),
        overall_risk_level=_level_of(overall),
        risk_distribution=distribution,
        top_risks=[a.to_dict() for a in top_risks],
        claim_details=[a.to_dict() for a in assessments],
    )
