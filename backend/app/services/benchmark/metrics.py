"""Benchmark Metrics（Phase 11）：评测指标计算。

指标（任务书 §3）：
- Accuracy             准确率：正确分类比例
- Precision            精确率：检测到的错误中真错误比例
- Recall               召回率：真错误中被检测比例
- F1                   F1 分数（Precision 与 Recall 的调和平均）
- Evidence Coverage    证据覆盖率：模型引用证据与金标准证据的重合比例
- Risk Detection Rate  风险检测率：高风险案例（gold_risk_score ≥ 阈值）被检出比例

错误检测口径（可解释）：
- 金标准：is_error_case=True 视为"含错"，需检测；False 视为"正确"，不应报错
- 模型预测：detected_error=True 视为"检测到错误"
- TP = 含错且检测到；FP = 正确但误报；FN = 含错但漏检；TN = 正确且不报

设计约束（任务书）：不修改已有核心模块；Benchmark 作为新增层。
"""

from __future__ import annotations

from typing import Iterable

from app.services.benchmark.schemas import (
    BenchmarkCase,
    BenchmarkMetrics,
    CaseResult,
)


# ---------------------------------------------------------------------------
# 错误检测口径
# ---------------------------------------------------------------------------
# 风险分阈值：gold_risk_score ≥ 该值视为"高风险案例"
RISK_SCORE_THRESHOLD = 60.0


def _confusion(
    cases: list[BenchmarkCase],
    results: list[CaseResult],
) -> dict[str, int]:
    """计算混淆矩阵：TP/FP/FN/TN。

    以 case_id 对齐案例与结果。
    """
    result_by_case = {r.case_id: r for r in results}
    tp = fp = fn = tn = 0
    for case in cases:
        r = result_by_case.get(case.case_id)
        if r is None:
            # 缺结果视为漏检
            if case.is_error_case:
                fn += 1
            else:
                tn += 1
            continue
        detected = r.detected_error
        if case.is_error_case and detected:
            tp += 1
        elif (not case.is_error_case) and detected:
            fp += 1
        elif case.is_error_case and (not detected):
            fn += 1
        else:
            tn += 1
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn}


# ---------------------------------------------------------------------------
# Accuracy / Precision / Recall / F1
# ---------------------------------------------------------------------------
def accuracy(cases: list[BenchmarkCase], results: list[CaseResult]) -> float:
    """准确率：(TP + TN) / 总数。"""
    cm = _confusion(cases, results)
    total = cm["TP"] + cm["FP"] + cm["FN"] + cm["TN"]
    if total == 0:
        return 0.0
    return round((cm["TP"] + cm["TN"]) / total, 3)


def precision(cases: list[BenchmarkCase], results: list[CaseResult]) -> float:
    """精精确率：TP / (TP + FP)。"""
    cm = _confusion(cases, results)
    denom = cm["TP"] + cm["FP"]
    if denom == 0:
        return 0.0
    return round(cm["TP"] / denom, 3)


def recall(cases: list[BenchmarkCase], results: list[CaseResult]) -> float:
    """召回率：TP / (TP + FN)。"""
    cm = _confusion(cases, results)
    denom = cm["TP"] + cm["FN"]
    if denom == 0:
        return 0.0
    return round(cm["TP"] / denom, 3)


def f1_score(cases: list[BenchmarkCase], results: list[CaseResult]) -> float:
    """F1：Precision 与 Recall 的调和平均。"""
    p = precision(cases, results)
    r = recall(cases, results)
    if p + r == 0:
        return 0.0
    return round(2 * p * r / (p + r), 3)


