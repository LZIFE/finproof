"""Phase 11 Financial AIBenchmark 专项测试。

覆盖任务书 §8：
- dataset 测试（案例载入/错误分布/校验）
- evaluation 测试（FinProof + Baseline LLM 评测）
- metric 测试（Accuracy/Precision/Recall/F1/Coverage/RiskDetectionRate）
- API 测试（POST /runs / GET /runs/{id} / GET /dataset）

设计约束：不修改已有核心模块；Benchmark 作为新增层。
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal, init_db
from app.services.benchmark.dataset import (
    SEED_CASES,
    get_error_distribution,
    get_seed_cases,
    load_dataset,
    seed_dataset,
    validate_case,
)
from app.services.benchmark.evaluator import (
    MODEL_BASELINE_LLM,
    MODEL_FINPROOF,
    evaluate_model,
    get_report,
    run_benchmark,
    save_report,
)
from app.services.benchmark.metrics import (
    RISK_SCORE_THRESHOLD,
    accuracy,
    compare_models,
    compute_metrics,
    evidence_coverage,
    f1_score,
    precision,
    recall,
    recall_by_category,
    risk_detection_rate,
)
from app.services.benchmark.schemas import (
    ERROR_CAUSAL_ERROR,
    ERROR_COMPETITIVE_CLAIM,
    ERROR_FINANCIAL_ERROR,
    ERROR_GROWTH_ERROR,
    ERROR_LABELS,
    ERROR_PERIOD_ERROR,
    ERROR_SEMANTIC_OVERSTATEMENT,
    ERROR_TYPES,
    BenchmarkCase,
    BenchmarkMetrics,
    CaseResult,
    GOLD_INSUFFICIENT,
    GOLD_PARTIALLY_SUPPORTED,
    GOLD_REFUTED,
    GOLD_SUPPORTED,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def _init():
    init_db()


# ---------------------------------------------------------------------------
# §8.1 Dataset 测试
# ---------------------------------------------------------------------------
def test_seed_cases_count_meets_requirement():
    """预置案例至少 50 条（任务书 §7）。"""
    cases = get_seed_cases()
    assert len(cases) >= 50


def test_seed_cases_cover_all_error_types():
    """预置案例覆盖全部 6 类错误。"""
    cases = get_seed_cases()
    categories = {c.category for c in cases}
    assert ERROR_TYPES.issubset(categories)


def test_seed_cases_have_unique_ids():
    cases = get_seed_cases()
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))
    assert all(cid.startswith("CASE-") for cid in ids)


def test_error_distribution_counts():
    """错误分布统计应正确。"""
    cases = get_seed_cases()
    dist = get_error_distribution(cases)
    # 总和应等于案例数
    assert sum(dist.values()) == len(cases)
    # 每类错误至少有 1 条
    for etype in ERROR_TYPES:
        assert etype in dist
        assert dist[etype] >= 1


def test_validate_case_rejects_missing_claim():
    case = BenchmarkCase(
        case_id="CASE-TEST",
        claim="",
        category=ERROR_FINANCIAL_ERROR,
        gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "营收 100 亿", "page": 1}],
        gold_result=GOLD_REFUTED,
    )
    errors = validate_case(case)
    assert any("claim" in e for e in errors)


def test_validate_case_rejects_bad_category():
    case = BenchmarkCase(
        case_id="CASE-TEST",
        claim="营收 200 亿",
        category="BAD_CATEGORY",
        gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "营收 100 亿", "page": 1}],
        gold_result=GOLD_REFUTED,
    )
    errors = validate_case(case)
    assert any("category" in e for e in errors)


def test_validate_case_rejects_missing_evidence():
    """Evidence First：金标准证据缺失应拒绝。"""
    case = BenchmarkCase(
        case_id="CASE-TEST",
        claim="营收 200 亿",
        category=ERROR_FINANCIAL_ERROR,
        gold_evidence=[],
        gold_result=GOLD_REFUTED,
    )
    errors = validate_case(case)
    assert any("gold_evidence" in e for e in errors)


def test_validate_case_accepts_valid():
    case = BenchmarkCase(
        case_id="CASE-TEST",
        claim="营收 200 亿",
        category=ERROR_FINANCIAL_ERROR,
        gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "营收 100 亿", "page": 1}],
        gold_result=GOLD_REFUTED,
    )
    assert validate_case(case) == []


def test_seed_dataset_persistence():
    """seed_dataset 持久化并可读回。"""
    with SessionLocal() as s:
        count = seed_dataset(s, dataset_name="test_seed_v1")
        assert count >= 50
        loaded = load_dataset(s, "test_seed_v1")
        assert len(loaded) == count
        # 案例字段完整
        for c in loaded:
            assert c.claim
            assert c.category in ERROR_TYPES
            assert c.gold_evidence


# ---------------------------------------------------------------------------
# §8.2 Metric 测试
# ---------------------------------------------------------------------------
def _make_cases_results() -> tuple[list[BenchmarkCase], list[CaseResult]]:
    """构造测试用案例与结果：
    - 3 含错案例（CASE-1/2/3），2 正确案例（CASE-4/5）
    - 模型检测到 CASE-1/2（TP=2），漏检 CASE-3（FN=1），误报 CASE-4（FP=1），正确放行 CASE-5（TN=1）
    """
    cases = [
        BenchmarkCase(case_id="CASE-1", claim="营收 200 亿", category=ERROR_FINANCIAL_ERROR,
                      gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "营收 100 亿", "page": 1}],
                      gold_result=GOLD_REFUTED, is_error_case=True, gold_risk_score=85.0),
        BenchmarkCase(case_id="CASE-2", claim="唯一龙头", category=ERROR_SEMANTIC_OVERSTATEMENT,
                      gold_evidence=[{"source": "NEWS", "text": "多家并列", "page": None}],
                      gold_result=GOLD_REFUTED, is_error_case=True, gold_risk_score=70.0),
        BenchmarkCase(case_id="CASE-3", claim="海外高速增长", category=ERROR_GROWTH_ERROR,
                      gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "海外增长 12%", "page": 6}],
                      gold_result=GOLD_REFUTED, is_error_case=True, gold_risk_score=60.0),
        BenchmarkCase(case_id="CASE-4", claim="营收 100 亿", category=ERROR_FINANCIAL_ERROR,
                      gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "营收 100 亿", "page": 1}],
                      gold_result=GOLD_SUPPORTED, is_error_case=False, gold_risk_score=0.0),
        BenchmarkCase(case_id="CASE-5", claim="净利润 50 亿", category=ERROR_FINANCIAL_ERROR,
                      gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "净利润 50 亿", "page": 2}],
                      gold_result=GOLD_SUPPORTED, is_error_case=False, gold_risk_score=0.0),
    ]
    results = [
        CaseResult(case_id="CASE-1", model="TEST", detected_error=True),
        CaseResult(case_id="CASE-2", model="TEST", detected_error=True),
        CaseResult(case_id="CASE-3", model="TEST", detected_error=False),  # 漏检
        CaseResult(case_id="CASE-4", model="TEST", detected_error=True),   # 误报
        CaseResult(case_id="CASE-5", model="TEST", detected_error=False),
    ]
    return cases, results


def test_accuracy_formula():
    cases, results = _make_cases_results()
    # (TP+TN)/total = (2+1)/5 = 0.6
    assert accuracy(cases, results) == 0.6


def test_precision_formula():
    cases, results = _make_cases_results()
    # TP/(TP+FP) = 2/(2+1) = 0.667
    assert precision(cases, results) == round(2 / 3, 3)


def test_recall_formula():
    cases, results = _make_cases_results()
    # TP/(TP+FN) = 2/(2+1) = 0.667
    assert recall(cases, results) == round(2 / 3, 3)


def test_f1_formula():
    cases, results = _make_cases_results()
    p = precision(cases, results)
    r = recall(cases, results)
    expected = round(2 * p * r / (p + r), 3)
    assert f1_score(cases, results) == expected


def test_evidence_coverage_average():
    cases, results = _make_cases_results()
    # 设置各案例证据覆盖
    results[0].evidence_coverage = 1.0
    results[1].evidence_coverage = 0.5
    results[2].evidence_coverage = 0.0
    results[3].evidence_coverage = 0.8
    results[4].evidence_coverage = 0.0
    # 平均 = (1.0 + 0.5 + 0.0 + 0.8 + 0.0) / 5 = 0.46
    assert evidence_coverage(cases, results) == round((1.0 + 0.5 + 0.0 + 0.8 + 0.0) / 5, 3)


def test_risk_detection_rate():
    cases, results = _make_cases_results()
    # 高风险案例（gold_risk_score >= 60）：CASE-1(85), CASE-2(70), CASE-3(60)
    # 检测到：CASE-1, CASE-2 → 2/3
    assert risk_detection_rate(cases, results) == round(2 / 3, 3)


def test_risk_detection_rate_threshold():
    cases, results = _make_cases_results()
    # 阈值=80：仅 CASE-1(85) 为高风险，检测到 → 1/1 = 1.0
    assert risk_detection_rate(cases, results, threshold=80.0) == 1.0


def test_recall_by_category():
    cases, results = _make_cases_results()
    by_cat = recall_by_category(cases, results)
    # FINANCIAL_ERROR: CASE-1(检测) / CASE-4(非错误，不计) → 1/1 = 1.0
    assert by_cat[ERROR_FINANCIAL_ERROR] == 1.0
    # SEMANTIC_OVERSTATEMENT: CASE-2(检测) → 1/1 = 1.0
    assert by_cat[ERROR_SEMANTIC_OVERSTATEMENT] == 1.0
    # GROWTH_ERROR: CASE-3(漏检) → 0/1 = 0.0
    assert by_cat[ERROR_GROWTH_ERROR] == 0.0


def test_compute_metrics_aggregates_all():
    cases, results = _make_cases_results()
    results[0].evidence_coverage = 1.0
    results[1].evidence_coverage = 0.5
    results[2].evidence_coverage = 0.0
    results[3].evidence_coverage = 0.8
    results[4].evidence_coverage = 0.0
    metrics = compute_metrics(cases, results)
    assert metrics.total_cases == 5
    assert metrics.accuracy == 0.6
    assert metrics.precision == round(2 / 3, 3)
    assert metrics.recall == round(2 / 3, 3)
    assert metrics.f1 == f1_score(cases, results)
    assert metrics.risk_detection_rate == round(2 / 3, 3)
    assert ERROR_GROWTH_ERROR in metrics.recall_by_category


def test_compare_models_highlights_gains():
    finproof_metrics = BenchmarkMetrics(
        total_cases=5, accuracy=0.8, precision=0.75, recall=0.9, f1=0.82,
        evidence_coverage=0.85, risk_detection_rate=0.9,
    )
    baseline_metrics = BenchmarkMetrics(
        total_cases=5, accuracy=0.4, precision=0.35, recall=0.5, f1=0.42,
        evidence_coverage=0.2, risk_detection_rate=0.4,
    )
    comp = compare_models(finproof_metrics, baseline_metrics)
    assert comp["accuracy_gain"] == round(0.8 - 0.4, 3)
    assert comp["f1_gain"] == round(0.82 - 0.42, 3)
    assert comp["recall_gain"] == round(0.9 - 0.5, 3)
    assert comp["finproof"]["accuracy"] == 0.8
    assert comp["baseline"]["accuracy"] == 0.4


def test_metrics_zero_when_no_cases():
    """无案例时指标应为 0（避免除零）。"""
    assert accuracy([], []) == 0.0
    assert precision([], []) == 0.0
    assert recall([], []) == 0.0
    assert f1_score([], []) == 0.0
    assert evidence_coverage([], []) == 0.0
    assert risk_detection_rate([], []) == 0.0


# ---------------------------------------------------------------------------
# §8.3 Evaluation 测试
# ---------------------------------------------------------------------------
def test_evaluate_model_finproof_runs_all_seed_cases():
    """FinProof 评测应覆盖全部预置案例。"""
    cases = get_seed_cases()
    result = evaluate_model(MODEL_FINPROOF, cases)
    assert result.model == MODEL_FINPROOF
    assert len(result.case_results) == len(cases)
    # 每条案例有预测结论
    for cr in result.case_results:
        assert cr.predicted_result
    # metrics 字段完整
    assert result.metrics.total_cases == len(cases)
    assert 0.0 <= result.metrics.accuracy <= 1.0


def test_evaluate_model_baseline_runs_all_seed_cases():
    cases = get_seed_cases()
    result = evaluate_model(MODEL_BASELINE_LLM, cases)
    assert result.model == MODEL_BASELINE_LLM
    assert len(result.case_results) == len(cases)


def test_finproof_detects_financial_error():
    """FinProof 应检测财务数据错误案例。"""
    case = BenchmarkCase(
        case_id="CASE-FIN-1",
        claim="美的集团2025年营业收入5000亿元",
        category=ERROR_FINANCIAL_ERROR,
        company="美的集团",
        stock_code="000333",
        report_period="2025FY",
        gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "公司2025年实现营业收入4564.52亿元。", "page": 1}],
        gold_result=GOLD_REFUTED,
        gold_risk_score=85.0,
        risk_type="FINANCIAL_ERROR",
        is_error_case=True,
    )
    result = evaluate_model(MODEL_FINPROOF, [case])
    cr = result.case_results[0]
    assert cr.detected_error is True
    assert cr.predicted_risk_type == "FINANCIAL_ERROR"


def test_finproof_detects_semantic_overstatement():
    """FinProof 应检测语义夸大案例。"""
    case = BenchmarkCase(
        case_id="CASE-SEM-1",
        claim="美的集团是唯一遥遥领先的家电龙头",
        category=ERROR_SEMANTIC_OVERSTATEMENT,
        gold_evidence=[{"source": "NEWS", "text": "市场份额显示海尔/格力同样具备竞争力。", "page": None}],
        gold_result=GOLD_REFUTED,
        gold_risk_score=65.0,
        risk_type="SEMANTIC_RISK",
        is_error_case=True,
    )
    result = evaluate_model(MODEL_FINPROOF, [case])
    assert result.case_results[0].detected_error is True
    assert result.case_results[0].predicted_risk_type == "SEMANTIC_RISK"


def test_finproof_detects_growth_error():
    """FinProof 应检测增长逻辑错误案例（增长词 + 无数字支持）。"""
    case = BenchmarkCase(
        case_id="CASE-GRW-1",
        claim="海外业务高速增长，增速超50%",
        category=ERROR_GROWTH_ERROR,
        gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "海外业务同比增长12%，低于公司整体增速。", "page": 6}],
        gold_result=GOLD_REFUTED,
        gold_risk_score=60.0,
        risk_type="EVIDENCE_RISK",
        is_error_case=True,
    )
    result = evaluate_model(MODEL_FINPROOF, [case])
    assert result.case_results[0].detected_error is True


def test_finproof_detects_competitive_no_evidence():
    """FinProof 应检测竞争优势主张缺证据案例。"""
    case = BenchmarkCase(
        case_id="CASE-CMP-1",
        claim="美的集团保持行业领先地位",
        category=ERROR_COMPETITIVE_CLAIM,
        gold_evidence=[{"source": "NEWS", "text": "未检索到市场份额/排名强证据。", "page": None}],
        gold_result=GOLD_INSUFFICIENT,
        gold_risk_score=55.0,
        risk_type="EVIDENCE_RISK",
        is_error_case=True,
    )
    result = evaluate_model(MODEL_FINPROOF, [case])
    assert result.case_results[0].detected_error is True
    assert result.case_results[0].predicted_risk_type == "EVIDENCE_RISK"


def test_finproof_detects_period_error():
    """FinProof 应检测期间错误案例（2024 vs 2025FY）。"""
    case = BenchmarkCase(
        case_id="CASE-PER-1",
        claim="美的集团2024年营业收入4564.52亿元",
        category=ERROR_PERIOD_ERROR,
        company="美的集团",
        stock_code="000333",
        report_period="2025FY",
        gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "公司2024年营业收入3591.61亿元。", "page": 1}],
        gold_result=GOLD_REFUTED,
        gold_risk_score=70.0,
        risk_type="PERIOD_ERROR",
        is_error_case=True,
    )
    result = evaluate_model(MODEL_FINPROOF, [case])
    assert result.case_results[0].detected_error is True
    assert result.case_results[0].predicted_risk_type == "PERIOD_ERROR"


def test_finproof_detects_causal_error():
    """FinProof 应检测因果归因错误案例。"""
    case = BenchmarkCase(
        case_id="CASE-CAU-1",
        claim="美的集团利润增长完全由海外业务驱动",
        category=ERROR_CAUSAL_ERROR,
        gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "利润增长由多业务分部共同贡献，非单一驱动。", "page": 6}],
        gold_result=GOLD_REFUTED,
        gold_risk_score=70.0,
        risk_type="SEMANTIC_RISK",
        is_error_case=True,
    )
    result = evaluate_model(MODEL_FINPROOF, [case])
    assert result.case_results[0].detected_error is True
    assert result.case_results[0].predicted_risk_type == "SEMANTIC_RISK"


def test_finproof_does_not_false_positive_on_correct_case():
    """正确对照案例不应被报错。"""
    case = BenchmarkCase(
        case_id="CASE-CORRECT-1",
        claim="美的集团2025年实现营业收入4564.52亿元，同比增长12.11%",
        category=ERROR_FINANCIAL_ERROR,
        company="美的集团",
        stock_code="000333",
        report_period="2025FY",
        gold_evidence=[{"source": "FINANCIAL_REPORT", "text": "公司2025年实现营业收入4564.52亿元，同比增长12.11%。", "page": 1}],
        gold_result=GOLD_SUPPORTED,
        gold_risk_score=0.0,
        risk_type="NONE",
        is_error_case=False,
    )
    result = evaluate_model(MODEL_FINPROOF, [case])
    assert result.case_results[0].detected_error is False
    assert result.case_results[0].predicted_risk_score == 0.0


def test_finproof_outperforms_baseline_on_seed():
    """FinProof 召回率应显著高于 Baseline（凸显发现 AI 幻觉能力）。"""
    cases = get_seed_cases()
    finproof = evaluate_model(MODEL_FINPROOF, cases)
    baseline = evaluate_model(MODEL_BASELINE_LLM, cases)
    assert finproof.metrics.recall > baseline.metrics.recall
    assert finproof.metrics.f1 >= baseline.metrics.f1


def test_evaluate_model_rejects_unknown_model():
    with pytest.raises(ValueError):
        evaluate_model("UNKNOWN_MODEL", [])


# ---------------------------------------------------------------------------
# §8.4 run_benchmark 全链路
# ---------------------------------------------------------------------------
def test_run_benchmark_with_seed_cases():
    """run_benchmark 用预置案例应生成完整报告。"""
    with SessionLocal() as s:
        report = run_benchmark(s, dataset_name=None, models=None, use_seed=True)
        assert report.total_cases >= 50
        assert MODEL_FINPROOF in report.models
        assert MODEL_BASELINE_LLM in report.models
        assert len(report.model_results) == 2
        # 错误分布非空
        assert report.error_distribution
        # 对比摘要含增益
        assert "f1_gain" in report.comparison
        assert "recall_gain" in report.comparison


def test_run_benchmark_raises_on_empty_dataset():
    with SessionLocal() as s:
        with pytest.raises(ValueError):
            run_benchmark(s, dataset_name="nonexistent_dataset_xyz", use_seed=False)


def test_save_and_get_report_persistence():
    with SessionLocal() as s:
        report = run_benchmark(s, dataset_name=None, use_seed=True)
        report = save_report(s, report)
        rid = report.id
        assert rid is not None

    with SessionLocal() as s:
        loaded = get_report(s, rid)
        assert loaded.total_cases == report.total_cases
        assert len(loaded.model_results) == 2
        # 模型对比可读回
        assert loaded.comparison
        assert "f1_gain" in loaded.comparison


def test_get_report_raises_on_missing():
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            get_report(s, 99999)


# ---------------------------------------------------------------------------
# §8.5 API 测试
# ---------------------------------------------------------------------------
def test_benchmark_api_dataset_overview():
    """API：GET /dataset 返回预置案例概况。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    r = client.get("/api/v1/benchmark/dataset")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 50
    assert "error_distribution" in data
    # 错误分布应覆盖全部 6 类
    for etype in ERROR_TYPES:
        assert etype in data["error_distribution"]


def test_benchmark_api_seed_and_count():
    """API：POST /seed 载入 Dataset + GET /dataset/count 统计。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    r = client.post("/api/v1/benchmark/seed", json={"dataset_name": "api_test_v1"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["count"] >= 50

    r2 = client.get("/api/v1/benchmark/dataset/count", params={"dataset_name": "api_test_v1"})
    assert r2.status_code == 200
    assert r2.json()["count"] >= 50


def test_benchmark_api_run_and_get():
    """API：POST /runs 运行评测 + GET /runs/{id} 查询报告。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    r = client.post("/api/v1/benchmark/runs", json={"use_seed": True})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["total_cases"] >= 50
    assert "model_results" in data
    assert "comparison" in data
    rid = data["id"]

    r2 = client.get(f"/api/v1/benchmark/runs/{rid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == rid


def test_benchmark_api_get_404_on_missing_run():
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    assert client.get("/api/v1/benchmark/runs/99999").status_code == 404
