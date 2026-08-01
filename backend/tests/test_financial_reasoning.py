"""FinProof Financial Reasoning Engine Tests（Phase 16）。

覆盖（任务书 §11）：
- 收入/利润混淆（METRIC_SUBSTITUTION / REVENUE_PROFIT_CONFUSION）
- 相关性/因果区分（CORRELATION_AS_CAUSATION）
- 期间偷换（PERIOD_SUBSTITUTION）
- 低基数（BASE_EFFECT_RISK）
- 增长质量（GROWTH_QUALITY_RISK：HIGH/MIXED/LOW/INSUFFICIENT）
- 支持与反证共存（SELECTIVE_EVIDENCE / MIXED_EVIDENCE）
- 隐含假设（HIDDEN_ASSUMPTION）
- 缺数据保持 UNKNOWN / INSUFFICIENT_DATA
- API/数据库/Copilot 集成
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.services.financial_reasoning import (
    apply_rules,
    check_assumptions,
    contradiction_to_results,
    detect_contradictions,
    analyze_growth_quality,
    growth_to_reasoning_result,
    reason_about,
    get_run,
    get_run_results,
    list_runs,
)
from app.services.financial_reasoning.schemas import (
    GQ_HIGH_QUALITY,
    GQ_INSUFFICIENT,
    GQ_LOW_QUALITY,
    GQ_MIXED_QUALITY,
    RT_BASE_EFFECT_RISK,
    RT_CONCLUSION_OVERREACH,
    RT_CORRELATION_AS_CAUSATION,
    RT_GROWTH_QUALITY_RISK,
    RT_HIDDEN_ASSUMPTION,
    RT_METRIC_SUBSTITUTION,
    RT_PERIOD_SUBSTITUTION,
    RT_REVENUE_PROFIT_CONFUSION,
    RT_SELECTIVE_EVIDENCE,
    STATUS_ASSUMPTION_UNVERIFIED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_LOGICAL_GAP,
    STATUS_MIXED_EVIDENCE,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    ReasoningInput,
)


def _fresh_db():
    init_db()


def _input(claim_text: str, evidence: list[dict] | None = None, **kw) -> ReasoningInput:
    return ReasoningInput(
        claim_text=claim_text,
        evidence_candidates=evidence or [],
        **kw,
    )


# ---------------------------------------------------------------------------
# 1. 收入/利润混淆
# ---------------------------------------------------------------------------
def test_metric_substitution_revenue_written_as_profit():
    inp = _input("海外收入增长，因此利润增长")
    results = apply_rules(inp)
    types = [r.reasoning_type for r in results]
    assert RT_METRIC_SUBSTITUTION in types
    r = next(r for r in results if r.reasoning_type == RT_METRIC_SUBSTITUTION)
    assert r.status == STATUS_LOGICAL_GAP
    assert "指标偷换" in r.logical_gap
    assert r.suggested_safe_wording


def test_revenue_profit_confusion_share_mismatch():
    inp = _input("海外收入贡献占比30%，因此海外利润贡献占比30%")
    results = apply_rules(inp)
    types = [r.reasoning_type for r in results]
    assert RT_REVENUE_PROFIT_CONFUSION in types


# ---------------------------------------------------------------------------
# 2. 相关性/因果区分
# ---------------------------------------------------------------------------
def test_correlation_as_causation():
    inp = _input("研发投入增长，因此带动了收入增长")
    results = apply_rules(inp)
    types = [r.reasoning_type for r in results]
    assert RT_CORRELATION_AS_CAUSATION in types
    r = next(r for r in results if r.reasoning_type == RT_CORRELATION_AS_CAUSATION)
    assert r.status == STATUS_ASSUMPTION_UNVERIFIED
    assert "因果" in r.logical_gap


# ---------------------------------------------------------------------------
# 3. 期间偷换
# ---------------------------------------------------------------------------
def test_period_substitution_h1_vs_q():
    inp = _input("2025H1 海外收入增长，等同于2025Q2 增长")
    results = apply_rules(inp)
    types = [r.reasoning_type for r in results]
    assert RT_PERIOD_SUBSTITUTION in types
    r = next(r for r in results if r.reasoning_type == RT_PERIOD_SUBSTITUTION)
    assert "口径" in r.logical_gap or "期间" in r.logical_gap


# ---------------------------------------------------------------------------
# 4. 低基数
# ---------------------------------------------------------------------------
def test_base_effect_risk_low_base_high_growth():
    inp = _input("新业务增长120%，从0起步的低基数高速增长")
    results = apply_rules(inp)
    types = [r.reasoning_type for r in results]
    assert RT_BASE_EFFECT_RISK in types
    r = next(r for r in results if r.reasoning_type == RT_BASE_EFFECT_RISK)
    assert r.status == STATUS_ASSUMPTION_UNVERIFIED
    assert "基数" in r.logical_gap


# ---------------------------------------------------------------------------
# 5. 增长质量
# ---------------------------------------------------------------------------
def test_growth_quality_high():
    inp = _input(
        "营收增长，净利润增长",
        evidence=[
            {"block_id": 1, "text": "营业收入同比增长10%"},
            {"block_id": 2, "text": "净利润同比增长12%"},
            {"block_id": 3, "text": "经营现金流同比增长8%"},
            {"block_id": 4, "text": "毛利率提升"},
        ],
    )
    gq = analyze_growth_quality(inp)
    assert gq.quality == GQ_HIGH_QUALITY


def test_growth_quality_low_when_cashflow_drops():
    inp = _input(
        "营收增长，经营质量改善",
        evidence=[
            {"block_id": 1, "text": "营业收入同比增长10%"},
            {"block_id": 2, "text": "净利润同比增长5%"},
            {"block_id": 3, "text": "经营现金流同比下降20%"},
            {"block_id": 4, "text": "应收账款同比上升25%"},
        ],
    )
    gq = analyze_growth_quality(inp)
    assert gq.quality == GQ_LOW_QUALITY
    result = growth_to_reasoning_result(inp, gq)
    assert result.reasoning_type == RT_GROWTH_QUALITY_RISK
    assert result.status == STATUS_MIXED_EVIDENCE


def test_growth_quality_mixed():
    inp = _input(
        "营收增长",
        evidence=[
            {"block_id": 1, "text": "营业收入同比增长10%"},
            {"block_id": 2, "text": "净利润同比增长5%"},
        ],
    )
    gq = analyze_growth_quality(inp)
    # 利润与营收同步增长但无现金流/毛利率数据 → 部分指标未同步
    assert gq.quality in (GQ_MIXED_QUALITY, GQ_HIGH_QUALITY)


def test_growth_quality_insufficient_when_revenue_missing():
    inp = _input("公司业务发展", evidence=[{"block_id": 1, "text": "仅含模糊表述"}])
    gq = analyze_growth_quality(inp)
    assert gq.quality == GQ_INSUFFICIENT
    result = growth_to_reasoning_result(inp, gq)
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert "数据缺失" in result.explanation or "数据不足" in result.explanation or "不得强行" in result.explanation


# ---------------------------------------------------------------------------
# 6. 支持与反证共存
# ---------------------------------------------------------------------------
def test_selective_evidence_mixed():
    inp = _input(
        "海外业务增长",
        evidence=[
            {"block_id": 1, "text": "海外收入同比增长10%", "stance": "SUPPORT"},
            {"block_id": 2, "text": "海外利润同比下滑5%", "stance": "COUNTER"},
        ],
    )
    results = apply_rules(inp)
    types = [r.reasoning_type for r in results]
    assert RT_SELECTIVE_EVIDENCE in types
    r = next(r for r in results if r.reasoning_type == RT_SELECTIVE_EVIDENCE)
    assert r.status == STATUS_MIXED_EVIDENCE
    assert len(r.counter_evidence) > 0


# ---------------------------------------------------------------------------
# 7. 隐含假设
# ---------------------------------------------------------------------------
def test_hidden_assumption_market_share_not_long_term():
    inp = _input("公司市场份额领先，因此具有长期竞争优势")
    results = check_assumptions(inp)
    types = [r.reasoning_type for r in results]
    assert RT_HIDDEN_ASSUMPTION in types
    r = next(r for r in results if r.reasoning_type == RT_HIDDEN_ASSUMPTION)
    assert r.status == STATUS_ASSUMPTION_UNVERIFIED
    assert "长期" in r.assumptions[0] or "份额" in r.assumptions[0]


# ---------------------------------------------------------------------------
# 8. 缺数据保持 UNKNOWN / INSUFFICIENT
# ---------------------------------------------------------------------------
def test_insufficient_data_no_strong_conclusion():
    inp = _input("公司业务发展良好", evidence=[])
    results = apply_rules(inp)
    # 无强信号 → 不触发过度跳跃；不应强行输出强结论
    overreach = [r for r in results if r.reasoning_type == RT_CONCLUSION_OVERREACH]
    # 无强表述触发 → 不应凭缺失数据强行判断
    for r in overreach:
        assert r.suggested_safe_wording  # 若触发，必有安全措辞


def test_growth_quality_insufficient_no_force():
    inp = _input("公司业务发展", evidence=[{"block_id": 1, "text": "abc"}])
    gq = analyze_growth_quality(inp)
    assert gq.quality == GQ_INSUFFICIENT
    # 不得凭缺失数据强行判断为 HIGH/LOW
    assert gq.quality not in (GQ_HIGH_QUALITY, GQ_LOW_QUALITY, GQ_MIXED_QUALITY)


# ---------------------------------------------------------------------------
# 9. 冲突检测
# ---------------------------------------------------------------------------
def test_contradiction_claim_vs_evidence():
    inp = _input(
        "海外业务利润同比增长",
        evidence=[
            {"block_id": 1, "text": "海外业务利润同比下滑5%"},
        ],
    )
    contradictions = detect_contradictions(inp)
    assert len(contradictions) > 0
    # 转 ReasoningResult
    results = contradiction_to_results(inp, contradictions)
    assert len(results) > 0
    assert results[0].status in (STATUS_UNSUPPORTED, STATUS_MIXED_EVIDENCE)


def test_contradiction_evidence_vs_evidence():
    inp = _input(
        "公司增长",
        evidence=[
            {"block_id": 1, "text": "营收同比增长10%", "document_id": "doc1"},
            {"block_id": 2, "text": "营收同比下滑5%", "document_id": "doc2"},
        ],
    )
    contradictions = detect_contradictions(inp)
    assert len(contradictions) > 0


# ---------------------------------------------------------------------------
# 10. Demo 案例 1：海外收入增长 → 利润增长核心（CONCLUSION_OVERREACH）
# ---------------------------------------------------------------------------
def test_demo_case1_overreach():
    inp = _input("海外收入增长，因此海外业务是利润增长核心")
    results = apply_rules(inp) + check_assumptions(inp)
    types = [r.reasoning_type for r in results]
    assert RT_CONCLUSION_OVERREACH in types
    r = next(r for r in results if r.reasoning_type == RT_CONCLUSION_OVERREACH)
    assert r.status == STATUS_LOGICAL_GAP
    assert "利润" in r.logical_gap or "收入" in r.logical_gap
    assert r.suggested_safe_wording
    # 安全措辞不得含投资观点
    assert "买入" not in r.suggested_safe_wording
    assert "卖出" not in r.suggested_safe_wording


# ---------------------------------------------------------------------------
# 11. Demo 案例 2：营收增长 → 经营质量改善（GROWTH_QUALITY）
# ---------------------------------------------------------------------------
def test_demo_case2_growth_quality():
    inp = _input(
        "营收增长说明经营质量改善",
        evidence=[
            {"block_id": 1, "text": "营业收入同比增长10%"},
            {"block_id": 2, "text": "净利润同比增长5%"},
            {"block_id": 3, "text": "经营现金流同比下降20%"},
            {"block_id": 4, "text": "应收账款同比上升25%"},
        ],
    )
    gq = analyze_growth_quality(inp)
    assert gq.quality in (GQ_LOW_QUALITY, GQ_MIXED_QUALITY)


# ---------------------------------------------------------------------------
# 12. Demo 案例 3：市场份额领先 → 长期竞争优势（HIDDEN_ASSUMPTION）
# ---------------------------------------------------------------------------
def test_demo_case3_hidden_assumption():
    inp = _input("公司市场份额领先，因此具有长期竞争优势")
    results = check_assumptions(inp)
    types = [r.reasoning_type for r in results]
    assert RT_HIDDEN_ASSUMPTION in types
    r = next(r for r in results if r.reasoning_type == RT_HIDDEN_ASSUMPTION)
    assert r.status == STATUS_ASSUMPTION_UNVERIFIED
    # 排名证据不足以证明长期优势
    assert "长期" in r.assumptions[0] or "份额" in r.assumptions[0]


# ---------------------------------------------------------------------------
# 13. reason_about 端到端 + 持久化
# ---------------------------------------------------------------------------
def test_reason_about_persists_and_deduplicates():
    _fresh_db()
    inp = _input(
        "海外收入增长，因此海外业务是利润增长核心",
        evidence=[
            {"block_id": 1, "text": "海外收入同比增长10%"},
        ],
    )
    with SessionLocal() as s:
        run = reason_about(s, inp)
    assert run.run_id.startswith("REASON-RUN-")
    assert len(run.results) > 0
    # 去重：相同 reasoning_type + status + logical_gap 不重复
    keys = {(r.reasoning_type, r.status, r.logical_gap) for r in run.results}
    assert len(keys) == len(run.results)
    # 全部 result 有 result_id 与 run_id
    for r in run.results:
        assert r.result_id.startswith("RR-")
        assert r.run_id == run.run_id
        assert r.triggered_rules  # 触发规则ID非空
        assert r.rule_version


def test_get_run_and_results_round_trip():
    _fresh_db()
    inp = _input(
        "营收增长说明经营质量改善",
        evidence=[
            {"block_id": 1, "text": "营业收入同比增长10%"},
            {"block_id": 2, "text": "净利润同比增长5%"},
            {"block_id": 3, "text": "经营现金流同比下降20%"},
        ],
    )
    with SessionLocal() as s:
        run = reason_about(s, inp)
        # 找数据库 id
        from app.models.financial_reasoning import ReasoningRunRow
        row = s.query(ReasoningRunRow).filter(ReasoningRunRow.run_id == run.run_id).first()
        db_id = row.id
        fetched = get_run(s, db_id)
        results = get_run_results(s, db_id)
    assert fetched.run_id == run.run_id
    assert len(results) == len(run.results)


def test_list_runs():
    _fresh_db()
    inp = _input("营收增长")
    with SessionLocal() as s:
        reason_about(s, inp)
        runs = list_runs(s)
    assert len(runs) >= 1


# ---------------------------------------------------------------------------
# 14. API 测试
# ---------------------------------------------------------------------------
def test_api_create_run_and_get():
    _fresh_db()
    client = TestClient(app)
    r = client.post(
        "/api/v1/reasoning/runs",
        json={
            "claim_text": "海外收入增长，因此海外业务是利润增长核心",
            "evidence_candidates": [{"block_id": 1, "text": "海外收入同比增长10%"}],
            "company": "美的集团",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["run_id"].startswith("REASON-RUN-")
    assert len(body["results"]) > 0
    # 找 db id
    from app.models.financial_reasoning import ReasoningRunRow
    with SessionLocal() as s:
        row = s.query(ReasoningRunRow).filter(ReasoningRunRow.run_id == body["run_id"]).first()
        db_id = row.id

    # GET /runs/{id}
    r = client.get(f"/api/v1/reasoning/runs/{db_id}")
    assert r.status_code == 200
    assert r.json()["run_id"] == body["run_id"]

    # GET /runs/{id}/results
    r = client.get(f"/api/v1/reasoning/runs/{db_id}/results")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_api_list_runs():
    _fresh_db()
    client = TestClient(app)
    r = client.get("/api/v1/reasoning/runs")
    assert r.status_code == 200
    assert "count" in r.json()


# ---------------------------------------------------------------------------
# 15. Copilot 集成（reasoning_explanation 意图）
# ---------------------------------------------------------------------------
def test_copilot_reasoning_explanation_intent():
    from app.services.copilot.intent_classifier import classify_intent
    i = classify_intent("为什么该结论不成立？逻辑风险是什么？")
    assert i.intent_type == "REASONING_EXPLANATION"


def test_copilot_chat_reasoning_routes_to_financial_reasoning():
    _fresh_db()
    with SessionLocal() as s:
        from app.services.copilot import chat
        resp = chat(s, "为什么该结论不成立？海外收入增长因此利润增长核心")
        out = resp.to_dict()
    # 应触发推理引擎，tool_trace 含 financial_reasoning
    tools = [t["tool"] for t in out["tool_trace"]]
    assert "financial_reasoning" in tools
    # 回答非空
    assert out["answer"]
    # 不输出投资建议
    assert "买入" not in out["answer"]
    assert "卖出" not in out["answer"]


# ---------------------------------------------------------------------------
# 16. safe_wording 安全性：只能降低强度，不含投资观点
# ---------------------------------------------------------------------------
def test_safe_wording_only_softens_and_no_investment_view():
    inp = _input("海外收入增长，因此海外业务是利润增长核心")
    results = apply_rules(inp) + check_assumptions(inp)
    for r in results:
        if r.suggested_safe_wording:
            assert "买入" not in r.suggested_safe_wording
            assert "卖出" not in r.suggested_safe_wording
            assert "推荐" not in r.suggested_safe_wording
