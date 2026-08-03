"""Phase 23.10 — 多 Evidence Verification。

对 Top K Evidence 执行：
1. 逐条判定每条 Evidence 与 Claim 的关系（evidence_level_verdicts）
2. 识别正确 Evidence 与干扰 Evidence（selected / rejected + reasons）
3. 对同一 metric/period/unit/scope 证据聚合；冲突证据保留冲突，不静默平均
4. 正确高置信 Evidence 不被多个低质量叙述块覆盖
5. Evidence 不足时弃权
6. 记录 aggregation_rule 与最终使用的 Evidence IDs

主链仍由 core_pipeline.core_verify 决定最终 Verdict（保证 Oracle 1.0 不回归）；
本模块在其之上做 evidence 级记录与聚合分析，不改变最终 Verdict，
仅补充 selected_evidence_ids / rejected_evidence_ids / rejection_reasons /
evidence_level_verdicts / aggregate_verdict / aggregation_rule。

用法：
    from app.services.verification.multi_evidence import aggregate_evidence_analysis
    analysis = aggregate_evidence_analysis(claim, evidence_list, final_result, trace)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class EvidenceLevelResult:
    evidence_id: str
    verdict: str
    confidence: float
    reason: str
    metric_hit: bool = False
    value_hit: bool = False
    period_hit: bool = False
    is_noise: bool = False


@dataclass
class EvidenceAggregation:
    selected_evidence_ids: list = field(default_factory=list)
    rejected_evidence_ids: list = field(default_factory=list)
    rejection_reasons: dict = field(default_factory=dict)
    evidence_level_verdicts: list = field(default_factory=list)
    aggregate_verdict: str = ""
    aggregation_rule: str = ""

    def to_dict(self) -> dict:
        return {
            "selected_evidence_ids": self.selected_evidence_ids,
            "rejected_evidence_ids": self.rejected_evidence_ids,
            "rejection_reasons": self.rejection_reasons,
            "evidence_level_verdicts": [
                {"evidence_id": e.evidence_id, "verdict": e.verdict, "confidence": round(e.confidence, 3),
                 "reason": e.reason, "metric_hit": e.metric_hit, "value_hit": e.value_hit,
                 "period_hit": e.period_hit, "is_noise": e.is_noise}
                for e in self.evidence_level_verdicts
            ],
            "aggregate_verdict": self.aggregate_verdict,
            "aggregation_rule": self.aggregation_rule,
        }


SUPPORTED = "SUPPORTED"
REFUTED = "REFUTED"
PARTIAL = "PARTIALLY_SUPPORTED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


def _evidence_text(e: dict) -> str:
    return e.get("text", "") or e.get("evidence_text", "") or ""


def _metric_aliases_of(claim: dict) -> list[str]:
    from app.services.evidence_retrieval.engine import metric_aliases

    return [a for a in metric_aliases(claim.get("metric_code"), claim.get("metric"))
            if a and re.search(r"[\u4e00-\u9fff]", a)]


def _judge_single_evidence(claim: dict, e: dict, claim_value, claim_unit) -> EvidenceLevelResult:
    """逐条证据判定：基于 metric/value/period 命中的确定性规则（不读取 Gold）。"""
    text = _evidence_text(e)
    eid = e.get("evidence_id") or e.get("block_id") or "?"
    aliases = _metric_aliases_of(claim)
    metric_hit = any(a and a in text for a in aliases)
    value_hit = False
    if claim_value is not None:
        from app.services.evidence_retrieval.engine import _block_value_hits

        ok, _r = _block_value_hits(text, claim_value, claim_unit or None)
        value_hit = ok
    period_hit = True
    claim_period = str(claim.get("period") or "").upper()
    if claim_period and re.search(r"20\d{2}", claim_period):
        period_hit = bool(re.search(r"20\d{2}", text) or re.search(r"报告期|年度|半年度|季度", text))
    # 数值冲突：同指标行但有数字且 value 未命中 → REFUTED
    numeric_conflict = metric_hit and bool(re.search(r"\d", text)) and not value_hit and claim_value is not None
    if numeric_conflict:
        return EvidenceLevelResult(eid, REFUTED, 0.85, "同指标行数值与主张不符（数值冲突）",
                                   metric_hit, value_hit, period_hit, is_noise=False)
    if value_hit and metric_hit:
        return EvidenceLevelResult(eid, SUPPORTED, 0.95, "指标+数值匹配",
                                   metric_hit, value_hit, period_hit, is_noise=False)
    if value_hit and not metric_hit:
        return EvidenceLevelResult(eid, PARTIAL, 0.55, "数值匹配但指标标签未命中",
                                   metric_hit, value_hit, period_hit, is_noise=True)
    if metric_hit and not re.search(r"\d", text):
        return EvidenceLevelResult(eid, INSUFFICIENT, 0.4, "叙述段提及指标但无具体数据",
                                   metric_hit, value_hit, period_hit, is_noise=True)
    return EvidenceLevelResult(eid, INSUFFICIENT, 0.3, "证据与主张无明确关联",
                               metric_hit, value_hit, period_hit, is_noise=True)


def aggregate_evidence_analysis(claim: dict, evidence_list: list[dict],
                                final_result=None, trace=None) -> EvidenceAggregation:
    """多 Evidence 聚合分析（不改变最终 Verdict）。

    aggregation_rule（任务十一）：
    - 存在确定性 REFUTED（数值冲突）→ 冲突保留，最终 REFUTED（不被低质量支持覆盖）
    - 否则 ≥1 条 SUPPORTED（高置信）且无冲突 → SUPPORTED
    - 部分支持 + 部分不足 → PARTIALLY_SUPPORTED
    - 全部不足 → INSUFFICIENT_EVIDENCE（弃权）
    """
    claim_value = claim.get("value") if isinstance(claim.get("value"), (int, float)) else None
    claim_unit = claim.get("unit") or ""
    ev_results = [_judge_single_evidence(claim, e, claim_value, claim_unit) for e in evidence_list]

    has_refuted = any(r.verdict == REFUTED for r in ev_results)
    supported = [r for r in ev_results if r.verdict == SUPPORTED]
    partial = [r for r in ev_results if r.verdict == PARTIAL]
    insufficient = [r for r in ev_results if r.verdict == INSUFFICIENT]

    # 聚合规则（与最终 Verdict 协调：Oracle 主链决定最终结果，这里给出聚合解释）
    if has_refuted:
        aggregate_verdict = REFUTED
        rule = "存在确定性数值冲突 → 冲突保留为 REFUTED（不被低质量叙述块覆盖）"
    elif supported:
        aggregate_verdict = SUPPORTED
        rule = f"{len(supported)} 条证据 SUPPORTED（高置信）且无冲突 → SUPPORTED"
    elif partial:
        aggregate_verdict = PARTIAL
        rule = f"{len(partial)} 条证据 PARTIAL（数值/指标部分命中）→ PARTIALLY_SUPPORTED"
    else:
        aggregate_verdict = INSUFFICIENT
        rule = "全部证据不足 → 弃权 INSUFFICIENT_EVIDENCE"
    # 若主链已有最终结果，以其为准（Oracle 主链不回归）
    if final_result is not None:
        aggregate_verdict = final_result.verification_status

    selected = [r.evidence_id for r in supported if r.verdict == SUPPORTED]
    rejected = []
    reasons = {}
    for r in ev_results:
        if r.evidence_id in selected:
            continue
        rejected.append(r.evidence_id)
        reasons[r.evidence_id] = f"{r.verdict}: {r.reason}"

    # 兼容 trace：写入 detail（不改 final_verdict）
    if trace is not None:
        trace.detail["multi_evidence"] = {
            "selected_evidence_ids": selected,
            "rejected_evidence_ids": rejected,
            "aggregation_rule": rule,
        }

    return EvidenceAggregation(
        selected_evidence_ids=selected,
        rejected_evidence_ids=rejected,
        rejection_reasons=reasons,
        evidence_level_verdicts=ev_results,
        aggregate_verdict=aggregate_verdict,
        aggregation_rule=rule,
    )


__all__ = ["aggregate_evidence_analysis", "EvidenceAggregation", "EvidenceLevelResult"]
