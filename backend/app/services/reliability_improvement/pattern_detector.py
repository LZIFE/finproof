"""FinProof Pattern Detector（Phase 23，任务书 §识别）。

聚合 FailureCase → FailurePattern（含 root_cause + suggested_improvement）+
WeaknessMap（source × pattern 矩阵）。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.services.reliability_improvement.schemas import (
    FailureCase,
    FailurePattern,
    PATTERN_EVIDENCE_MISSING,
    PATTERN_LABELS,
    PATTERN_LOGICAL_GAP,
    PATTERN_NUMERIC_ERROR,
    PATTERN_PERIOD_CONFUSION,
    PATTERN_TYPES,
    PATTERN_UNSUPPORTED_CLAIM,
    SOURCE_TYPES,
    WeaknessCell,
    WeaknessMap,
)


# ---------------------------------------------------------------------------
# root_cause + suggested_improvement 知识库（按 pattern）
# ---------------------------------------------------------------------------
PATTERN_ROOT_CAUSE = {
    PATTERN_NUMERIC_ERROR: "数值口径不一致或计算错误：模型直接生成未核实的财务增长率/百分比，未绑定原始报表数值。",
    PATTERN_PERIOD_CONFUSION: "期间混淆：模型将不同年度/季度的数据错配，未区分报告期与基期。",
    PATTERN_UNSUPPORTED_CLAIM: "无依据主张：模型生成强结论但未检索到对应证据，幻觉风险。",
    PATTERN_EVIDENCE_MISSING: "证据缺失：主张提及指标但证据未覆盖，证据覆盖率不足。",
    PATTERN_LOGICAL_GAP: "逻辑缺口：因果倒置/相关性当因果/结论过度外推/隐藏假设未显式化。",
}

PATTERN_IMPROVEMENT = {
    PATTERN_NUMERIC_ERROR: [
        "在生成数值前强制对齐原始报表口径，所有增长率/百分比必须绑定 block_id + document_id + page。",
        "引入数值一致性校验：增长率 = (本期 - 上期) / 上期，校验计算是否匹配原文。",
        "对未检索到原始数值的主张标记 INSUFFICIENT_DATA，不强行生成。",
    ],
    PATTERN_PERIOD_CONFUSION: [
        "抽取证据时显式标注报告期（report_period）与基期，禁止跨期引用。",
        "在 Reasoning Engine 中启用 PERIOD_SUBSTITUTION 检查，命中即降级为部分支持。",
    ],
    PATTERN_UNSUPPORTED_CLAIM: [
        "对无 Evidence 绑定的主张强制标记 unsupported，不进入最终结论。",
        "Red Team 增加 Unsupported Claim 攻击比例，提升幻觉检出率阈值至 0.9。",
    ],
    PATTERN_EVIDENCE_MISSING: [
        "提升 Evidence Retrieval 覆盖阈值，主张提及的指标必须命中证据。",
        "Auditor 在审计阶段强制检查 Evidence Coverage，低于 1.0 即记 issue。",
    ],
    PATTERN_LOGICAL_GAP: [
        "在 Reasoning Engine 中启用全部 9 类逻辑检查，CONCLUSION_OVERREACH 命中即降级。",
        "Arena Skeptic 增加 Overstatement 挑战权重，强表述低置信的观点必被挑战。",
        "对因果类主张强制标注假设（assumptions），隐藏假设显式化。",
    ],
}


def detect_patterns(failures: list[FailureCase], totals: dict[str, int]) -> list[FailurePattern]:
    """聚合失败案例 → 5 类 FailurePattern（含 root_cause + suggested_improvement）。"""
    by_pattern: dict[str, list[FailureCase]] = defaultdict(list)
    for f in failures:
        by_pattern[f.pattern].append(f)

    # 总案例数 = 各来源 totals 之和（避免重复）
    total_cases = sum(totals.values()) if totals else max(1, len(failures))

    patterns: list[FailurePattern] = []
    for pt in PATTERN_TYPES:
        cases = by_pattern.get(pt, [])
        if not cases:
            # 即便无案例，也产出空模式（前端展示 5 类齐全）
            patterns.append(FailurePattern(
                pattern=pt,
                failure_count=0,
                failure_rate=0.0,
                affected_category="",
                example_cases=[],
                root_cause=PATTERN_ROOT_CAUSE.get(pt, ""),
                suggested_improvement="；".join(PATTERN_IMPROVEMENT.get(pt, [])),
            ))
            continue
        # affected_category：来源占比最多的
        src_counts = Counter(c.source for c in cases)
        top_src = src_counts.most_common(1)[0][0] if src_counts else ""
        patterns.append(FailurePattern(
            pattern=pt,
            failure_count=len(cases),
            failure_rate=len(cases) / total_cases,
            affected_category=top_src,
            example_cases=cases[:5],
            root_cause=PATTERN_ROOT_CAUSE.get(pt, ""),
            suggested_improvement="；".join(PATTERN_IMPROVEMENT.get(pt, [])),
        ))
    return patterns


def build_weakness_map(failures: list[FailureCase]) -> WeaknessMap:
    """构建 source × pattern 弱点矩阵。"""
    cells: list[WeaknessCell] = []
    src_pattern_counts: dict[tuple[str, str], int] = defaultdict(int)
    src_totals: dict[str, int] = defaultdict(int)
    for f in failures:
        src_pattern_counts[(f.source, f.pattern)] += 1
        src_totals[f.source] += 1
    max_count = 0
    for src in SOURCE_TYPES:
        for pt in PATTERN_TYPES:
            cnt = src_pattern_counts.get((src, pt), 0)
            rate = cnt / src_totals[src] if src_totals[src] else 0.0
            cells.append(WeaknessCell(source=src, pattern=pt, count=cnt, rate=rate))
            max_count = max(max_count, cnt)
    return WeaknessMap(
        cells=cells,
        sources=list(SOURCE_TYPES),
        patterns=list(PATTERN_TYPES),
        max_count=max_count,
    )


__all__ = [
    "PATTERN_ROOT_CAUSE", "PATTERN_IMPROVEMENT",
    "detect_patterns", "build_weakness_map",
]
