"""Conflict Detector（Phase 8）：Investment Claim vs External Fact 比对。

四类发现（任务书 §3）：
- FINANCIAL_DATA_CONFLICT        财务数据冲突（数字类口径不一致）
- BUSINESS_DESC_CONFLICT         业务描述冲突（业务定性矛盾）
- GROWTH_LOGIC_INSUFFICIENT      增长逻辑不足（增长主张缺证据/数据不支持）
- COMPETITIVE_EVIDENCE_MISSING   竞争优势缺证据（领先类主张无外部证据）

Evidence First：
- 每个 ConflictFinding 必须附 evidence_trace（claim 原文 + fact 原始证据）；
- 不无证据下"冲突"结论；缺证据时归类 GROWTH_LOGIC_INSUFFICIENT 或
  COMPETITIVE_EVIDENCE_MISSING，不夸大风险。

可解释：
- 比对基于规则（维度配对 / 关键词 / 数值容差 / 证据存在性），
  risk_score 与 risk_type 一一对应，可追溯。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.services.intelligence.schemas import (
    CONFLICT_BUSINESS_DESC,
    CONFLICT_COMPETITIVE_EVIDENCE,
    CONFLICT_FINANCIAL_DATA,
    CONFLICT_GROWTH_LOGIC,
    CONFLICT_NO_OPPOSITION,
    CONFLICT_RISK_TYPE,
    ConflictFinding,
    CompanyFact,
    InvestmentClaim,
    risk_level_of,
)

# 数值比对容差：相对 5% 或绝对 0.5 视为一致
_NUMERIC_REL_TOL = 0.05
_NUMERIC_ABS_TOL = 0.5


# ---------------------------------------------------------------------------
# 维度配对：Claim 与 Fact 的维度一致性是比对前提
# ---------------------------------------------------------------------------
def _claim_dimension(claim: InvestmentClaim, facts: list[CompanyFact]) -> str:
    """根据 Claim 关键词推断其维度（若未指定）。

    优先使用 claim.dimension；否则按关键词猜测：
    - "海外/境外/北美" → MARKET
    - "领先/龙头/第一" → COMPETITION
    - "增长/提升" + 数字 → FINANCIAL（增长逻辑）
    - 其余 → BUSINESS
    """
    if claim.dimension:
        return claim.dimension
    text = claim.claim
    if any(kw in text for kw in ("海外", "境外", "北美", "欧洲", "东南亚")):
        return "MARKET"
    if any(kw in text for kw in ("领先", "龙头", "第一", "行业第一")):
        return "COMPETITION"
    if any(kw in text for kw in ("增长", "提升", "高速")):
        return "FINANCIAL"
    return "BUSINESS"


def _pair_claims_facts(
    claims: list[InvestmentClaim],
    facts: list[CompanyFact],
) -> list[tuple[InvestmentClaim, list[CompanyFact]]]:
    """每个 Claim 配对维度相同（或 COMPANY 兜底）的 Fact。"""
    pairs: list[tuple[InvestmentClaim, list[CompanyFact]]] = []
    for claim in claims:
        dim = _claim_dimension(claim, facts)
        matched: list[CompanyFact] = []
        for f in facts:
            if f.dimension == dim:
                matched.append(f)
            elif dim == "MARKET" and f.dimension == "MARKET":
                matched.append(f)
        # 若无精确维度匹配，则用全部事实兜底（让 detector 自行判别）
        if not matched:
            matched = list(facts)
        pairs.append((claim, matched))
    return pairs


# ---------------------------------------------------------------------------
# 数值比对（FINANCIAL_DATA_CONFLICT / GROWTH_LOGIC_INSUFFICIENT）
# ---------------------------------------------------------------------------
def _numbers_agree(
    claimed: float | None,
    factual: float | None,
    claimed_unit: str = "",
    fact_unit: str = "",
) -> tuple[bool, float | None]:
    """判断两个数值是否一致（容差内）。

    单位归一：亿元 / 万元 / 元 / %。
    返回 (是否一致, 差值)。
    """
    if claimed is None or factual is None:
        return (False, None)

    def _to_yuan(v: float, u: str) -> float:
        if u == "亿元":
            return v * 1e8
        if u == "万元":
            return v * 1e4
        return v  # 元或 %

    c = _to_yuan(claimed, claimed_unit)
    f = _to_yuan(factual, fact_unit)
    denom = max(abs(c), abs(f), 1e-9)
    diff_rel = abs(c - f) / denom
    if diff_rel <= _NUMERIC_REL_TOL or abs(c - f) <= _NUMERIC_ABS_TOL:
        return (True, c - f)
    return (False, c - f)


def _detect_financial(
    claim: InvestmentClaim,
    matched_facts: list[CompanyFact],
) -> ConflictFinding | None:
    """财务数据 / 增长逻辑比对。

    - 若 Claim 有数值且找到对应 Fact 数值：
        一致 → NO_OPPOSITION（支持）
        不一致 → FINANCIAL_DATA_CONFLICT
    - 若 Claim 是增长类但无对应 Fact 数值支持：
        GROWTH_LOGIC_INSUFFICIENT
    """
    claim_has_value = claim.value is not None
    financial_facts = [f for f in matched_facts if f.dimension == "FINANCIAL" and f.value is not None]

    # 直接数值比对
    if claim_has_value and financial_facts:
        for f in financial_facts:
            agree, diff = _numbers_agree(claim.value, f.value, claim.unit, f.unit)
            if not agree:
                return ConflictFinding(
                    finding_id="",  # 由 detect_conflicts 统一编号
                    claim_id=claim.claim_id,
                    fact_id=f.fact_id,
                    claim=claim.claim,
                    fact=f.statement,
                    conflict_type=CONFLICT_FINANCIAL_DATA,
                    difference=f"主张值 {claim.value}{claim.unit} 与事实 {f.value}{f.unit} 不一致"
                    + (f"（差 {diff:.2f}）" if diff is not None else ""),
                    risk_type=CONFLICT_RISK_TYPE[CONFLICT_FINANCIAL_DATA],
                    risk_score=85.0,
                    risk_level=risk_level_of(85.0),
                    evidence_trace=[
                        {"role": "claim", "text": claim.claim, "value": claim.value},
                        {"role": "fact", "text": f.evidence, "source": f.source,
                         "source_label": f.source_label, "timestamp": f.timestamp,
                         "confidence": f.confidence},
                    ],
                )
            # agree → 视为支持，不报冲突
            return ConflictFinding(
                finding_id="",
                claim_id=claim.claim_id,
                fact_id=f.fact_id,
                claim=claim.claim,
                fact=f.statement,
                conflict_type=CONFLICT_NO_OPPOSITION,
                difference=f"主张值与财报事实一致（容差内）",
                risk_type=CONFLICT_RISK_TYPE[CONFLICT_NO_OPPOSITION],
                risk_score=0.0,
                risk_level="LOW",
                evidence_trace=[
                    {"role": "claim", "text": claim.claim, "value": claim.value},
                    {"role": "fact", "text": f.evidence, "source": f.source,
                     "source_label": f.source_label, "timestamp": f.timestamp,
                     "confidence": f.confidence},
                ],
            )

    # 增长逻辑：Claim 含"增长/提升/高速"但无对应数字证据
    if any(kw in claim.claim for kw in ("增长", "提升", "高速", "持续增长")):
        if not financial_facts and not claim_has_value:
            return ConflictFinding(
                finding_id="",
                claim_id=claim.claim_id,
                fact_id="",
                claim=claim.claim,
                fact="(无对应增长数据事实)",
                conflict_type=CONFLICT_GROWTH_LOGIC,
                difference="增长类主张缺乏对应数字证据支持，增长逻辑不充分",
                risk_type=CONFLICT_RISK_TYPE[CONFLICT_GROWTH_LOGIC],
                risk_score=60.0,
                risk_level=risk_level_of(60.0),
                evidence_trace=[
                    {"role": "claim", "text": claim.claim},
                    {"role": "fact", "text": "未检索到对应数字事实", "source": "N/A"},
                ],
            )

    return None


# ---------------------------------------------------------------------------
# 业务描述比对（BUSINESS_DESC_CONFLICT）
# ---------------------------------------------------------------------------
_BUSINESS_POSITIVE_KW = ("领先", "龙头", "第一", "增长", "提升", "扩张", "高速")
_BUSINESS_NEGATIVE_KW = ("下降", "下滑", "亏损", "收缩", "负增长")


def _detect_business(
    claim: InvestmentClaim,
    matched_facts: list[CompanyFact],
) -> ConflictFinding | None:
    """业务描述冲突：Claim 与 Fact 在业务定性上矛盾。

    规则：
    - Claim 含正向定性，但配对 Fact 含负向关键词 → 冲突；
    - Claim 含负向定性，但 Fact 含正向 → 冲突；
    - 否则 → NO_OPPOSITION。
    """
    business_facts = [f for f in matched_facts if f.dimension in ("BUSINESS", "FINANCIAL")]
    if not business_facts:
        return None

    claim_positive = any(kw in claim.claim for kw in _BUSINESS_POSITIVE_KW)
    claim_negative = any(kw in claim.claim for kw in _BUSINESS_NEGATIVE_KW)

    for f in business_facts:
        f_text = f"{f.statement} {f.evidence}"
        f_positive = any(kw in f_text for kw in _BUSINESS_POSITIVE_KW)
        f_negative = any(kw in f_text for kw in _BUSINESS_NEGATIVE_KW)
        # 矛盾：Claim 正向 ↔ Fact 负向；Claim 负向 ↔ Fact 正向
        if (claim_positive and f_negative) or (claim_negative and f_positive):
            return ConflictFinding(
                finding_id="",
                claim_id=claim.claim_id,
                fact_id=f.fact_id,
                claim=claim.claim,
                fact=f.statement,
                conflict_type=CONFLICT_BUSINESS_DESC,
                difference=f"投资观点与外部事实的业务定性存在矛盾",
                risk_type=CONFLICT_RISK_TYPE[CONFLICT_BUSINESS_DESC],
                risk_score=70.0,
                risk_level=risk_level_of(70.0),
                evidence_trace=[
                    {"role": "claim", "text": claim.claim},
                    {"role": "fact", "text": f.evidence, "source": f.source,
                     "source_label": f.source_label, "timestamp": f.timestamp,
                     "confidence": f.confidence},
                ],
            )

    return None


# ---------------------------------------------------------------------------
# 竞争优势缺证据（COMPETITIVE_EVIDENCE_MISSING）
# ---------------------------------------------------------------------------
_COMPETITIVE_KW = ("领先", "龙头", "行业第一", "第一", "优势", "头部")


def _detect_competition(
    claim: InvestmentClaim,
    matched_facts: list[CompanyFact],
) -> ConflictFinding | None:
    """竞争类主张证据核验。

    规则：
    - Claim 含竞争定性关键词；
    - 若无任何 COMPETITION 维度的 Fact → 缺证据；
    - 若 Fact 含"市场份额/行业第一"等强证据 → NO_OPPOSITION；
    - 若 Fact 含竞争关键词但口径模糊 → 中度风险。
    """
    if not any(kw in claim.claim for kw in _COMPETITIVE_KW):
        return None

    competition_facts = [f for f in matched_facts if f.dimension == "COMPETITION"]
    if not competition_facts:
        return ConflictFinding(
            finding_id="",
            claim_id=claim.claim_id,
            fact_id="",
            claim=claim.claim,
            fact="(无竞争优势外部证据)",
            conflict_type=CONFLICT_COMPETITIVE_EVIDENCE,
            difference="竞争优势类主张缺少外部市场份额/排名证据支持",
            risk_type=CONFLICT_RISK_TYPE[CONFLICT_COMPETITIVE_EVIDENCE],
            risk_score=55.0,
            risk_level=risk_level_of(55.0),
            evidence_trace=[
                {"role": "claim", "text": claim.claim},
                {"role": "fact", "text": "未检索到竞争优势外部证据", "source": "N/A"},
            ],
        )

    # 有竞争类 Fact：检查是否有强证据
    strong_evidence_kws = ("市场份额", "行业第一", "第一", "排名", "出货量")
    has_strong = any(
        any(kw in f"{f.statement} {f.evidence}" for kw in strong_evidence_kws)
        for f in competition_facts
    )
    if has_strong:
        f = competition_facts[0]
        return ConflictFinding(
            finding_id="",
            claim_id=claim.claim_id,
            fact_id=f.fact_id,
            claim=claim.claim,
            fact=f.statement,
            conflict_type=CONFLICT_NO_OPPOSITION,
            difference="竞争优势主张有外部强证据支持",
            risk_type=CONFLICT_RISK_TYPE[CONFLICT_NO_OPPOSITION],
            risk_score=0.0,
            risk_level="LOW",
            evidence_trace=[
                {"role": "claim", "text": claim.claim},
                {"role": "fact", "text": f.evidence, "source": f.source,
                 "source_label": f.source_label, "timestamp": f.timestamp,
                 "confidence": f.confidence},
            ],
        )

    # 有竞争类 Fact 但无强证据 → 中度风险
    f = competition_facts[0]
    return ConflictFinding(
        finding_id="",
        claim_id=claim.claim_id,
        fact_id=f.fact_id,
        claim=claim.claim,
        fact=f.statement,
        conflict_type=CONFLICT_COMPETITIVE_EVIDENCE,
        difference="竞争优势主张仅有定性证据，缺少市场份额/排名等强证据",
        risk_type=CONFLICT_RISK_TYPE[CONFLICT_COMPETITIVE_EVIDENCE],
        risk_score=55.0,
        risk_level=risk_level_of(55.0),
        evidence_trace=[
            {"role": "claim", "text": claim.claim},
            {"role": "fact", "text": f.evidence, "source": f.source,
             "source_label": f.source_label, "timestamp": f.timestamp,
             "confidence": f.confidence},
        ],
    )


# ---------------------------------------------------------------------------
# 主入口：detect_conflicts
# ---------------------------------------------------------------------------
@dataclass
class DetectionResult:
    findings: list[ConflictFinding]
    support_count: int  # NO_OPPOSITION 数
    conflict_count: int  # 实际冲突数（不含 NO_OPPOSITION）


def detect_conflicts(
    claims: list[InvestmentClaim],
    facts: list[CompanyFact],
) -> DetectionResult:
    """对所有 Investment Claim 与 External Fact 配对比对，输出 ConflictFindings。

    每个 Claim 至多产出一条 Finding（按优先级：
    FINANCIAL_DATA > BUSINESS_DESC > GROWTH_LOGIC > COMPETITIVE_EVIDENCE > NO_OPPOSITION）。
    """
    pairs = _pair_claims_facts(claims, facts)
    findings: list[ConflictFinding] = []
    fid_idx = 1

    for claim, matched in pairs:
        chosen: ConflictFinding | None = None
        # 优先级 1：财务数据冲突 / 数值一致
        chosen = _detect_financial(claim, matched)
        # 优先级 2：业务描述冲突
        if chosen is None:
            chosen = _detect_business(claim, matched)
        # 优先级 3：竞争优势缺证据
        if chosen is None:
            chosen = _detect_competition(claim, matched)

        # 兜底：无任何比对结论 → NO_OPPOSITION（无可比外部事实）
        if chosen is None:
            chosen = ConflictFinding(
                finding_id="",
                claim_id=claim.claim_id,
                fact_id="",
                claim=claim.claim,
                fact="(无可比外部事实)",
                conflict_type=CONFLICT_NO_OPPOSITION,
                difference="未找到与该主张匹配的外部事实",
                risk_type=CONFLICT_RISK_TYPE[CONFLICT_NO_OPPOSITION],
                risk_score=0.0,
                risk_level="LOW",
                evidence_trace=[
                    {"role": "claim", "text": claim.claim},
                    {"role": "fact", "text": "无可比事实", "source": "N/A"},
                ],
            )

        chosen.finding_id = f"CFLT-{fid_idx:04d}"
        fid_idx += 1
        findings.append(chosen)

    support_count = sum(1 for f in findings if f.conflict_type == CONFLICT_NO_OPPOSITION)
    conflict_count = sum(1 for f in findings if f.conflict_type != CONFLICT_NO_OPPOSITION)

    return DetectionResult(
        findings=findings,
        support_count=support_count,
        conflict_count=conflict_count,
    )


# ---------------------------------------------------------------------------
# 整体风险评分（与 Phase 6/7 阈值一致）
# ---------------------------------------------------------------------------
def compute_overall_risk(findings: Iterable[ConflictFinding]) -> tuple[float, str]:
    """整体风险：0.5 × 最高单项 + 0.5 × 冲突项平均（可解释公式）。

    无冲突 → 0.0 LOW。
    """
    findings_list = list(findings)
    if not findings_list:
        return (0.0, "LOW")
    scores = [f.risk_score for f in findings_list]
    conflict_scores = [f.risk_score for f in findings_list if f.risk_score > 0]
    if not conflict_scores:
        return (0.0, "LOW")
    overall = 0.5 * max(scores) + 0.5 * (sum(conflict_scores) / len(conflict_scores))
    overall = max(0.0, min(100.0, overall))
    return (round(overall, 1), risk_level_of(overall))


__all__ = [
    "DetectionResult",
    "detect_conflicts",
    "compute_overall_risk",
]
