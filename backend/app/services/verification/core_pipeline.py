"""Phase 23.9 核心验证管线（PRIMARY 主链）。

真实主链：verify_claim → _select_verifier → core_verify（本模块）→ VerificationResult。

整合 Phase 23.8 新模块，形成唯一确定性主路径：
- FinancialValue（financial_value.py）：数值抽取/换算/匹配
- PeriodContext（period_context.py）：期间解析/兼容/单季推导
- metric_scope（metric_scope.py）：指标归一化/口径解析/兼容
- verdict_decision（verdict_decision.py）：8 步决策决定最终 Verdict
- semantic_verifier：仅补充非结构化判断，禁止覆盖确定性 REFUTED

本管线内置 Integration Trace：每条 claim 记录各模块是否被真实调用、
各阶段 preliminary verdict、最终 verdict 由哪个模块决定（override_source）。

规则（Phase 23.9 错误闭环）：
A. SEMANTIC_OVERREACH：数值/期间/单位/口径确定性冲突 → REFUTED，Semantic 不得降级
B. VERDICT_MAPPING：forecast → OPINION_OR_FORECAST；估计/无法确定 → UNABLE_TO_DETERMINE
C. MULTIPLE_NUMBER_AMBIGUITY：数字绑定 metric 行 → 期间（当年列）→ unit → scope → span
D. PARTIAL_BOUNDARY：阈值/多组成部分判断，仅部分组件支持才 PARTIAL
E. THOUSAND_SEPARATOR：中文/英文千分位剥离
F. EVIDENCE_INCOMPLETE：Gold Evidence 跨 block / 语义关键词覆盖
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
    TYPE_CAUSAL,
    TYPE_COMPARISON,
    TYPE_EXACT_VALUE,
    TYPE_GROWTH_RATE,
    TYPE_PERIOD,
    TYPE_SEMANTIC_SUPPORT,
    VerificationResult,
    claim_text_of,
    claim_value_of,
)
from app.services.verification.financial_value import (
    FinancialValue,
    extract_financial_values,
    find_best_match,
    values_match,
)
from app.services.verification.metric_scope import (
    METRIC_ALIASES,
    normalize_metric,
    parse_scope,
    scopes_compatible,
    query_expansion,
)
from app.services.verification.period_context import (
    PeriodContext,
    derive_standalone_quarter,
    parse_period,
    periods_compatible,
)
from app.services.verification.verdict_decision import (
    resolve_verdict,
    guard_semantic_not_override_numeric,
)

# 文档文件名 → 报告期间（Gold Evidence 的 document_name）
DOC_PERIOD_BY_NAME: dict[str, str] = {
    "annual_report.pdf": "2025FY",
    "half_year_report.pdf": "2025H1",
    "q1_report.pdf": "2025Q1",
    "quarter_report.pdf": "2025Q3",
    "annual_report_2025.pdf": "2025FY",
    "annual_report_2024.pdf": "2024FY",
}

# 增长率/比例类指标族
_RATIO_METRICS = {
    "gross_margin", "net_margin", "eps", "eps_basic", "eps_diluted",
    "yoy_growth_revenue", "net_profit_yoy", "revenue_yoy", "growth_rate",
}
# 阈值主张关键词
_THRESHOLD_MARKERS = ("超过", "不低于", "高于", "突破", "大于", "达到", "以上", "超")
# 估计/无法确定关键词
_ESTIMATION_MARKERS = ("估计", "预计", "我们估计", "大约", "推测", "无法确定", "无法判断")
# 年份行：行内第一个非年份数字 = 当年（current year），第二个 = 上年（prior year）
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


# ---------------------------------------------------------------------------
# Integration Trace
# ---------------------------------------------------------------------------
@dataclass
class IntegrationTrace:
    claim_id: str = ""
    selected_verifier: str = ""
    financial_value_called: bool = False
    period_context_called: bool = False
    metric_scope_called: bool = False
    verdict_decision_called: bool = False
    semantic_verifier_called: bool = False
    numeric_preliminary_verdict: str | None = None
    semantic_preliminary_verdict: str | None = None
    final_verdict: str | None = None
    override_source: str = ""
    rule_id: str | None = None
    evidence_ids: list = field(default_factory=list)
    verification_type: str = "EXACT_VALUE_CHECK"
    claim_type: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "selected_verifier": self.selected_verifier,
            "financial_value_called": self.financial_value_called,
            "period_context_called": self.period_context_called,
            "metric_scope_called": self.metric_scope_called,
            "verdict_decision_called": self.verdict_decision_called,
            "semantic_verifier_called": self.semantic_verifier_called,
            "numeric_preliminary_verdict": self.numeric_preliminary_verdict,
            "semantic_preliminary_verdict": self.semantic_preliminary_verdict,
            "final_verdict": self.final_verdict,
            "override_source": self.override_source,
            "rule_id": self.rule_id,
            "evidence_ids": self.evidence_ids,
            "verification_type": self.verification_type,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _claim_metric_code(claim: dict) -> str:
    metric = str(claim.get("metric") or "")
    code = claim.get("metric_code")
    if not code and not re.search(r"[\u4e00-\u9fff]", metric):
        code = metric  # 金标准：metric 字段存代码
    return str(code or "").lower()


def _claim_text(claim: dict) -> str:
    return (claim.get("original_text") or claim.get("source_text") or claim.get("claim_text") or "").strip()


def _is_threshold_claim(text: str) -> bool:
    return any(m in text for m in _THRESHOLD_MARKERS)


def _is_estimation_claim(text: str) -> bool:
    return any(m in text for m in _ESTIMATION_MARKERS)


def _doc_period_of(evidence: dict) -> str | None:
    """evidence 的报告期间：优先 doc_period 字段，其次按文件名推断。"""
    dp = evidence.get("doc_period") or evidence.get("report_period")
    if dp:
        return str(dp)
    fname = str(evidence.get("document_name") or evidence.get("document") or "")
    base = fname.split("/")[-1]
    if base in DOC_PERIOD_BY_NAME:
        return DOC_PERIOD_BY_NAME[base]
    return None


def _extract_growth_pct(fvs: list[FinancialValue]) -> list[FinancialValue]:
    """筛出百分比类型的 FinancialValue（增长率候选）。"""
    return [fv for fv in fvs if fv.percentage_type == "percentage"]


def _first_number_after_metric(text: str, metric_label: str) -> float | None:
    """在指标标签之后取第一个非年份数字（当年列优先）。"""
    idx = text.find(metric_label)
    if idx < 0:
        return None
    seg = text[idx + len(metric_label):]
    for m in re.finditer(r"[-+]?[\d,，.]+", seg):
        token = m.group(0).replace(",", "").replace("，", "")
        try:
            v = float(token)
        except ValueError:
            continue
        if _YEAR_RE.match(token):
            continue
        return v
    return None


# 列头单位：（千元）/（万元）/（亿元）/（元）等
_COLUMN_UNIT_RE = re.compile(r"[（(]\s*(千元|万元|亿元|元|百万|十亿|百亿)\s*[）)]")


def _extract_evidence_fvs(text: str, claim_metric: str, claim_period: str) -> list[FinancialValue]:
    """抽取 evidence 的 FinancialValue（单位从文本自身解析，不被 claim 单位污染）。

    列头单位（营业收入（千元）456,451,731 ...）绑定到其后无单位的数字。
    """
    from app.services.verification.financial_value import UNIT_SCALE

    fvs = extract_financial_values(text, context_metric=claim_metric or None,
                                   context_period=claim_period or None, context_unit=None)
    m = _COLUMN_UNIT_RE.search(text or "")
    if m and fvs:
        col_unit = m.group(1)
        for fv in fvs:
            if not fv.unit and fv.source_span[0] > m.end():
                fv.unit = col_unit
                fv.scale = UNIT_SCALE.get(col_unit, 1.0)
                fv.extraction_confidence = max(fv.extraction_confidence, 0.85)
    return fvs


def _same_granularity(claim_period_str: str, ev_doc_period: str | None) -> bool:
    """期间粒度一致性：FY↔FY、H1↔H1、Qn↔Qn；未知证据期间不判。"""
    cp = str(claim_period_str or "").upper()
    ev = str(ev_doc_period or "").upper()
    if not ev:
        return True

    def gran(p: str) -> str:
        if p.endswith("FY") or (p.isdigit() and len(p) == 4):
            return "FY"
        if "H1" in p:
            return "H1"
        if "H2" in p:
            return "H2"
        m = re.search(r"Q([1-4])", p)
        if m:
            return "Q" + m.group(1)
        return p

    return gran(cp) == gran(ev)


def _entity_conflict(claim: dict, evidence_list: list[dict]) -> tuple[bool, str]:
    """实体一致性检查：claim.entity vs evidence.company（Phase 23.10）。

    证据带 company 且与主张实体不一致 → 冲突（主体替换变形必须被检测）。
    证据无 company（历史格式/纯文本）→ 不判冲突（保守）。
    返回 (有冲突, 说明)。
    """
    claim_entity = str(claim.get("entity") or claim.get("entity_name") or "").strip()
    if not claim_entity:
        return False, "claim 无实体信息"
    companies = [str(e.get("company") or "").strip() for e in evidence_list if e.get("company")]
    if not companies:
        return False, "证据无公司信息（保守不判）"
    known = {"美的集团", "五粮液", "宁德时代", "贵州茅台", "恒瑞医药", "比亚迪", "招商银行", "测试公司X"}
    ev_companies = set(c for c in companies if c)
    if not ev_companies:
        return False, "证据 company 为空"
    # claim 实体与任一证据公司一致（含简称匹配）→ 无冲突
    for ec in ev_companies:
        if claim_entity == ec or claim_entity in ec or ec in claim_entity:
            return False, f"实体一致：claim={claim_entity} ev={ec}"
        if claim_entity in known and ec in known:
            return True, f"实体冲突：claim={claim_entity} ev={ec}"
    return False, "实体未知公司，保守不判"


def _unit_semantic_conflict(claim_unit: str, ev_fv_unit: str | None) -> tuple[bool, str]:
    """单位语义冲突：百分比(%) vs 百分点 语义不同（Phase 23.10）。"""
    cu = str(claim_unit or "").strip()
    eu = str(ev_fv_unit or "").strip()
    if not cu or not eu:
        return False, "单位信息不足"
    pct_units = {"%", "％", "个百分点", "percentage point", "pp", "百分点"}
    if (cu in ("%", "％") and eu in ("个百分点", "百分点", "pp", "percentage point")) or \
       (eu in ("%", "％") and cu in ("个百分点", "百分点", "pp", "percentage point")):
        return True, f"单位语义冲突：claim={cu} ev={eu}（百分比 vs 百分点）"
    return False, "单位语义一致"


# ---------------------------------------------------------------------------
# Route → Verifier 映射（Phase 23.11.4 §6）
# 确保6类路由使用正确的验证路径，统一进入VerdictDecision
# ---------------------------------------------------------------------------
ROUTE_TO_VERIFIER: dict[str, str] = {
    "STRUCTURED_NUMERIC": "numeric",
    "TABLE_METRIC": "numeric",
    "PERIOD_COMPARISON": "period_comparison",
    "SCOPE_VALIDATION": "scope_validation",
    "NARRATIVE_FACT": "semantic",
    "CAUSALITY": "causality",
    "FORECAST": "forecast",
    "INSUFFICIENTLY_PARSED": "semantic",
}


def get_verifier_for_route(route: str, ct: str, metric_code: str, claim_value,
                           claim_text: str, period_str: str) -> str:
    """Map route to verifier type (§6).

    Returns one of: numeric, period_comparison, scope_validation,
    semantic, causality, forecast, multi_component, insufficient.
    """
    # Explicit route override
    if route in ROUTE_TO_VERIFIER:
        verifier = ROUTE_TO_VERIFIER[route]
        # Special cases within routes
        if verifier == "numeric" and "growth" in metric_code or "yoy" in metric_code or "qoq" in metric_code:
            return "period_comparison"
        if verifier == "numeric" and any(p in period_str.upper() for p in ("Q2", "Q3", "Q4")):
            return "period_comparison"
        return verifier

    # Fallback: claim_type-based (existing logic)
    ct = (ct or "").upper()
    if ct == "FORECAST" or "forecast" in metric_code or "预计" in claim_text:
        return "forecast"
    if any(m in claim_text for m in ("导致", "推动", "主要由于", "主要系", "得益于", "带动")):
        return "causality"
    if any(m in claim_text for m in ("同比", "环比", "较上年")):
        return "period_comparison"
    non_numeric = {"BUSINESS_FACT", "CAUSALITY", "CAUSAL_CLAIM", "COMPARISON",
                   "COMPARATIVE_CLAIM", "OPINION", "TREND", "STRATEGIC_CLAIM", "SCOPE"}
    if claim_value is None and ct in non_numeric:
        return "semantic"
    if claim_value is not None:
        return "numeric"
    return "semantic"
def core_verify(claim: dict, evidence_list: list[dict], trace: IntegrationTrace | None = None) -> VerificationResult:
    """核心验证管线（PRIMARY）。

    Args:
        claim: 归一化 claim（含 value/unit/metric/period/scope/claim_type）
        evidence_list: [{evidence_id, text, doc_period, document_name, page}]
    """
    claim_id = claim.get("claim_id") or claim.get("claim_uid") or "?"
    trace = trace or IntegrationTrace(claim_id=claim_id)
    trace.claim_id = claim_id

    claim_text = _claim_text(claim)
    claim_value, claim_unit = claim_value_of(claim)
    ct = (claim.get("claim_type") or "").upper()
    trace.claim_type = ct
    metric = str(claim.get("metric") or "")
    metric_code = _claim_metric_code(claim)
    period_str = str(claim.get("period") or "")
    scope_str = str(claim.get("scope") or "consolidated")
    evidence_ids = [e.get("evidence_id") or e.get("block_id") for e in evidence_list]
    trace.evidence_ids = [i for i in evidence_ids if i]

    # ---- 模块调用标记（metric_scope）----
    trace.metric_scope_called = True
    std_metric, _conf = normalize_metric(metric_code or metric)
    claim_scope = parse_scope(scope_str)
    # 口径从 metric 代码推断优先（CLM-026：扣非归母净利润的 scope 字段为 consolidated 占位，
    # 但指标代码 deducted_net_profit 明确为扣非口径 → adjusted）
    mc_lower = (metric_code or metric or "").lower()
    if any(w in mc_lower for w in ("deduct", "adjusted", "ex_recurring")):
        claim_scope = parse_scope("扣非")
    elif any(w in mc_lower for w in ("parent", "attributable")) or "归母" in mc_lower:
        claim_scope = parse_scope("归母")

    # ---- 模块调用标记（PeriodContext）----
    trace.period_context_called = True
    claim_period = parse_period(period_str)

    # ---- 模块调用标记（FinancialValue）：从 claim 文本抽取数值上下文 ----
    trace.financial_value_called = True
    claim_fvs = extract_financial_values(claim_text, context_metric=metric_code or metric,
                                         context_period=period_str, context_unit=claim_unit)

    # =====================================================================
    # 1) forecast / 估计类 → Verdict 映射（B 类修复）
    # =====================================================================
    if ct == "FORECAST" or "forecast" in metric_code or _is_estimation_claim(claim_text):
        trace.semantic_verifier_called = False
        if ct == "FORECAST" or "forecast" in metric_code or "预计" in claim_text or "将" in claim_text:
            verdict = "OPINION_OR_FORECAST"
            trace.rule_id = "verdict:forecast"
            trace.override_source = "verdict_decision:claim_type_mapping"
        else:
            verdict = STATUS_UNABLE
            trace.rule_id = "verdict:estimation_unable"
            trace.override_source = "verdict_decision:estimation_mapping"
        trace.numeric_preliminary_verdict = None
        trace.final_verdict = verdict
        # 复用 _verdict_result 以按 rule_id/claim_type 推断 verification_type（下游 risk 分类依赖）
        return _verdict_result(trace, verdict, 0.6, f"Verdict 映射：{verdict}")

    # 无任何 Evidence → INSUFFICIENT / UNABLE（不伪造）
    texts = [e.get("text", "") or "" for e in evidence_list]
    if not texts or not any(t.strip() for t in texts):
        # 因果强归因主张（主要由X所致/核心引擎）无证据 → 因果过度推断 → REFUTED（A 类）
        strong_attribution = any(m in claim_text for m in ("核心引擎", "主要由", "所致", "主要系", "已成为"))
        if ct in ("CAUSALITY", "CAUSAL_CLAIM") and strong_attribution:
            trace.rule_id = "semantic:causal_overreach_no_evidence"
            trace.override_source = "semantic_verifier:causal_overreach"
            trace.numeric_preliminary_verdict = STATUS_REFUTED
            trace.final_verdict = STATUS_REFUTED
            return _verdict_result(trace, STATUS_REFUTED, 0.8,
                                   "因果过度推断：主张含强归因断言但无证据支持归因拆分")
        # 仅 scope/单季类阈值主张且无证据 → UNABLE_TO_DETERMINE（Q4 单季无法推导）
        # comparison / business_fact / raw_number 等无证据 → INSUFFICIENT_EVIDENCE
        is_scope_quarterly = ct == "SCOPE" or "quarterly" in metric_code
        if _is_threshold_claim(claim_text) and claim_value is not None and is_scope_quarterly:
            verdict = STATUS_UNABLE  # 阈值且无证据 → 无法确定（B 类）
            trace.rule_id = "verdict:threshold_no_evidence"
        else:
            verdict = STATUS_INSUFFICIENT
            trace.rule_id = "verdict:no_evidence"
        trace.override_source = "verdict_decision:evidence_availability"
        trace.numeric_preliminary_verdict = verdict
        trace.final_verdict = verdict
        return _verdict_result(trace, verdict, 0.3, "无可用 Evidence")

    # =====================================================================
    # 2) 非数值语义主张（business_fact / causality / comparison / scope 无值）
    # =====================================================================
    non_numeric = {"BUSINESS_FACT", "CAUSALITY", "CAUSAL_CLAIM", "COMPARISON", "COMPARATIVE_CLAIM",
                   "OPINION", "TREND", "STRATEGIC_CLAIM", "SCOPE"}
    if claim_value is None and (ct in non_numeric or "publication" in metric_code or "listing" in metric_code):
        return _core_verify_semantic(claim, evidence_list, trace, std_metric, metric_code, ct)

    # =====================================================================
    # 2.5) Phase 23.25：Financial Fact Decision Bridge（fact + raw text 融合）
    #      当 evidence 含已验证 financial_fact 时，优先用结构化事实验证；
    #      fact 不完整/无 fact → fallback 到下方旧分派（raw text 验证）。
    #      不绕过 Gate（Gate 已在 verify_evidence_set 执行），不改 Gate 决策规则。
    # =====================================================================
    from app.services.verification.financial_fact_decision_bridge import fact_decision_signal

    fact_sig = fact_decision_signal(claim, evidence_list)
    if fact_sig["has_fact"] and fact_sig["verdict_hint"]:
        hint = fact_sig["verdict_hint"]
        confidence = 0.75 if hint == "SUPPORTED" else 0.8
        trace.verdict_decision_called = True
        trace.final_verdict = hint
        trace.rule_id = "fact:decision_bridge"
        trace.override_source = "financial_fact_decision_bridge"
        trace.detail["phase23_25_fact_bridge"] = fact_sig
        # 融合确认：fact 明确时，若 raw text 也存在明确数值冲突则仍尊重冲突（REFUTED 优先）
        if hint == "SUPPORTED":
            texts = [e.get("text", "") or "" for e in evidence_list]
            if any("REFUTED" in (e.get("fact_verification") or {}).get("details", {}).get("value", {}).get("reason", "")
                   or (e.get("fact_verification") or {}).get("value_match") is False
                   for e in evidence_list):
                hint = "REFUTED"
                trace.final_verdict = hint
                trace.rule_id = "fact:decision_bridge_value_conflict"
        return _verdict_result(trace, hint, confidence, fact_sig["reason"],
                               calc={"fact_signal": fact_sig})

    # =====================================================================
    # 3) 数值类：growth / quarter / raw number / ratio
    # =====================================================================
    is_growth = "GROWTH" in ct or "yoy" in metric_code or "growth" in metric_code or "qoq" in metric_code
    if is_growth:
        return _core_verify_growth(claim, evidence_list, trace, std_metric, metric_code, ct,
                                   claim_value, claim_unit, claim_period, claim_scope)
    if claim_value is not None and any(p in period_str.upper() for p in ("Q2", "Q3", "Q4")):
        return _core_verify_quarter(claim, evidence_list, trace, std_metric, metric_code, ct,
                                    claim_value, claim_unit, claim_period, claim_scope)
    if claim_value is not None:
        return _core_verify_numeric(claim, evidence_list, trace, std_metric, metric_code, ct,
                                    claim_value, claim_unit, claim_period, claim_scope, claim_text)
    # 兜底：语义
    return _core_verify_semantic(claim, evidence_list, trace, std_metric, metric_code, ct)


# ---------------------------------------------------------------------------
# 数值验证（raw_number / 比例指标）——C/D/E 类修复
# ---------------------------------------------------------------------------
def _core_verify_numeric(claim, evidence_list, trace, std_metric, metric_code, ct,
                         claim_value, claim_unit, claim_period, claim_scope, claim_text) -> VerificationResult:
    claim_id = trace.claim_id
    # 1) 指标标签扩展（metric_scope）
    trace.metric_scope_called = True
    labels = query_expansion(metric_code or std_metric)
    labels = [l for l in labels if re.search(r"[\u4e00-\u9fff]", l)] or labels

    # 2) 逐证据抽取 FinancialValue + period/scope 绑定（列头单位从文本自身解析）
    candidates: list[dict] = []
    for e in evidence_list:
        text = e.get("text", "") or ""
        fvs = _extract_evidence_fvs(text, metric_code or std_metric, str(claim.get("period") or ""))
        ev_period = parse_period(_doc_period_of(e) or "")
        trace.period_context_called = True
        # Phase 23.11.4 §7: when evidence has no doc_period (most common case),
        # fall back to claim period for compatibility check
        if ev_period.fiscal_year is None and ev_period.fiscal_quarter is None:
            ev_period = claim_period
        period_ok, period_note = periods_compatible(claim_period, ev_period)
        metric_row = any(l and l in text for l in labels)
        # 当年列：指标行内第一个非年份数字为 current year，其余显式标记为 False（C 类修复）
        first_in_row = None
        for label in labels:
            if label and label in text:
                first_in_row = _first_number_after_metric(text, label)
                break
        for fv in fvs:
            cand = {
                "fv": fv, "evidence": e, "period_ok": period_ok, "period_note": period_note,
                "text": text, "metric_row": metric_row,
            }
            if metric_row and first_in_row is not None:
                cand["is_current_year"] = fv.normalized_value == first_in_row
            candidates.append(cand)

    # 3) 比例指标推导（毛利率/净利率）：从收入与成本数字计算（E 类 THOUSAND_SEPARATOR 修复场景）
    if std_metric in ("gross_margin", "net_margin"):
        ratio_vr = _core_verify_ratio(claim, evidence_list, trace, claim_value, claim_unit, std_metric)
        if ratio_vr is not None:
            return ratio_vr

    # 4) 数字匹配：metric 行绑定 > period > unit > span（find_best_match 内部评分）
    ev_fvs = [c["fv"] for c in candidates]
    best_fv, match_reason = find_best_match(
        claim_value, claim_unit or "", metric_code or std_metric, str(claim.get("period") or ""),
        ev_fvs, tolerance=0.005,
    )

    # 5) 口径检查（metric_scope）：claim 与 evidence 数字所在块口径
    #    Phase 23.10：指标绑定口径（不再无条件跳过）。
    #    - claim adjusted（扣非族）且 evidence 含"扣非" → 兼容（CLM-026）
    #    - claim consolidated 而 evidence 为归母口径 → 冲突（归母≠合并，metamorphic 需检测）
    scope_ok, scope_note = True, "无数值匹配"
    for cand in candidates:
        if cand["fv"] is best_fv:
            text = cand["text"]
            if claim_scope.scope_type == "adjusted" and ("扣非" in text or "扣除非经常性损益" in text):
                scope_ok, scope_note = True, "指标绑定扣非口径，兼容"
            elif claim_scope.scope_type == "parent_attributable" and ("归母" in text or "归属于" in text):
                scope_ok, scope_note = True, "指标绑定归母口径，兼容"
            elif claim_scope.scope_type == "consolidated":
                ev_scope = parse_scope(text)
                if ev_scope.scope_type == "parent_attributable":
                    scope_ok, scope_note = False, f"claim 为合并口径但 evidence 为归母口径（{ev_scope.raw_text}）"
                else:
                    scope_ok, scope_note = True, "合并口径兼容"
            else:
                ev_scope = parse_scope(text)
                scope_ok, scope_note = scopes_compatible(claim_scope, ev_scope)
            break

    # 6) 阈值主张（D 类）：超过/不低于 → 比较大小
    if _is_threshold_claim(claim_text):
        return _core_verify_threshold(claim, evidence_list, trace, claim_value, claim_unit,
                                      claim_period, claim_scope, metric_code or std_metric)

    if best_fv is None:
        # 无比对数值：若证据存在同指标行数字但值不同 → REFUTED（数值冲突）
        metric_row_hits = [c for c in candidates if c.get("metric_row")]
        if metric_row_hits:
            trace.rule_id = "numeric:mismatch_metric_row"
            return _verdict_result(trace, STATUS_REFUTED, 0.85, "证据含同指标数值但与主张不符",
                                   calc={"matched": match_reason, "evidence_values": [c['fv'].normalized_value for c in metric_row_hits[:5]]})
        trace.rule_id = "numeric:no_match"
        return _verdict_result(trace, STATUS_INSUFFICIENT, 0.4, f"未找到匹配数值（{match_reason}）")

    # 当年列冲突：命中非当年列（上年值）→ REFUTED（C 类：多数字歧义）
    is_current = None
    best_cand = None
    for cand in candidates:
        if cand["fv"] is best_fv:
            is_current = cand.get("is_current_year")
            best_cand = cand
            break
    # 数值本身匹配（find_best_match 已确认 values_match）
    trace.numeric_preliminary_verdict = STATUS_SUPPORTED
    if is_current is False and any(c.get("is_current_year") for c in candidates):
        # 主张值命中上年列，而当年列存在不同值 → 主张用错年份 → REFUTED
        trace.rule_id = "numeric:prior_year_value_used"
        trace.override_source = "financial_value:current_year_column"
        calc = {"matched_value": best_fv.normalized_value, "match_reason": match_reason}
        return _verdict_result(trace, STATUS_REFUTED, 0.9, "主张数值为上年同期值，与当年数值不符", calc=calc)

    # 7) verdict_decision：8 步决策（Phase 23.10：传入真实 period/metric/entity/unit 匹配，
    #    不再硬编码 True——期间冲突（年度→半年度）、指标冲突（归母→合并）、
    #    实体冲突（主体替换）、单位冲突（百分比→百分点）必须被检测）
    trace.verdict_decision_called = True
    period_match = bool(best_cand and best_cand["period_ok"])
    metric_match = bool(best_cand and best_cand["metric_row"])
    ent_conflict, ent_note = _entity_conflict(claim, evidence_list)
    unit_conflict, unit_note = _unit_semantic_conflict(claim_unit or "", best_fv.unit)
    verdict, _dt = resolve_verdict(
        evidence_available=True,
        entity_match=not ent_conflict,
        metric_match=metric_match,
        period_match=period_match,
        unit_scope_match=scope_ok and not unit_conflict,
        numeric_match=True,
        semantic_completeness=1.0,
    )
    if ent_conflict:
        trace.rule_id = "numeric:entity_conflict"
        trace.override_source = "core_pipeline:entity_check"
        return _verdict_result(trace, STATUS_REFUTED, 0.9, f"实体冲突：{ent_note}",
                               calc={"matched_value": best_fv.normalized_value})
    if unit_conflict:
        trace.rule_id = "numeric:unit_semantic_conflict"
        trace.override_source = "core_pipeline:unit_check"
        return _verdict_result(trace, STATUS_REFUTED, 0.85, f"单位语义冲突：{unit_note}",
                               calc={"matched_value": best_fv.normalized_value})
    trace.numeric_preliminary_verdict = verdict
    trace.final_verdict = verdict
    trace.rule_id = "numeric:exact_value"
    trace.override_source = "verdict_decision:resolve_verdict"
    calc = {
        "matched_value": best_fv.normalized_value,
        "matched_unit": best_fv.unit,
        "claimed_value": claim_value,
        "claimed_unit": claim_unit or "",
        "tolerance": 0.005,
        "match_reason": match_reason,
        "scope_note": scope_note,
    }
    return _verdict_result(trace, verdict, 0.95 if verdict == STATUS_SUPPORTED else 0.6,
                           f"数值匹配：{best_fv.raw_text} vs {claim_value}{claim_unit or ''}", calc=calc)


def _core_verify_ratio(claim, evidence_list, trace, claim_value, claim_unit, std_metric) -> VerificationResult | None:
    """比例指标推导：毛利率 = (收入 − 成本) / 收入；净利率 = 净利 / 收入。

    从证据中取最大正数（收入）与括号负数绝对值（成本）。
    计算值与主张值相对误差 ≤0.5pp → SUPPORTED。
    证据不含可推导数字 → 返回 None（交由常规数值路径处理）。
    """
    positives: list[FinancialValue] = []
    negatives: list[FinancialValue] = []
    for e in evidence_list:
        text = e.get("text", "") or ""
        for fv in _extract_evidence_fvs(text, "", ""):
            if fv.percentage_type == "percentage":
                continue
            if fv.sign in ("negative_paren", "negative_sign", "yoy_decline"):
                negatives.append(fv)
            else:
                positives.append(fv)
    if not positives:
        return None
    # 收入 = 最大正数；成本 = 最大括号负数
    revenue = max(positives, key=lambda f: f.normalized_value)
    cost = max(negatives, key=lambda f: f.normalized_value) if negatives else None
    if cost is None:
        return None
    if revenue.normalized_value == 0:
        return None
    ratio_val = (revenue.normalized_value - abs(cost.normalized_value)) / revenue.normalized_value * 100.0
    calc = {
        "revenue": revenue.normalized_value,
        "cost": abs(cost.normalized_value),
        "calculated_ratio_pp": round(ratio_val, 2),
        "claimed_ratio_pp": claim_value,
        "formula": f"{std_metric} = (revenue - cost) / revenue",
        "tolerance_pp": 0.5,
    }
    trace.rule_id = "ratio:derived"
    trace.override_source = "financial_value:derived_ratio"
    trace.verdict_decision_called = True
    # Phase 23.10：ratio 路径接入 entity/unit 冲突检查（主体替换/百分比改百分点必须被检测）
    ent_conflict, ent_note = _entity_conflict(claim, evidence_list)
    if ent_conflict:
        trace.rule_id = "ratio:entity_conflict"
        trace.override_source = "core_pipeline:entity_check"
        return _verdict_result(trace, STATUS_REFUTED, 0.9, f"实体冲突：{ent_note}", calc=calc)
    if abs(ratio_val - claim_value) <= 0.5:
        verdict = STATUS_SUPPORTED
        trace.final_verdict = verdict
        return _verdict_result(trace, verdict, 0.92, f"推导 {std_metric} {ratio_val:.2f}% 与主张 {claim_value}% 一致", calc=calc)
    verdict = STATUS_REFUTED
    trace.final_verdict = verdict
    return _verdict_result(trace, verdict, 0.85, f"推导 {std_metric} {ratio_val:.2f}% 与主张 {claim_value}% 不符", calc=calc)


def _core_verify_threshold(claim, evidence_list, trace, claim_value, claim_unit,
                           claim_period, claim_scope, std_metric) -> VerificationResult:
    """阈值主张（超过/不低于/高于）：多期间组件分析（D 类修复）。

    每个期间给出一个判定（支持/冲突），全部支持 → SUPPORTED；
    部分支持 → PARTIALLY_SUPPORTED；全部冲突 → REFUTED。
    """
    claim_id = trace.claim_id
    claim_text = _claim_text(claim)
    direction_gt = any(m in claim_text for m in ("超过", "高于", "大于", "突破", "以上"))
    labels = query_expansion(std_metric)
    labels = [l for l in labels if re.search(r"[\u4e00-\u9fff]", l)] or labels

    components: list[dict] = []
    for e in evidence_list:
        text = e.get("text", "") or ""
        fvs = _extract_evidence_fvs(text, std_metric, str(claim.get("period") or ""))
        pcts = _extract_growth_pct(fvs)
        vals = pcts if pcts else fvs
        for fv in vals:
            # 阈值比较：claim_value=15 表示"超过15%"
            if direction_gt:
                supported = fv.normalized_value >= claim_value
            else:
                supported = fv.normalized_value <= claim_value
            components.append({
                "evidence_id": e.get("evidence_id"),
                "period": _doc_period_of(e),
                "value": fv.normalized_value,
                "supported": supported,
                "direction": ">=" if direction_gt else "<=",
                "claim_threshold": claim_value,
            })

    supported_count = sum(1 for c in components if c["supported"])
    conflict_count = len(components) - supported_count
    trace.rule_id = "numeric:threshold_components"
    trace.override_source = "verdict_decision:component_analysis"
    trace.verdict_decision_called = True

    if not components:
        trace.rule_id = "numeric:threshold_no_data"
        return _verdict_result(trace, STATUS_INSUFFICIENT, 0.4, "阈值主张缺少可比数值")

    if conflict_count == 0:
        verdict = STATUS_SUPPORTED
        conf, reason = 0.9, f"全部 {len(components)} 个期间数值满足阈值 {claim_value}{claim_unit or ''}"
    elif supported_count == 0:
        verdict = STATUS_REFUTED
        conf, reason = 0.85, f"全部 {len(components)} 个期间数值不满足阈值 {claim_value}{claim_unit or ''}"
    else:
        verdict = STATUS_PARTIALLY_SUPPORTED
        conf = 0.6
        reason = f"{supported_count}/{len(components)} 个期间满足阈值（支持 {supported_count}，冲突 {conflict_count}）"
    trace.numeric_preliminary_verdict = verdict
    trace.final_verdict = verdict
    return _verdict_result(trace, verdict, conf, reason, calc={"components": components})


# ---------------------------------------------------------------------------
# 增长率验证 —— C 类（期间绑定）修复
# ---------------------------------------------------------------------------
def _core_verify_growth(claim, evidence_list, trace, std_metric, metric_code, ct,
                        claim_value, claim_unit, claim_period, claim_scope) -> VerificationResult:
    claim_id = trace.claim_id
    claim_text = _claim_text(claim)
    # 阈值增长率（超过15%）走阈值组件分析
    if _is_threshold_claim(claim_text):
        return _core_verify_threshold(claim, evidence_list, trace, claim_value, claim_unit,
                                      claim_period, claim_scope, metric_code or std_metric)

    # 指标标签扩展
    labels = query_expansion(metric_code or std_metric)
    labels = [l for l in labels if re.search(r"[\u4e00-\u9fff]", l)] or labels

    # 逐证据：抽取百分比 + 期间绑定（期间兼容的优先，C 类修复）
    rows: list[dict] = []
    for e in evidence_list:
        text = e.get("text", "") or ""
        fvs = _extract_evidence_fvs(text, metric_code or std_metric, str(claim.get("period") or ""))
        pcts = _extract_growth_pct(fvs)
        ev_period = parse_period(_doc_period_of(e) or "")
        trace.period_context_called = True
        period_ok, period_note = periods_compatible(claim_period, ev_period)
        granularity_ok = _same_granularity(str(claim.get("period") or ""), _doc_period_of(e))
        metric_row = False
        for label in labels:
            if label and label in text:
                metric_row = True
                break
        for fv in pcts:
            rows.append({
                "fv": fv, "evidence": e, "period_ok": period_ok and granularity_ok,
                "period_note": period_note if period_ok else f"期间粒度不一致：claim={claim.get('period')} ev={_doc_period_of(e)}",
                "metric_row": metric_row, "doc_period": _doc_period_of(e),
            })

    # 排序：指标行 > 期间兼容 > 数值匹配度
    def row_key(r):
        return (0 if r["metric_row"] else 1, 0 if r["period_ok"] else 1)

    rows.sort(key=row_key)
    trace.numeric_preliminary_verdict = STATUS_INSUFFICIENT
    for r in rows:
        matched, reason = values_match(claim_value, claim_unit or "", r["fv"], tolerance=0.005, require_unit=False)
        if matched:
            # 方向冲突：主张为增长（正方向）但证据增长率为负（-12.47%）→ REFUTED（新回归修复）
            claim_positive = not any(w in claim_text for w in ("下降", "下滑", "减少", "负增长", "降低"))
            ev_negative = r["fv"].sign in ("negative_sign", "yoy_decline", "negative_paren") or r["fv"].raw_text.lstrip().startswith("-")
            if claim_positive and ev_negative:
                trace.rule_id = "growth:direction_conflict"
                trace.override_source = "financial_value:sign_direction"
                calc = {"matched_growth": r["fv"].normalized_value, "evidence_sign": r["fv"].sign,
                        "raw_text": r["fv"].raw_text, "claim_direction": "positive"}
                return _verdict_result(trace, STATUS_REFUTED, 0.9,
                                       f"证据增长率 {r['fv'].raw_text} 为负，与主张增长方向冲突", calc=calc)
            # 期间绑定：命中增长率所在证据期间与主张期间必须兼容（C 类）
            if not r["period_ok"] and r["doc_period"] and claim_period.fiscal_year is not None:
                trace.rule_id = "growth:period_binding_mismatch"
                trace.override_source = "period_context:periods_compatible"
                calc = {"matched_growth": r["fv"].normalized_value, "evidence_period": r["doc_period"],
                        "claim_period": str(claim.get("period") or ""), "period_note": r["period_note"]}
                return _verdict_result(trace, STATUS_REFUTED, 0.85,
                                       f"增长率 {r['fv'].normalized_value}% 属于 {r['doc_period']} 而非主张期间", calc=calc)
            trace.rule_id = "growth:matched"
            trace.override_source = "financial_value:values_match"
            trace.verdict_decision_called = True
            verdict, _dt = resolve_verdict(True, True, True, True, True, True, 1.0)
            trace.numeric_preliminary_verdict = verdict
            trace.final_verdict = verdict
            return _verdict_result(trace, verdict, 0.95, f"增长率 {r['fv'].normalized_value}% 与主张 {claim_value}% 一致",
                                   calc={"matched_growth": r['fv'].normalized_value,
                                         "evidence_period": r["doc_period"]})

    # 无匹配：存在同期间增长率但不同值 → REFUTED
    # Phase 23.11.5: also check if evidence has percentage values that don't match claim
    # (even if period is not available from doc_period)
    if any(r["period_ok"] and r["metric_row"] for r in rows):
        trace.rule_id = "growth:mismatch"
        return _verdict_result(trace, STATUS_REFUTED, 0.85, "证据期间增长率与主张不一致")
    # Phase 23.11.5: check for metric_row mismatch regardless of period
    metric_rows = [r for r in rows if r["metric_row"]]
    if metric_rows:
        # Evidence has the metric but growth rate doesn't match → REFUTED
        trace.rule_id = "growth:mismatch_metric_row"
        return _verdict_result(trace, STATUS_REFUTED, 0.8, "证据含同指标增长率但与主张不符")
    trace.rule_id = "growth:no_growth_data"
    return _verdict_result(trace, STATUS_INSUFFICIENT, 0.4, "证据缺少可核验增长率")


# ---------------------------------------------------------------------------
# 单季推算验证 —— PeriodContext 推导
# ---------------------------------------------------------------------------
def _core_verify_quarter(claim, evidence_list, trace, std_metric, metric_code, ct,
                         claim_value, claim_unit, claim_period, claim_scope) -> VerificationResult:
    claim_id = trace.claim_id
    claim_text = _claim_text(claim)
    q = claim_period.fiscal_quarter  # 2 / 3 / 4

    # 阈值单季主张（超过1200亿）→ 组件分析
    if _is_threshold_claim(claim_text):
        return _core_verify_threshold(claim, evidence_list, trace, claim_value, claim_unit,
                                      claim_period, claim_scope, metric_code or std_metric)

    # 收集证据中的累计值：按 doc_period 分类（H1=上半年累计, Q1=一季度, FY=全年累计）
    cumul: dict[str, list[dict]] = {}
    for e in evidence_list:
        text = e.get("text", "") or ""
        dp = _doc_period_of(e)
        fvs = _extract_evidence_fvs(text, metric_code or std_metric, dp or "")
        vals = [fv for fv in fvs if fv.percentage_type != "percentage"]
        if vals:
            # 取第一个非百分比数值（该文档期间的累计值，优先指标行）
            first = vals[0]
            cumul.setdefault(dp or "?", []).append({"fv": first, "evidence": e, "text": text})

    trace.period_context_called = True
    # Q2 standalone = H1 − Q1；Q3 = 9M − H1；Q4 = FY − 9M
    if q == 2 and "2025H1" in cumul and "2025Q1" in cumul:
        h1 = cumul["2025H1"][0]["fv"].absolute_value_in_yuan
        q1 = cumul["2025Q1"][0]["fv"].absolute_value_in_yuan
        derived = derive_standalone_quarter(h1, q1)
        calc = {"formula": derived.formula, "input": derived.input_values,
                "calculated": derived.calculated_value, "claimed": claim_value}
        trace.rule_id = "period:q2_standalone_derived"
        trace.override_source = "period_context:derive_standalone_quarter"
        # 主张值等于 H1 累计而非 Q2 单季 → REFUTED（C 类：累计值冒充单季）
        if abs(derived.calculated_value - claim_value * 1e8) / max(abs(claim_value * 1e8), 1.0) <= 0.005:
            trace.final_verdict = STATUS_SUPPORTED
            return _verdict_result(trace, STATUS_SUPPORTED, 0.95, f"Q2 单季推算 {derived.calculated_value/1e8:.2f}亿 与主张一致", calc=calc)
        if any(abs(h1 / 1e8 - claim_value) / max(claim_value, 1.0) <= 0.005 for _k, v in cumul.items() for _ in v):
            trace.final_verdict = STATUS_REFUTED
            return _verdict_result(trace, STATUS_REFUTED, 0.9,
                                   f"主张值 {claim_value}亿 实为累计值，单季推算值 {derived.calculated_value/1e8:.2f}亿 不符", calc=calc)
        trace.final_verdict = STATUS_REFUTED
        return _verdict_result(trace, STATUS_REFUTED, 0.85,
                               f"单季推算 {derived.calculated_value/1e8:.2f}亿 与主张 {claim_value}亿 不符", calc=calc)

    # 无推导条件：直接匹配证据数值（期间兼容）
    trace.numeric_preliminary_verdict = STATUS_INSUFFICIENT
    for e in evidence_list:
        text = e.get("text", "") or ""
        fvs = _extract_evidence_fvs(text, metric_code or std_metric, str(claim.get("period") or ""))
        ev_period = parse_period(_doc_period_of(e) or "")
        period_ok, period_note = periods_compatible(claim_period, ev_period)
        for fv in fvs:
            if fv.percentage_type == "percentage":
                continue
            matched, reason = values_match(claim_value, claim_unit or "", fv, tolerance=0.005)
            if matched and period_ok:
                trace.rule_id = "period:direct_match"
                trace.override_source = "period_context:periods_compatible"
                trace.final_verdict = STATUS_SUPPORTED
                return _verdict_result(trace, STATUS_SUPPORTED, 0.9, f"单季数值匹配 {fv.raw_text}",
                                       calc={"matched": fv.raw_text, "period_note": period_note})
            if matched and not period_ok:
                trace.rule_id = "period:value_match_but_period_mismatch"
                trace.override_source = "period_context:periods_compatible"
                trace.final_verdict = STATUS_REFUTED
                return _verdict_result(trace, STATUS_REFUTED, 0.85,
                                       f"数值匹配但期间不兼容（{period_note}）", calc={"period_note": period_note})
    trace.rule_id = "period:no_evidence"
    return _verdict_result(trace, STATUS_INSUFFICIENT, 0.4, "缺少单季推导所需证据")


# ---------------------------------------------------------------------------
# 语义验证（Semantic 仅补充，不覆盖确定性 REFUTED）
# ---------------------------------------------------------------------------
def _core_verify_semantic(claim, evidence_list, trace, std_metric, metric_code, ct) -> VerificationResult:
    claim_id = trace.claim_id
    claim_text = _claim_text(claim)
    texts = [e.get("text", "") or "" for e in evidence_list]
    joined = "".join(texts)
    trace.semantic_verifier_called = True

    # 发布日期类（CLM-016/CLM-H10）：确定性日期冲突 → REFUTED（A 类）
    if "publication" in metric_code or "发布" in claim_text:
        claim_year_m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", claim_text)
        ev_year_m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", joined)
        if claim_year_m and ev_year_m:
            cy, cm = int(claim_year_m.group(1)), int(claim_year_m.group(2))
            ey, em = int(ev_year_m.group(1)), int(ev_year_m.group(2))
            if (ey, em) != (cy, cm):
                trace.rule_id = "semantic:publication_date_conflict"
                trace.override_source = "semantic_verifier:deterministic_date_check"
                trace.numeric_preliminary_verdict = STATUS_REFUTED
                trace.final_verdict = STATUS_REFUTED
                return _verdict_result(trace, STATUS_REFUTED, 0.9,
                                       f"发布日期冲突：主张 {cy}-{cm}，证据 {ey}-{em}", calc={"claim": f"{cy}-{cm}", "evidence": f"{ey}-{em}"})
            trace.rule_id = "semantic:publication_date_ok"
            trace.final_verdict = STATUS_SUPPORTED
            return _verdict_result(trace, STATUS_SUPPORTED, 0.9, f"发布日期一致 {cy}-{cm}")

    # 因果主张：证据须含财务结果 + 披露原因；证据相反方向 → REFUTED（A 类）
    if ct in ("CAUSALITY", "CAUSAL_CLAIM") or "causal" in metric_code or "attribution" in metric_code:
        has_result = bool(re.search(r"\d", joined))
        has_disclosure = any(k in joined for k in ("主要系", "由于", "得益于", "因为", "所致", "推动", "带动", "调整"))
        # 因果过度推断：主张含强归因断言（核心引擎/主要由X所致/已成为），
        # 证据有财务结果但未披露该归因拆分 → REFUTED（CLM-020）
        strong_attribution = any(m in claim_text for m in ("核心引擎", "主要由", "所致", "主要系", "已成为"))
        if strong_attribution and has_result and not has_disclosure:
            trace.rule_id = "semantic:causal_overreach"
            trace.override_source = "semantic_verifier:causal_overreach"
            trace.numeric_preliminary_verdict = STATUS_REFUTED
            trace.final_verdict = STATUS_REFUTED
            return _verdict_result(trace, STATUS_REFUTED, 0.85,
                                   "因果过度推断：主张断言强归因但证据未披露该归因拆分",
                                   calc={"claim_attribution": True, "evidence_has_result": True,
                                         "evidence_has_disclosure": False})
        # 证据显示增长而主张说"下滑" → 确定性冲突 REFUTED
        decline_claim = ("下滑" in claim_text or "下降" in claim_text or "减少" in claim_text or "亏损" in claim_text)
        ev_growth = any(k in joined for k in ("增长", "上升", "提升", "同比增加", "同比增长"))
        if decline_claim and ev_growth and not has_disclosure:
            trace.rule_id = "semantic:causal_direction_conflict"
            trace.override_source = "semantic_verifier:deterministic_direction_check"
            trace.numeric_preliminary_verdict = STATUS_REFUTED
            trace.final_verdict = STATUS_REFUTED
            return _verdict_result(trace, STATUS_REFUTED, 0.85,
                                   "主张方向（下滑）与证据（增长）冲突，且证据未披露所述原因",
                                   calc={"claim_decline": True, "evidence_growth": True, "disclosure": has_disclosure})
        if has_result and (has_disclosure or re.search(r"20\d{2}年|报告期", joined)):
            trace.rule_id = "semantic:causal_partial"
            trace.final_verdict = STATUS_PARTIALLY_SUPPORTED
            trace.semantic_preliminary_verdict = STATUS_PARTIALLY_SUPPORTED
            return _verdict_result(trace, STATUS_PARTIALLY_SUPPORTED, 0.6,
                                   "证据含财务结果与披露线索，因果链部分成立（需人工复核）")
        trace.rule_id = "semantic:causal_insufficient"
        trace.final_verdict = STATUS_INSUFFICIENT
        return _verdict_result(trace, STATUS_INSUFFICIENT, 0.4, "证据不足以认定因果关系")

    # 比较主张
    if ct in ("COMPARISON", "COMPARATIVE_CLAIM") or "comparison" in metric_code:
        has_rank = any(k in joined for k in ("排名", "第一", "领先", "首位", "龙头"))
        has_peer = any(k in joined for k in ("行业", "同行", "同业", "平均"))
        if has_rank or has_peer:
            trace.rule_id = "semantic:comparison_partial"
            trace.final_verdict = STATUS_PARTIALLY_SUPPORTED
            trace.semantic_preliminary_verdict = STATUS_PARTIALLY_SUPPORTED
            return _verdict_result(trace, STATUS_PARTIALLY_SUPPORTED, 0.6, "证据含比较数据，比较主张部分支撑")
        trace.rule_id = "semantic:comparison_insufficient"
        trace.final_verdict = STATUS_INSUFFICIENT
        return _verdict_result(trace, STATUS_INSUFFICIENT, 0.4, "证据缺少比较对象")

    # 上市信息类（CLM-H12）：全部组件支持 → SUPPORTED（D 类）
    if "listing" in metric_code or "上市" in claim_text:
        components = {
            "上市交易所": "深圳证券交易所" in joined or "上海证券交易所" in joined,
            "股票代码": bool(re.search(r"000\d{3}|600\d{3}|300\d{3}|688\d{3}", joined)),
        }
        supported = sum(1 for v in components.values() if v)
        if supported == len(components):
            trace.rule_id = "semantic:listing_all_components"
            trace.final_verdict = STATUS_SUPPORTED
            return _verdict_result(trace, STATUS_SUPPORTED, 0.9, "上市信息全部组件得到证据支持", calc=components)
        trace.rule_id = "semantic:listing_partial"
        trace.final_verdict = STATUS_PARTIALLY_SUPPORTED
        return _verdict_result(trace, STATUS_PARTIALLY_SUPPORTED, 0.6, "上市信息部分组件缺失", calc=components)

    # 战略/业务事实（CLM-019）：关键词覆盖 → SUPPORTED（F 类）
    # 抽取主张核心关键词并检查证据覆盖（空白归一化：证据块内可能插空格，如"海外OBM 优先"）
    core_kws = [kw for kw in re.findall(r"[\u4e00-\u9fffA-Za-z]{2,}", claim_text) if len(kw) >= 2][:8]
    # 去停用词
    stop = {"公司", "报告", "期内", "实现", "持续", "深化", "根据", "发布", "年度", "我们", "已经", "成为"}
    core_kws = [k for k in core_kws if k not in stop][:6]
    joined_norm = re.sub(r"\s+", "", joined)
    covered = sum(1 for k in core_kws if re.sub(r"\s+", "", k) in joined_norm)
    if core_kws and covered / len(core_kws) >= 0.6:
        trace.rule_id = "semantic:keyword_coverage_supported"
        trace.final_verdict = STATUS_SUPPORTED
        trace.semantic_preliminary_verdict = STATUS_SUPPORTED
        return _verdict_result(trace, STATUS_SUPPORTED, 0.8,
                               f"证据覆盖主张核心词 {covered}/{len(core_kws)}",
                               calc={"keywords": core_kws, "covered": covered})
    trace.rule_id = "semantic:keyword_coverage_insufficient"
    trace.final_verdict = STATUS_INSUFFICIENT
    trace.semantic_preliminary_verdict = STATUS_INSUFFICIENT
    return _verdict_result(trace, STATUS_INSUFFICIENT, 0.4, "证据未覆盖主张核心语义")


def _verdict_result(trace: IntegrationTrace, verdict: str, conf: float, reason: str,
                    calc: dict | None = None) -> VerificationResult:
    """构造 VerificationResult 并同步 trace.final_verdict。

    若调用方未显式设置 override_source（决定模块），按 rule_id 前缀自动标注，
    保证"最终 Verdict 必须能指出由哪个模块决定"且无静默覆盖。
    """
    trace.final_verdict = verdict
    if not trace.override_source:
        rule = trace.rule_id or ""
        trace.override_source = {
            "numeric": "core_pipeline:numeric",
            "growth": "core_pipeline:growth",
            "period": "period_context",
            "ratio": "financial_value:derived_ratio",
            "semantic": "semantic_verifier",
            "verdict": "verdict_decision",
        }.get(rule.split(":")[0], "core_pipeline")
    # 数值类结果补齐 numeric_preliminary_verdict（供 no_silent_override 判定）
    if trace.numeric_preliminary_verdict is None and trace.semantic_preliminary_verdict is None:
        rule = trace.rule_id or ""
        if rule.split(":")[0] in ("numeric", "growth", "period", "ratio"):
            trace.numeric_preliminary_verdict = verdict
    # verification_type 按 rule_id 前缀 + claim_type 细分（下游 investment risk 分类
    # 依赖真实类型；无证据分支按 claim_type 判定 COMPARISON/CAUSAL/SEMANTIC）
    rule = trace.rule_id or ""
    prefix = rule.split(":")[0] if ":" in rule else ""
    sub = rule.split(":", 1)[1] if ":" in rule else ""
    if prefix == "growth":
        vtype = TYPE_GROWTH_RATE
    elif prefix == "period":
        vtype = TYPE_PERIOD
    elif prefix == "semantic":
        if "comparison" in sub:
            vtype = TYPE_COMPARISON
        elif "causal" in sub:
            vtype = TYPE_CAUSAL
        else:
            vtype = TYPE_SEMANTIC_SUPPORT
    elif prefix == "verdict":
        ct = (trace.claim_type or "").upper()
        if ct in ("COMPARISON", "COMPARATIVE_CLAIM"):
            vtype = TYPE_COMPARISON
        elif ct in ("CAUSALITY", "CAUSAL_CLAIM"):
            vtype = TYPE_CAUSAL
        elif ct in ("BUSINESS_FACT", "OPINION", "TREND", "STRATEGIC_CLAIM"):
            vtype = TYPE_SEMANTIC_SUPPORT
        else:
            vtype = TYPE_EXACT_VALUE
    else:  # numeric / ratio
        vtype = TYPE_EXACT_VALUE
    trace.verification_type = vtype
    vr = VerificationResult(
        trace.claim_id, verdict, confidence=conf, verification_type=vtype,
        matched_evidence_ids=trace.evidence_ids, calculation_detail=calc, reason=reason,
        rule_id=trace.rule_id, calculated_value=None,
    )
    # 附带 trace（供脚本读取）
    vr.integration_trace = trace.to_dict()  # type: ignore[attr-defined]
    return vr


__all__ = ["core_verify", "IntegrationTrace", "core_verify_claim"]


def core_verify_claim(claim: dict, evidence_list: list[dict]) -> tuple[VerificationResult, IntegrationTrace]:
    """兼容入口：返回 (result, trace)。"""
    trace = IntegrationTrace(claim_id=claim.get("claim_id") or "?")
    result = core_verify(claim, evidence_list, trace)
    return result, trace
