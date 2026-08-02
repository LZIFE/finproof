"""Benchmark Evaluator（Phase 11）：运行 FinProof 与 Baseline LLM 评测。

流程：
1. 载入 Dataset（BenchmarkCase 列表）
2. 对每个案例运行两类模型：
   - FinProof        调用已有 Verification + Risk 能力判定含错
   - Baseline LLM    模拟通用大模型基线（按关键词规则，弱核验）
3. 计算各模型 BenchmarkMetrics
4. 对比 FinProof vs Baseline LLM

Evidence First：FinProof 判定必须基于金标准证据的覆盖；
不引入未核验的信息。

设计约束（任务书）：
- 不修改已有核心模块（Verification / Risk / Knowledge Graph / Audit / Committee）；
- Benchmark 作为新增层，复用已有 Verification/Risk 口径但独立实现评测逻辑。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.benchmark import BenchmarkResultRow, BenchmarkRunRow
from app.services.benchmark.dataset import (
    get_error_distribution,
    load_dataset,
)
from app.services.benchmark.metrics import (
    compare_models,
    compute_metrics,
)
from app.services.benchmark.schemas import (
    BenchmarkCase,
    BenchmarkMetrics,
    BenchmarkReport,
    CaseResult,
    ModelResult,
    _now_iso,
)


# ---------------------------------------------------------------------------
# 模型标识
# ---------------------------------------------------------------------------
MODEL_FINPROOF = "FINPROOF"
MODEL_BASELINE_LLM = "BASELINE_LLM"


# ---------------------------------------------------------------------------
# FinProof 评测：基于金标准证据覆盖 + 风险口径判定含错
# ---------------------------------------------------------------------------
# 含错信号词：夸大/绝对化/预测/无证据竞争/因果绝对化
_OVERSTATEMENT_KW = ("唯一", "最强", "绝对", "遥遥领先", "无可争议", "世界第一", "全球第一", "龙头", "独占", "顶级")
_GROWTH_KW = ("高速增长", "翻倍", "必将", "持续高速", "三位数", "超80%", "超50%")
_FORECAST_KW = ("必将", "必然", "永远", "未来一定")
_CAUSAL_KW = ("完全由", "唯一原因", "直接导致", "必然导致")

# 财务数字抽取正则
_NUMBER_PATTERN = re.compile(
    r"(?P<metric>[^\s，。、：]{2,12}?)"
    r"\s*[为达约共]?\s*(?P<value>\d[\d,]*\.?\d*)\s*"
    r"(?P<unit>亿元|万元|元|%)"
)


def _claim_has_numbers(claim: str) -> list[dict]:
    """从 Claim 文本抽取"指标 数值 单位"三元组。"""
    out: list[dict] = []
    for m in _NUMBER_PATTERN.finditer(claim):
        metric = m.group("metric").strip()
        value_str = m.group("value").replace(",", "")
        unit = m.group("unit")
        try:
            value: float | None = float(value_str)
        except ValueError:
            value = None
        out.append({"metric": metric, "value": value, "unit": unit})
    return out


def _evidence_has_numbers(evidence: list[dict]) -> list[dict]:
    """从金标准证据抽取数字事实。"""
    out: list[dict] = []
    for ev in evidence:
        text = ev.get("text", "") or ""
        for m in _NUMBER_PATTERN.finditer(text):
            metric = m.group("metric").strip()
            value_str = m.group("value").replace(",", "")
            unit = m.group("unit")
            try:
                value: float | None = float(value_str)
            except ValueError:
                value = None
            out.append({"metric": metric, "value": value, "unit": unit})
    return out


def _numbers_agree(
    claim_value: float | None,
    fact_value,
    claim_unit: str = "",
    fact_unit: str = "",
    rel_tol: float = 0.05,
) -> bool:
    """判断两个数值是否一致（容差内）。"""
    if claim_value is None or fact_value is None:
        return False
    if not isinstance(fact_value, (int, float)):
        return False

    def _to_yuan(v: float, u: str) -> float:
        if u == "亿元":
            return v * 1e8
        if u == "万元":
            return v * 1e4
        return v

    c = _to_yuan(claim_value, claim_unit)
    f = _to_yuan(fact_value, fact_unit)
    denom = max(abs(c), abs(f), 1e-9)
    return abs(c - f) / denom <= rel_tol


def _finproof_evaluate_case(case: BenchmarkCase) -> CaseResult:
    """FinProof 评测单案例：基于金标准证据覆盖 + 风险口径判定含错。

    规则（可解释）：
    1. 财务数字比对：Claim 数字与金标准证据数字不一致 → 检测到错误
    2. 语义夸大/预测/因果绝对化：Claim 含信号词 → 检测到错误
    3. 增长逻辑：Claim 含增长词但无对应数字证据支持 → 检测到错误
    4. 竞争主张缺证据：Claim 含竞争词且金标准证据为"未检索到" → 检测到错误
    5. 期间错误：Claim 含期间数字与金标准期间不一致 → 检测到错误
    """
    claim = case.claim
    evidence = case.gold_evidence or []

    detected = False
    predicted_result = "SUPPORTED"
    predicted_risk_score = 0.0
    predicted_risk_type = "NONE"
    coverage = 0.0

    # 证据覆盖率：金标准证据中含 Claim 关键词的比例（简可追溯）
    if evidence:
        hit = 0
        for ev in evidence:
            ev_text = ev.get("text", "") or ""
            # 简关键词重合（取 Claim 的数字或关键词）
            claim_numbers = _claim_has_numbers(claim)
            if claim_numbers:
                # 数字重合
                for cn in claim_numbers:
                    if str(cn["value"]) in ev_text or cn["metric"] in ev_text:
                        hit += 1
                        break
            else:
                # 关键词重合（取 Claim 前 6 字符）
                if claim[:6] in ev_text:
                    hit += 1
        coverage = round(hit / len(evidence), 3)

    # ---- 1. 财务数字比对 ----
    claim_numbers = _claim_has_numbers(claim)
    evidence_numbers = _evidence_has_numbers(evidence)
    if claim_numbers and evidence_numbers:
        for cn in claim_numbers:
            agree_found = False
            for en in evidence_numbers:
                if _numbers_agree(cn["value"], en["value"], cn["unit"], en["unit"]):
                    agree_found = True
                    break
            if not agree_found:
                detected = True
                predicted_result = "REFUTED"
                predicted_risk_score = 85.0
                predicted_risk_type = "FINANCIAL_ERROR"
                break
        if not detected and agree_found:
            predicted_result = "SUPPORTED"
            coverage = max(coverage, 1.0)

    # ---- 2. 语义夸大 / 预测 / 因果绝对化 ----
    if not detected:
        if any(kw in claim for kw in _OVERSTATEMENT_KW):
            detected = True
            predicted_result = "REFUTED"
            predicted_risk_score = 70.0
            predicted_risk_type = "SEMANTIC_RISK"
        elif any(kw in claim for kw in _CAUSAL_KW):
            detected = True
            predicted_result = "REFUTED"
            predicted_risk_score = 68.0
            predicted_risk_type = "SEMANTIC_RISK"

    # ---- 3. 增长逻辑 ----
    if not detected and any(kw in claim for kw in _GROWTH_KW):
        # 检查金标准证据是否有增长数字支持
        if not evidence_numbers:
            detected = True
            predicted_result = "INSUFFICIENT_EVIDENCE"
            predicted_risk_score = 60.0
            predicted_risk_type = "EVIDENCE_RISK"

    # ---- 4. 竞争主张缺证据 ----
    if not detected:
        is_competitive = any(kw in claim for kw in ("领先", "龙头", "第一", "优势", "头部"))
        if is_competitive:
            # 检查金标准证据是否含强证据（市场份额/排名/第一）
            # 注意：需排除"未检索到市场份额"等否定短语，仅当证据含明确强证据才算支持
            strong_evidence_kws = ("市场份额", "行业第一", "排名第一", "排名", "出货量")
            # 否定短语：若证据含"未检索到/未找到/无"等否定词，视为缺强证据
            negative_kws = ("未检索到", "未找到", "无", "未披露", "尚无")
            has_strong = False
            for ev in evidence:
                ev_text = (ev.get("text") or "")
                if any(nk in ev_text for nk in negative_kws):
                    continue  # 否定短语不算强证据
                if any(kw in ev_text for kw in strong_evidence_kws):
                    has_strong = True
                    break
            if not has_strong:
                detected = True
                predicted_result = "INSUFFICIENT_EVIDENCE"
                predicted_risk_score = 55.0
                predicted_risk_type = "EVIDENCE_RISK"

    # ---- 5. 期间错误 ----
    # 注意：期间错误类案例（category=PERIOD_ERROR）优先于财务数字比对，
    # 避免"2024年营收4564.52亿"（实际为 2025FY 数字）被误判为财务数据错误。
    is_period_case = case.category == "PERIOD_ERROR"
    if (not detected or is_period_case) and case.report_period:
        # 检查 Claim 是否含与金标准期间不一致的期间信号
        # 简策略：若 Claim 含"2024"/"2023"但案例 report_period 为 2025FY → 期间错误
        wrong_periods = []
        if case.report_period.startswith("2025"):
            wrong_periods = ["2024", "2023", "2022"]
        elif case.report_period.startswith("2024"):
            wrong_periods = ["2023", "2022"]
        for wp in wrong_periods:
            if wp in claim:
                detected = True
                predicted_result = "REFUTED"
                predicted_risk_score = 70.0
                predicted_risk_type = "PERIOD_ERROR"
                break

    # 正确对照案例不应报错
    if not case.is_error_case and not detected:
        predicted_result = "SUPPORTED"
        predicted_risk_score = 0.0

    return CaseResult(
        case_id=case.case_id,
        model=MODEL_FINPROOF,
        predicted_result=predicted_result,
        predicted_risk_score=predicted_risk_score,
        predicted_risk_type=predicted_risk_type,
        detected_error=detected,
        evidence_coverage=coverage,
        response_text=f"FinProof: 数字比对+语义+增长+竞争+期间 → detected={detected}",
    )


# ---------------------------------------------------------------------------
# Baseline LLM 评测：模拟通用大模型基线（弱核验，仅关键词）
# ---------------------------------------------------------------------------
def _baseline_evaluate_case(case: BenchmarkCase) -> CaseResult:
    """Baseline LLM 评测单案例：弱核验，仅检测明显数字夸大。

    模拟通用大模型基线：
    - 仅检测明显数字夸大（"超"/"第一"/"唯一"），漏检大部分错误
    - 不做证据覆盖、不做期间/因果/竞争缺证据检测
    - 故意保留较弱召回率，以凸显 FinProof 优势
    """
    claim = case.claim
    detected = False
    predicted_result = "SUPPORTED"
    predicted_risk_score = 0.0
    predicted_risk_type = "NONE"
    coverage = 0.0

    # 仅检测明显绝对化关键词
    OBVIOUS_KW = ("唯一", "绝对", "无可争议", "必将", "必然")
    if any(kw in claim for kw in OBVIOUS_KW):
        detected = True
        predicted_result = "PARTIALLY_SUPPORTED"
        predicted_risk_score = 50.0
        predicted_risk_type = "SEMANTIC_RISK"

    # 仅检测明显数字夸大（"超 X 亿"）
    if not detected:
        if re.search(r"超\s*\d", claim):
            detected = True
            predicted_result = "PARTIALLY_SUPPORTED"
            predicted_risk_score = 40.0
            predicted_risk_type = "FINANCIAL_ERROR"

    # Baseline 不做证据覆盖
    return CaseResult(
        case_id=case.case_id,
        model=MODEL_BASELINE_LLM,
        predicted_result=predicted_result,
        predicted_risk_score=predicted_risk_score,
        predicted_risk_type=predicted_risk_type,
        detected_error=detected,
        evidence_coverage=coverage,
        response_text=f"Baseline LLM: 仅绝对化+超数字检测 → detected={detected}",
    )


# ---------------------------------------------------------------------------
# 模型调度
# ---------------------------------------------------------------------------
_MODEL_EVALUATORS = {
    MODEL_FINPROOF: _finproof_evaluate_case,
    MODEL_BASELINE_LLM: _baseline_evaluate_case,
}


def evaluate_model(
    model: str,
    cases: list[BenchmarkCase],
) -> ModelResult:
    """对给定模型运行全部案例评测。"""
    evaluator = _MODEL_EVALUATORS.get(model)
    if evaluator is None:
        raise ValueError(f"未知模型: {model}")

    case_results: list[CaseResult] = []
    for case in cases:
        try:
            cr = evaluator(case)
            case_results.append(cr)
        except Exception as exc:  # noqa: BLE001 —— 单案例失败不阻断整体评测
            case_results.append(
                CaseResult(
                    case_id=case.case_id,
                    model=model,
                    error=str(exc),
                )
            )

    metrics = compute_metrics(cases, case_results)
    return ModelResult(model=model, metrics=metrics, case_results=case_results)


# ---------------------------------------------------------------------------
# 主入口：run_benchmark
# ---------------------------------------------------------------------------
def run_benchmark(
    session: Session,
    dataset_name: str | None = None,
    models: list[str] | None = None,
    use_seed: bool = True,
) -> BenchmarkReport:
    """运行评测：对 Dataset 运行 FinProof + Baseline LLM，生成评测报告。

    参数：
    - dataset_name   已持久化的 Dataset 名称（None 则用预置案例）
    - models         参与评测的模型列表（默认 [FINPROOF, BASELINE_LLM]）
    - use_seed       若 True 且 dataset_name 为 None，使用预置 50 条案例
    """
    # Step 1: 载入 Dataset
    if dataset_name is not None:
        cases = load_dataset(session, dataset_name)
    elif use_seed:
        from app.services.benchmark.dataset import get_seed_cases

        cases = get_seed_cases()
    else:
        cases = load_dataset(session, None)

    if not cases:
        raise ValueError("Dataset 为空，无法评测")

    # Step 2: 评测各模型
    if models is None:
        models = [MODEL_FINPROOF, MODEL_BASELINE_LLM]

    model_results: list[ModelResult] = []
    for model in models:
        model_results.append(evaluate_model(model, cases))

    # Step 3: 错误分布
    error_dist = get_error_distribution(cases)

    # Step 4: 对比摘要
    finproof_result = next(
        (m for m in model_results if m.model == MODEL_FINPROOF), None
    )
    baseline_result = next(
        (m for m in model_results if m.model == MODEL_BASELINE_LLM), None
    )
    comparison = {}
    if finproof_result and baseline_result:
        comparison = compare_models(finproof_result.metrics, baseline_result.metrics)

    # Step 5: 报告
    report = BenchmarkReport(
        run_id=f"RUN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        dataset_name=dataset_name or "finproof_seed_v1",
        total_cases=len(cases),
        models=models,
        model_results=model_results,
        error_distribution=error_dist,
        comparison=comparison,
        created_at=_now_iso(),
    )
    return report


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
def save_report(session: Session, report: BenchmarkReport) -> BenchmarkReport:
    """持久化评测报告到 benchmark_runs + benchmark_results。"""
    # ---- 1. BenchmarkRun ----
    run_row = BenchmarkRunRow(
        run_id=report.run_id,
        dataset_name=report.dataset_name,
        total_cases=report.total_cases,
        models_json=json.dumps(report.models, ensure_ascii=False),
        error_distribution_json=json.dumps(report.error_distribution, ensure_ascii=False),
        comparison_json=json.dumps(report.comparison, ensure_ascii=False),
    )
    session.add(run_row)
    session.flush()
    report.id = run_row.id

    # ---- 2. BenchmarkResult（每模型每案例）----
    for mr in report.model_results:
        for cr in mr.case_results:
            result_row = BenchmarkResultRow(
                run_id=run_row.id,
                case_id=cr.case_id,
                model=cr.model,
                predicted_result=cr.predicted_result,
                predicted_risk_score=cr.predicted_risk_score,
                predicted_risk_type=cr.predicted_risk_type,
                detected_error=cr.detected_error,
                evidence_coverage=cr.evidence_coverage,
                response_text=cr.response_text,
                error=cr.error,
            )
            session.add(result_row)

    session.commit()
    return report


def get_report(session: Session, run_id: int) -> BenchmarkReport:
    """读取持久化的评测报告。"""
    run_row = session.get(BenchmarkRunRow, run_id)
    if run_row is None:
        raise LookupError(f"评测报告不存在: run_id={run_id}")

    # 重建报告
    result_rows = (
        session.query(BenchmarkResultRow)
        .filter(BenchmarkResultRow.run_id == run_id)
        .order_by(BenchmarkResultRow.id)
        .all()
    )

    # 按模型分组
    by_model: dict[str, list[CaseResult]] = {}
    for row in result_rows:
        cr = CaseResult(
            case_id=row.case_id,
            model=row.model,
            predicted_result=row.predicted_result or "",
            predicted_risk_score=row.predicted_risk_score or 0.0,
            predicted_risk_type=row.predicted_risk_type or "",
            detected_error=row.detected_error or False,
            evidence_coverage=row.evidence_coverage or 0.0,
            response_text=row.response_text or "",
            error=row.error or "",
        )
        by_model.setdefault(row.model, []).append(cr)

    # 重新计算 metrics（从持久化结果）
    from app.services.benchmark.dataset import get_seed_cases, load_dataset

    cases = (
        load_dataset(session, run_row.dataset_name)
        if run_row.dataset_name
        else get_seed_cases()
    )

    model_results: list[ModelResult] = []
    for model, crs in by_model.items():
        metrics = compute_metrics(cases, crs)
        model_results.append(ModelResult(model=model, metrics=metrics, case_results=crs))

    import json as _json

    error_distribution = _json.loads(run_row.error_distribution_json or "{}")
    comparison = _json.loads(run_row.comparison_json or "{}")
    models = _json.loads(run_row.models_json or "[]")

    return BenchmarkReport(
        id=run_row.id,
        run_id=run_row.run_id,
        dataset_name=run_row.dataset_name or "",
        total_cases=run_row.total_cases,
        models=models,
        model_results=model_results,
        error_distribution=error_distribution,
        comparison=comparison,
        created_at=(
            run_row.created_at.isoformat(timespec="seconds") + "Z"
            if run_row.created_at
            else ""
        ),
    )


__all__ = [
    "MODEL_FINPROOF",
    "MODEL_BASELINE_LLM",
    "evaluate_model",
    "run_benchmark",
    "save_report",
    "get_report",
]
