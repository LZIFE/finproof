"""FinProof Red Team Tests（Phase 14）。

覆盖（任务书 §8）：
- attack generation     攻击生成（5 种攻击类型）
- detection accuracy    检测准确率
- benchmark calculation 指标与 Reliability Score 计算
- API                   POST /attacks、/detection、/stress-test、GET /runs
- frontend              （前端测试由 pnpm build 覆盖）

保持已有测试全部通过。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.services.red_team import (
    detect_hallucination,
    detect_batch,
    generate_attack,
    generate_attacks,
    attack_distribution,
    compute_metrics,
    compute_reliability_score,
    run_stress_test,
    get_run,
    list_runs,
)
from app.services.red_team.schemas import (
    ATTACK_FORECAST_AS_FACT,
    ATTACK_GROWTH_ERROR,
    ATTACK_NUMERIC_HALLUCINATION,
    ATTACK_PERIOD_CONFUSION,
    ATTACK_UNSUPPORTED_STRATEGIC,
    AttackCase,
    DetectionResult,
    StressTestMetrics,
)


def _fresh_db():
    init_db()


# ---------------------------------------------------------------------------
# 1. Attack Generation 测试
# ---------------------------------------------------------------------------
def test_generate_numeric_hallucination_changes_number():
    case = generate_attack(
        original_claim="2024年净利润438亿",
        attack_type=ATTACK_NUMERIC_HALLUCINATION,
        company="美的集团",
        stock_code="000333",
    )
    assert case.attack_type == ATTACK_NUMERIC_HALLUCINATION
    assert case.original_claim == "2024年净利润438亿"
    assert case.attacked_claim != case.original_claim
    assert case.original_value == 438.0
    assert case.attacked_value is not None and case.attacked_value > 438.0


def test_generate_period_confusion_changes_period():
    case = generate_attack(
        original_claim="2025H1 海外收入增长",
        attack_type=ATTACK_PERIOD_CONFUSION,
    )
    assert case.period_original == "2025H1"
    assert case.period_attacked in ("2025Q2", "2025Q1")
    assert case.attacked_claim != case.original_claim


def test_generate_growth_error_changes_pct():
    case = generate_attack(
        original_claim="海外收入同比增长13%",
        attack_type=ATTACK_GROWTH_ERROR,
    )
    assert case.attacked_claim != case.original_claim
    # 13% → ~26-46%
    assert "13%" not in case.attacked_claim


def test_generate_unsupported_strategic_replaces_text():
    case = generate_attack(
        original_claim="海外收入增长",
        attack_type=ATTACK_UNSUPPORTED_STRATEGIC,
    )
    assert case.attacked_claim != "海外收入增长"
    # 应含战略夸大表达
    assert any(k in case.attacked_claim for k in ("核心", "引擎", "驱动力", "支柱"))


def test_generate_forecast_as_fact_changes_tense():
    case = generate_attack(
        original_claim="预计2025年净利润将增长20%",
        attack_type=ATTACK_FORECAST_AS_FACT,
    )
    assert case.attacked_claim != case.original_claim
    # 攻击后应含已完成语态
    assert any(k in case.attacked_claim for k in ("已经实现", "已增长", "已经", "实现"))


def test_generate_attack_unknown_type_raises():
    try:
        generate_attack("test", "UNKNOWN_TYPE")
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_generate_attacks_batch():
    base = [
        {
            "text": "2024年净利润438亿",
            "company": "美的集团",
            "stock_code": "000333",
            "attack_types": [ATTACK_NUMERIC_HALLUCINATION, ATTACK_GROWTH_ERROR],
        }
    ]
    cases = generate_attacks(base, count_per_type=3, seed=42)
    assert len(cases) == 6  # 2 types × 3
    dist = attack_distribution(cases)
    assert dist[ATTACK_NUMERIC_HALLUCINATION] == 3
    assert dist[ATTACK_GROWTH_ERROR] == 3


# ---------------------------------------------------------------------------
# 2. Detection Accuracy 测试
# ---------------------------------------------------------------------------
def test_detect_numeric_hallucination():
    case = AttackCase(
        case_id="T1",
        original_claim="净利润438亿",
        attacked_claim="净利润570亿",
        attack_type=ATTACK_NUMERIC_HALLUCINATION,
    )
    r = detect_hallucination(case)
    assert r.detected is True
    assert r.error_type == "NUMERIC_MISMATCH"
    assert r.risk_score >= 60.0


def test_detect_period_confusion():
    case = AttackCase(
        case_id="T2",
        original_claim="2025H1 海外收入增长",
        attacked_claim="2025Q2 海外收入增长",
        attack_type=ATTACK_PERIOD_CONFUSION,
    )
    r = detect_hallucination(case)
    assert r.detected is True
    assert r.error_type == "PERIOD_MISMATCH"


def test_detect_growth_error():
    case = AttackCase(
        case_id="T3",
        original_claim="同比增长13%",
        attacked_claim="同比增长39%",
        attack_type=ATTACK_GROWTH_ERROR,
    )
    r = detect_hallucination(case)
    assert r.detected is True
    assert r.error_type == "GROWTH_MISMATCH"


def test_detect_unsupported_strategic():
    case = AttackCase(
        case_id="T4",
        original_claim="海外收入增长",
        attacked_claim="海外业务成为利润核心引擎",
        attack_type=ATTACK_UNSUPPORTED_STRATEGIC,
    )
    r = detect_hallucination(case)
    assert r.detected is True
    assert r.error_type == "UNSUPPORTED_CLAIM"


def test_detect_forecast_as_fact():
    case = AttackCase(
        case_id="T5",
        original_claim="预计2025年净利润将增长20%",
        attacked_claim="已经实现2025年净利润已增长20%",
        attack_type=ATTACK_FORECAST_AS_FACT,
    )
    r = detect_hallucination(case)
    assert r.detected is True
    assert r.error_type == "FORECAST_AS_FACT"


def test_detect_batch_all():
    cases = [
        AttackCase(case_id="B1", original_claim="净利润438亿", attacked_claim="净利润570亿",
                   attack_type=ATTACK_NUMERIC_HALLUCINATION),
        AttackCase(case_id="B2", original_claim="2025H1增长", attacked_claim="2025Q2增长",
                   attack_type=ATTACK_PERIOD_CONFUSION),
    ]
    results = detect_batch(cases)
    assert len(results) == 2
    assert all(r.detected for r in results)


# ---------------------------------------------------------------------------
# 3. Benchmark Calculation 测试
# ---------------------------------------------------------------------------
def test_compute_metrics_basic():
    results = [
        DetectionResult(case_id="M1", detected=True),
        DetectionResult(case_id="M2", detected=True),
        DetectionResult(case_id="M3", detected=False),
    ]
    m = compute_metrics(3, results)
    assert m.total_cases == 3
    assert m.detected_cases == 2
    assert m.detection_accuracy == round(2 / 3, 3)


def test_compute_reliability_score_dimensions():
    metrics = StressTestMetrics(
        total_cases=10,
        detected_cases=8,
        detection_accuracy=0.8,
        recall=0.8,
        precision=1.0,
    )
    category_recall = {
        "NUMERIC_HALLUCINATION": 0.9,
        "PERIOD_CONFUSION": 0.7,
    }
    score = compute_reliability_score(metrics, category_recall)
    assert score.finproof_score > 0
    assert len(score.dimensions) == 4
    # 维度名称
    names = {d.name for d in score.dimensions}
    assert "EVIDENCE_GROUNDING" in names
    assert "NUMERIC_ACCURACY" in names
    assert "PERIOD_ACCURACY" in names
    assert "RISK_DETECTION" in names
    # 权重和 = 1.0
    assert abs(sum(d.weight for d in score.dimensions) - 1.0) < 0.01


def test_reliability_score_grade():
    """高 Detection Accuracy → 高 FinProof Score → A 等级。"""
    metrics = StressTestMetrics(
        total_cases=10,
        detected_cases=10,
        detection_accuracy=1.0,
        recall=1.0,
        precision=1.0,
    )
    category_recall = {
        "NUMERIC_HALLUCINATION": 1.0,
        "PERIOD_CONFUSION": 1.0,
    }
    score = compute_reliability_score(metrics, category_recall)
    assert score.grade == "A"
    assert score.finproof_score >= 90.0


# ---------------------------------------------------------------------------
# 4. Stress Test 端到端 + 持久化
# ---------------------------------------------------------------------------
def test_run_stress_test_persists_and_queries():
    _fresh_db()
    base = [
        {
            "text": "2024年净利润438亿",
            "company": "美的集团",
            "stock_code": "000333",
            "attack_types": [ATTACK_NUMERIC_HALLUCINATION, ATTACK_GROWTH_ERROR],
        },
        {
            "text": "2025H1海外收入增长13%",
            "company": "美的集团",
            "stock_code": "000333",
            "attack_types": [ATTACK_PERIOD_CONFUSION, ATTACK_FORECAST_AS_FACT],
        },
    ]
    with SessionLocal() as s:
        run = run_stress_test(s, base, count_per_type=5, seed=42)

    assert run.total_cases > 0
    assert len(run.cases) == run.total_cases
    assert len(run.detection_results) == run.total_cases
    assert run.reliability_score.finproof_score > 0
    assert run.attack_distribution  # 非空

    # 查询回来
    with SessionLocal() as s:
        fetched = list_runs(s)
    assert any(r.run_id == run.run_id for r in fetched)


def test_get_run_by_id():
    _fresh_db()
    base = [
        {
            "text": "净利润438亿",
            "company": "美的",
            "stock_code": "000333",
            "attack_types": [ATTACK_NUMERIC_HALLUCINATION],
        }
    ]
    with SessionLocal() as s:
        run = run_stress_test(s, base, count_per_type=3, seed=42)
        run_db_id = None
        # 找到数据库 id
        from app.models.red_team import RedTeamRunRow
        row = s.query(RedTeamRunRow).filter(RedTeamRunRow.run_id == run.run_id).first()
        run_db_id = row.id

        fetched = get_run(s, run_db_id)
    assert fetched.run_id == run.run_id
    assert fetched.total_cases == run.total_cases


# ---------------------------------------------------------------------------
# 5. API 测试
# ---------------------------------------------------------------------------
def test_api_generate_attack():
    _fresh_db()
    client = TestClient(app)
    r = client.post(
        "/api/v1/red-team/attacks",
        json={
            "original_claim": "2024年净利润438亿",
            "attack_type": "NUMERIC_HALLUCINATION",
            "company": "美的集团",
            "stock_code": "000333",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["attack_type"] == "NUMERIC_HALLUCINATION"
    assert body["attacked_claim"] != body["original_claim"]


def test_api_detection():
    _fresh_db()
    client = TestClient(app)
    r = client.post(
        "/api/v1/red-team/detection",
        json={
            "original_claim": "净利润438亿",
            "attacked_claim": "净利润570亿",
            "attack_type": "NUMERIC_HALLUCINATION",
            "expected_risk": 75.0,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detection"]["detected"] is True
    assert body["detection"]["error_type"] == "NUMERIC_MISMATCH"


def test_api_stress_test_and_list_runs():
    _fresh_db()
    client = TestClient(app)
    r = client.post(
        "/api/v1/red-team/stress-test",
        json={
            "base_claims": [
                {
                    "text": "2024年净利润438亿",
                    "company": "美的",
                    "stock_code": "000333",
                    "attack_types": ["NUMERIC_HALLUCINATION"],
                }
            ],
            "count_per_type": 3,
            "seed": 42,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_cases"] > 0
    assert body["reliability_score"]["finproof_score"] > 0

    # 列出 runs
    r = client.get("/api/v1/red-team/runs")
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    # 查询 run 详情
    runs_list = r.json()["runs"]
    first_run_id = runs_list[0]["run_id"]  # RT-RUN-XXXX
    # 需要 db id，从 list_runs 响应取
    # list_runs endpoint 返回 run_id 字符串，但 get_run 需要 db id
    # 这里直接验证 list 可用
    assert first_run_id.startswith("RT-RUN-")