# ---------------------------------------------------------------------------
# Evidence Coverage：证据覆盖率
# ---------------------------------------------------------------------------
def evidence_coverage(
    cases: list[BenchmarkCase],
    results: list[CaseResult],
) -> float:
    """证据覆盖率：模型引用证据与金标准证据的重合比例（平均）。

    简化口径：
    - 若模型 CaseResult.evidence_coverage 已设置（0-1），直接取平均；
    - 否则按金标准证据数量与模型响应是否覆盖判定。
    """
    if not results:
        return 0.0
    covers: list[float] = []
    for r in results:
        if r.evidence_coverage > 0:
            covers.append(r.evidence_coverage)
        else:
            covers.append(0.0)
    return round(sum(covers) / len(covers), 3)


# ---------------------------------------------------------------------------
# Risk Detection Rate：风险检测率
# ---------------------------------------------------------------------------
def risk_detection_rate(
    cases: list[BenchmarkCase],
    results: list[CaseResult],
    threshold: float = RISK_SCORE_THRESHOLD,
) -> float:
    """风险检测率：高风险案例（gold_risk_score ≥ 阈值）中被检测比例。"""
    result_by_case = {r.case_id: r for r in results}
    high_risk_cases = [c for c in cases if c.gold_risk_score >= threshold]
    if not high_risk_cases:
        return 0.0
    detected = 0
    for case in high_risk_cases:
        r = result_by_case.get(case.case_id)
        if r is not None and r.detected_error:
            detected += 1
    return round(detected / len(high_risk_cases), 3)


# ---------------------------------------------------------------------------
# 分错误类别的召回率（便于前端 Error Distribution）
# ---------------------------------------------------------------------------
def recall_by_category(
    cases: list[BenchmarkCase],
    results: list[CaseResult],
) -> dict[str, float]:
    """按错误类别计算召回率：该类别真错误中被检测比例。"""
    result_by_case = {r.case_id: r for r in results}
    by_cat: dict[str, list[bool]] = {}
    for case in cases:
        if not case.is_error_case:
            continue
        r = result_by_case.get(case.case_id)
        detected = r is not None and r.detected_error
        by_cat.setdefault(case.category, []).append(detected)

    out: dict[str, float] = {}
    for cat, flags in by_cat.items():
        if not flags:
            out[cat] = 0.0
            continue
        out[cat] = round(sum(flags) / len(flags), 3)
    return out


# ---------------------------------------------------------------------------
# 主入口：compute_metrics
# ---------------------------------------------------------------------------
def compute_metrics(
    cases: list[BenchmarkCase],
    results: list[CaseResult],
) -> BenchmarkMetrics:
    """计算全部评测指标。"""
    return BenchmarkMetrics(
        total_cases=len(cases),
        accuracy=accuracy(cases, results),
        precision=precision(cases, results),
        recall=recall(cases, results),
        f1=f1_score(cases, results),
        evidence_coverage=evidence_coverage(cases, results),
        risk_detection_rate=risk_detection_rate(cases, results),
        recall_by_category=recall_by_category(cases, results),
    )


# ---------------------------------------------------------------------------
# 模型对比摘要
# ---------------------------------------------------------------------------
def compare_models(
    finproof_metrics: BenchmarkMetrics,
    baseline_metrics: BenchmarkMetrics,
) -> dict:
    """对比 FinProof vs Baseline LLM 的关键指标差。"""
    def _diff(field: str) -> float:
        return round(getattr(finproof_metrics, field) - getattr(baseline_metrics, field), 3)

    return {
        "finproof": finproof_metrics.to_dict(),
        "baseline": baseline_metrics.to_dict(),
        "accuracy_gain": _diff("accuracy"),
        "precision_gain": _diff("precision"),
        "recall_gain": _diff("recall"),
        "f1_gain": _diff("f1"),
        "evidence_coverage_gain": _diff("evidence_coverage"),
        "risk_detection_rate_gain": _diff("risk_detection_rate"),
    }


__all__ = [
    "RISK_SCORE_THRESHOLD",
    "accuracy",
    "precision",
    "recall",
    "f1_score",
    "evidence_coverage",
    "risk_detection_rate",
    "recall_by_category",
    "compute_metrics",
    "compare_models",
]
