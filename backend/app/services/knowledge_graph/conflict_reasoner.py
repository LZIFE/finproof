"""Conflict Reasoner（Phase 10）：基于知识图谱的冲突推理。

检测四类冲突（任务书 §5）：
- CONFLICT_CLAIM_VS_FACT            Claim 与 Fact 冲突（数字/口径不一致）
- CONFLICT_BUSINESS_OVERSTATEMENT   Business 描述夸大（绝对化关键词）
- CONFLICT_COMPETITIVE_NO_EVIDENCE  Competitive 优势缺证据
- CONFLICT_GROWTH_INSUFFICIENT      Growth 逻辑不足（缺增长数字证据）

输出 ConflictFinding（任务书 §5）：
- claim          Claim 原文
- graph_facts    相关图谱事实（含证据追溯）
- difference     差异描述（人类可读）
- risk_type      风险类型
- risk_score     风险分数（0-100）

Evidence First：每个结论必须引用图谱事实的证据，
不凭空下"冲突"结论。

设计约束（任务书）：
- 不修改已有 Verification 逻辑；
- Knowledge Graph 作为新增层，与已有模块解耦。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.services.knowledge_graph.schemas import (
    CONFLICT_BASE_SCORE,
    CONFLICT_BUSINESS_OVERSTATEMENT,
    CONFLICT_CLAIM_VS_FACT,
    CONFLICT_COMPETITIVE_NO_EVIDENCE,
    CONFLICT_GROWTH_INSUFFICIENT,
    CONFLICT_NO_OPPOSITION,
    CONFLICT_RISK_TYPE,
    ConflictFinding,
    Fact,
    KnowledgeGraph,
    risk_level_of,
)

# ---------------------------------------------------------------------------
# 关键词：夸大表达 / 增长逻辑 / 竞争优势
# ---------------------------------------------------------------------------
_OVERSTATEMENT_KW = (
    "唯一",
    "最强",
    "绝对",
    "遥遥领先",
    "无可争议",
    "世界第一",
    "全球第一",
    "行业第一",
    "龙头",
    "领跑",
    "顶级",
    "独占",
)

_GROWTH_KW = ("增长", "提升", "高速", "持续增长", "快速增长")
_COMPETITIVE_KW = ("领先", "龙头", "行业第一", "第一", "优势", "头部")

# 数字抽取正则
_NUMBER_PATTERN = re.compile(
    r"(?P<metric>[^\s，。、：]{2,12}?)"
    r"\s*[为达约共]?\s*(?P<value>\d[\d,]*\.?\d*)\s*"
    r"(?P<unit>亿元|万元|元|%)"
)


# ---------------------------------------------------------------------------
# 辅助：从 Claim 文本抽取数字
# ---------------------------------------------------------------------------
def _extract_claim_numbers(claim_text: str) -> list[dict]:
    """从 Claim 原文抽取"指标 数值 单位"三元组。"""
    out: list[dict] = []
    for m in _NUMBER_PATTERN.finditer(claim_text):
        metric = m.group("metric").strip()
        value_str = m.group("value").replace(",", "")
        unit = m.group("unit")
        try:
            value: float | None = float(value_str)
        except ValueError:
            value = None
        out.append({"metric": metric, "value": value, "unit": unit, "match": m.group(0)})
    return out


def _numbers_agree(
    claim_value: float | None,
    fact_value,
    claim_unit: str = "",
    fact_unit: str = "",
) -> tuple[bool, float | None]:
    """判断 Claim 数字与 Fact 数字是否一致（容差内）。"""
    if claim_value is None or fact_value is None:
        return (False, None)

    # 单位归一（亿元 / 万元 / 元 / %）
    def _to_yuan(v: float, u: str) -> float:
        if u == "亿元":
            return v * 1e8
        if u == "万元":
            return v * 1e4
        return v  # 元或 %

    c = _to_yuan(claim_value, claim_unit)
    f = _to_yuan(fact_value, fact_unit) if isinstance(fact_value, (int, float)) else 0.0
    denom = max(abs(c), abs(f), 1e-9)
    diff_rel = abs(c - f) / denom
    if diff_rel <= 0.05 or abs(c - f) <= 0.5:
        return (True, c - f)
    return (False, c - f)


# ---------------------------------------------------------------------------
# 检测 1：CONFLICT_CLAIM_VS_FACT（Claim 与 Fact 数字/口径冲突）
# ---------------------------------------------------------------------------
def _detect_claim_vs_fact(
    claim_id: str,
    claim_text: str,
    facts: list[Fact],
) -> ConflictFinding | None:
    """Claim 含数字，与图谱 Fact 数字不一致 → 冲突。"""
    claim_numbers = _extract_claim_numbers(claim_text)
    if not claim_numbers:
        return None

    # 找到含数字的 Fact
    numeric_facts = [f for f in facts if f.object_value is not None]
    if not numeric_facts:
        return None

    # 比对每个 Claim 数字与 Fact 数字
    for cn in claim_numbers:
        for fact in numeric_facts:
            agree, _ = _numbers_agree(
                cn["value"], fact.object_value, cn["unit"], fact.unit
            )
            if not agree:
                graph_facts = [fact.to_dict()]
                return ConflictFinding(
                    finding_id="",  # 由 detect_conflicts 统一编号
                    claim_id=claim_id,
                    claim=claim_text,
                    conflict_type=CONFLICT_CLAIM_VS_FACT,
                    graph_facts=graph_facts,
                    difference=f"Claim 数字 {cn['value']}{cn['unit']} 与图谱事实 {fact.object_value}{fact.unit} 不一致",
                    risk_type=CONFLICT_RISK_TYPE[CONFLICT_CLAIM_VS_FACT],
                    risk_score=CONFLICT_BASE_SCORE[CONFLICT_CLAIM_VS_FACT],
                    risk_level=risk_level_of(CONFLICT_BASE_SCORE[CONFLICT_CLAIM_VS_FACT]),
                    evidence_trace=[
                        {"role": "claim", "text": claim_text, "value": cn["value"]},
                        {"role": "fact", "text": fact.evidence, "source": fact.source,
                         "source_label": fact.source_label, "timestamp": fact.timestamp,
                         "confidence": fact.confidence},
                    ],
                )
            # agree → NO_OPPOSITION（支持）
            return ConflictFinding(
                finding_id="",
                claim_id=claim_id,
                claim=claim_text,
                conflict_type=CONFLICT_NO_OPPOSITION,
                graph_facts=[fact.to_dict()],
                difference="Claim 数字与图谱事实一致（容差内）",
                risk_type=CONFLICT_RISK_TYPE[CONFLICT_NO_OPPOSITION],
                risk_score=0.0,
                risk_level="LOW",
                evidence_trace=[
                    {"role": "claim", "text": claim_text, "value": cn["value"]},
                    {"role": "fact", "text": fact.evidence, "source": fact.source,
                     "source_label": fact.source_label, "timestamp": fact.timestamp,
                     "confidence": fact.confidence},
                ],
            )

    return None


# ---------------------------------------------------------------------------
# 检测 2：CONFLICT_BUSINESS_OVERSTATEMENT（Business 描述夸大）
# ---------------------------------------------------------------------------
def _detect_business_overstatement(
    claim_id: str,
    claim_text: str,
    facts: list[Fact],
) -> ConflictFinding | None:
    """Claim 含夸大关键词 → Business 描述夸大。"""
    matched_kw = [kw for kw in _OVERSTATEMENT_KW if kw in claim_text]
    if not matched_kw:
        return None

    return ConflictFinding(
        finding_id="",
        claim_id=claim_id,
        claim=claim_text,
        conflict_type=CONFLICT_BUSINESS_OVERSTATEMENT,
        graph_facts=[],
        difference=f"Claim 含夸大表达关键词：{', '.join(matched_kw[:3])}",
        risk_type=CONFLICT_RISK_TYPE[CONFLICT_BUSINESS_OVERSTATEMENT],
        risk_score=CONFLICT_BASE_SCORE[CONFLICT_BUSINESS_OVERSTATEMENT],
        risk_level=risk_level_of(CONFLICT_BASE_SCORE[CONFLICT_BUSINESS_OVERSTATEMENT]),
        evidence_trace=[
            {"role": "claim", "text": claim_text, "kw": matched_kw[:3]},
        ],
    )


# ---------------------------------------------------------------------------
# 检测 3：CONFLICT_GROWTH_INSUFFICIENT（Growth 逻辑不足）
# ---------------------------------------------------------------------------
def _detect_growth_insufficient(
    claim_id: str,
    claim_text: str,
    facts: list[Fact],
) -> ConflictFinding | None:
    """Claim 含增长关键词，但图谱无对应增长数字事实 → Growth 逻辑不足。"""
    is_growth_claim = any(kw in claim_text for kw in _GROWTH_KW)
    if not is_growth_claim:
        return None

    # 检查图谱中是否有数字事实支持增长
    numeric_facts = [f for f in facts if f.object_value is not None]
    if numeric_facts:
        # 有数字事实支持 → NO_OPPOSITION
        fact = numeric_facts[0]
        return ConflictFinding(
            finding_id="",
            claim_id=claim_id,
            claim=claim_text,
            conflict_type=CONFLICT_NO_OPPOSITION,
            graph_facts=[fact.to_dict()],
            difference="增长类 Claim 有图谱数字事实支持",
            risk_type=CONFLICT_RISK_TYPE[CONFLICT_NO_OPPOSITION],
            risk_score=0.0,
            risk_level="LOW",
            evidence_trace=[
                {"role": "claim", "text": claim_text},
                {"role": "fact", "text": fact.evidence, "source": fact.source,
                 "source_label": fact.source_label, "timestamp": fact.timestamp,
                 "confidence": fact.confidence},
            ],
        )

    # 无数字事实支持 → Growth 逻辑不足
    return ConflictFinding(
        finding_id="",
        claim_id=claim_id,
        claim=claim_text,
        conflict_type=CONFLICT_GROWTH_INSUFFICIENT,
        graph_facts=[],
        difference="增长类 Claim 缺乏图谱数字事实支持，增长逻辑不充分",
        risk_type=CONFLICT_RISK_TYPE[CONFLICT_GROWTH_INSUFFICIENT],
        risk_score=CONFLICT_BASE_SCORE[CONFLICT_GROWTH_INSUFFICIENT],
        risk_level=risk_level_of(CONFLICT_BASE_SCORE[CONFLICT_GROWTH_INSUFFICIENT]),
        evidence_trace=[
            {"role": "claim", "text": claim_text},
            {"role": "fact", "text": "无对应增长数字事实", "source": "N/A"},
        ],
    )


# ---------------------------------------------------------------------------
# 检测 4：CONFLICT_COMPETITIVE_NO_EVIDENCE（Competitive 优势缺证据）
# ---------------------------------------------------------------------------
def _detect_competitive_no_evidence(
    claim_id: str,
    claim_text: str,
    facts: list[Fact],
) -> ConflictFinding | None:
    """Claim 含竞争领先关键词，但图谱无市场份额/排名强证据 → 缺证据。"""
    is_competitive_claim = any(kw in claim_text for kw in _COMPETITIVE_KW)
    if not is_competitive_claim:
        return None

    # 检查图谱中是否有强证据（市场份额/排名/第一）
    strong_evidence_kws = ("市场份额", "行业第一", "第一", "排名", "出货量")
    strong_facts = [
        f for f in facts
        if any(kw in f"{f.predicate} {f.evidence}" for kw in strong_evidence_kws)
    ]

    if strong_facts:
        fact = strong_facts[0]
        return ConflictFinding(
            finding_id="",
            claim_id=claim_id,
            claim=claim_text,
            conflict_type=CONFLICT_NO_OPPOSITION,
            graph_facts=[fact.to_dict()],
            difference="竞争优势 Claim 有图谱强证据支持",
            risk_type=CONFLICT_RISK_TYPE[CONFLICT_NO_OPPOSITION],
            risk_score=0.0,
            risk_level="LOW",
            evidence_trace=[
                {"role": "claim", "text": claim_text},
                {"role": "fact", "text": fact.evidence, "source": fact.source,
                 "source_label": fact.source_label, "timestamp": fact.timestamp,
                 "confidence": fact.confidence},
            ],
        )

    # 无强证据 → 缺证据
    return ConflictFinding(
        finding_id="",
        claim_id=claim_id,
        claim=claim_text,
        conflict_type=CONFLICT_COMPETITIVE_NO_EVIDENCE,
        graph_facts=[],
        difference="竞争优势 Claim 缺少市场份额/排名等图谱强证据支持",
        risk_type=CONFLICT_RISK_TYPE[CONFLICT_COMPETITIVE_NO_EVIDENCE],
        risk_score=CONFLICT_BASE_SCORE[CONFLICT_COMPETITIVE_NO_EVIDENCE],
        risk_level=risk_level_of(CONFLICT_BASE_SCORE[CONFLICT_COMPETITIVE_NO_EVIDENCE]),
        evidence_trace=[
            {"role": "claim", "text": claim_text},
            {"role": "fact", "text": "无竞争优势强证据", "source": "N/A"},
        ],
    )


# ---------------------------------------------------------------------------
# 主入口：detect_conflicts
# ---------------------------------------------------------------------------
@dataclass
class DetectionResult:
    findings: list[ConflictFinding]
    conflict_count: int  # 实际冲突数（不含 NO_OPPOSITION）
    support_count: int   # NO_OPPOSITION 数


def detect_conflicts(
    claims: list[dict],
    graph: KnowledgeGraph,
) -> DetectionResult:
    """对所有 Claim 进行冲突推理（基于知识图谱）。

    每个 Claim 至多产出一条 Finding，按优先级：
    1. CONFLICT_CLAIM_VS_FACT（数字比对）
    2. CONFLICT_BUSINESS_OVERSTATEMENT（夸大表达）
    3. CONFLICT_GROWTH_INSUFFICIENT（增长逻辑）
    4. CONFLICT_COMPETITIVE_NO_EVIDENCE（竞争优势缺证据）
    5. NO_OPPOSITION（无冲突/支持）
    """
    findings: list[ConflictFinding] = []
    fid_idx = 1

    for claim in claims:
        claim_id = claim.get("claim_id") or claim.get("claim_uid") or f"CLM-{fid_idx:04d}"
        claim_text = (
            claim.get("original_text")
            or claim.get("source_text")
            or claim.get("claim", "")
        )
        if not claim_text:
            continue

        # 图谱事实
        facts = graph.facts

        # 按优先级检测
        chosen: ConflictFinding | None = None

        # 优先级 1：数字比对
        chosen = _detect_claim_vs_fact(claim_id, claim_text, facts)
        # 优先级 2：夸大表达
        if chosen is None:
            chosen = _detect_business_overstatement(claim_id, claim_text, facts)
        # 优先级 3：增长逻辑
        if chosen is None:
            chosen = _detect_growth_insufficient(claim_id, claim_text, facts)
        # 优先级 4：竞争优势缺证据
        if chosen is None:
            chosen = _detect_competitive_no_evidence(claim_id, claim_text, facts)

        # 兜底：无任何比对结论 → NO_OPPOSITION
        if chosen is None:
            chosen = ConflictFinding(
                finding_id="",
                claim_id=claim_id,
                claim=claim_text,
                conflict_type=CONFLICT_NO_OPPOSITION,
                graph_facts=[],
                difference="未找到与该 Claim 匹配的图谱事实",
                risk_type=CONFLICT_RISK_TYPE[CONFLICT_NO_OPPOSITION],
                risk_score=0.0,
                risk_level="LOW",
                evidence_trace=[
                    {"role": "claim", "text": claim_text},
                    {"role": "fact", "text": "无可比图谱事实", "source": "N/A"},
                ],
            )

        chosen.finding_id = f"CFLT-{fid_idx:04d}"
        fid_idx += 1
        findings.append(chosen)

    conflict_count = sum(
        1 for f in findings if f.conflict_type != CONFLICT_NO_OPPOSITION
    )
    support_count = sum(
        1 for f in findings if f.conflict_type == CONFLICT_NO_OPPOSITION
    )

    return DetectionResult(
        findings=findings,
        conflict_count=conflict_count,
        support_count=support_count,
    )


# ---------------------------------------------------------------------------
# 整体风险评分
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
