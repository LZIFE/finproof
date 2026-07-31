"""主张提取评测模块单元测试：匹配状态 / 指标计算 / 歧义 / 产物生成。"""

import json
from pathlib import Path

from app.services.evaluation import claim_eval


def _gold(claim_id, text, metric="revenue", value=100.0, period="2025FY",
          claim_type="raw_number", risk_level="high"):
    return {
        "claim_id": claim_id, "original_text": text, "metric": metric,
        "value": value, "unit": "亿元", "period": period,
        "claim_type": claim_type, "risk_level": risk_level,
    }


def _sys(sid, text, code="revenue", value=100.0, period="2025FY",
         claim_type="ABSOLUTE_FINANCIAL_VALUE", metric="营业收入"):
    return {
        "id": sid, "source_text": text, "metric_code": code, "metric": metric,
        "reported_value": value, "period": period, "claim_type": claim_type,
    }


# ---------- 匹配信号 ----------

def test_match_score_signals():
    g = _gold("G1", "公司2025年营业收入4564.52亿元")
    s = _sys(1, "公司2025年营业收入4564.52亿元")
    score, reasons = claim_eval.match_score(g, s)
    assert score >= 0.9
    assert "text_overlap" in reasons and "metric" in reasons and "value" in reasons


def test_match_score_weak_without_signals():
    g = _gold("G1", "公司2025年营业收入4564.52亿元")
    s = _sys(1, "完全无关的句子", code=None, value=None, period=None)
    score, _ = claim_eval.match_score(g, s)
    assert score < 0.5


def test_period_compatible_fy_year():
    assert claim_eval.period_compatible("2025FY", "2025")
    assert claim_eval.period_compatible("2025H1", "2025H1")
    assert not claim_eval.period_compatible("2025Q1", "2025H1")


# ---------- 匹配分配 ----------

def test_match_best_per_gold():
    golds = [_gold("G1", "公司2025年营业收入4564.52亿元", value=4564.52)]
    systems = [
        _sys(1, "公司2025年营业收入4564.52亿元", value=4564.52),
        _sys(2, "公司2025年营业收入4564.52亿元", value=9999.0),  # 数值错误 → 低分
    ]
    result = claim_eval.match_claims(systems, golds)
    matched = [r for r in result.records if r.match_status == "MATCHED"]
    unmatched = [r for r in result.records if r.match_status == "UNMATCHED_SYSTEM"]
    assert len(matched) == 1  # 每个金标准只保留最佳系统主张
    assert len(unmatched) == 1


def test_missed_and_unmatched():
    golds = [_gold("G1", "公司2025年营业收入4564.52亿元", value=4564.52)]
    systems = [
        _sys(1, "完全无关内容", code=None, value=None, period=None,
             claim_type="OTHER_VERIFIABLE", metric=None)
    ]
    result = claim_eval.match_claims(systems, golds)
    assert result.missed_gold and result.missed_gold[0]["claim_id"] == "G1"
    assert len(result.unmatched_system) == 1


def test_ambiguous_detection():
    # 系统句与两条金标准文本高度重叠（G1 ⊂ sys，G2 == sys），得分并列 → 歧义，不强行选择
    golds = [
        _gold("G1", "公司2025年收入100亿元", value=100.0),
        _gold("G2", "公司2025年收入100亿元左右", value=100.0),
    ]
    systems = [_sys(1, "公司2025年收入100亿元左右", value=100.0)]
    result = claim_eval.match_claims(systems, golds)
    assert any(r.match_status == "AMBIGUOUS" for r in result.records)
    assert len(result.matched_gold_ids) == 0


# ---------- 指标计算 ----------

def test_compute_metrics():
    golds = [
        _gold("G1", "公司2025年营业收入4564.52亿元", value=4564.52, risk_level="high"),
        _gold("G2", "海外业务已成为利润增长核心引擎", metric="overseas_business",
              value=None, claim_type="causality", risk_level="high"),
    ]
    systems = [
        _sys(1, "公司2025年营业收入4564.52亿元", value=4564.52),
        _sys(2, "海外业务已成为利润增长核心引擎", code="overseas_business",
             value=None, claim_type="CAUSAL_CLAIM"),
    ]
    result = claim_eval.match_claims(systems, golds)
    run = {
        "id": 1, "mode": "mock", "provider": "mock", "model_name": None,
        "prompt_version": "v1", "candidate_claim_count": 2,
        "schema_valid_count": 2, "duplicate_removed_count": 0,
    }
    m = claim_eval.compute_metrics(run, result, golds, systems)
    assert m["recall"] == 1.0
    assert m["precision"] == 1.0
    assert m["f1"] == 1.0
    assert m["high_risk_recall"] == 1.0  # 大小写不敏感
    assert m["numeric_claim_recall"] == 1.0
    assert m["semantic_claim_recall"] == 1.0
    assert m["schema_validity_rate"] == 1.0
    assert m["duplicate_rate"] == 0.0
    assert m["metric_accuracy"] == 1.0
    assert m["period_accuracy"] == 1.0


def test_compute_metrics_schema_and_duplicate_rates():
    golds = [_gold("G1", "公司2025年营业收入4564.52亿元", value=4564.52)]
    systems = [_sys(1, "公司2025年营业收入4564.52亿元", value=4564.52)]
    result = claim_eval.match_claims(systems, golds)
    run = {
        "id": 1, "mode": "mock", "provider": "mock", "model_name": None,
        "prompt_version": "v1", "candidate_claim_count": 10,
        "schema_valid_count": 8, "duplicate_removed_count": 2,
    }
    m = claim_eval.compute_metrics(run, result, golds, systems)
    assert m["schema_validity_rate"] == 0.8
    assert m["duplicate_rate"] == 0.2


def test_matched_artifacts_consistent():
    """指标 matched_count 与 matched_claims 产物数量一致。"""
    golds = [_gold("G1", "公司2025年营业收入4564.52亿元", value=4564.52)]
    systems = [_sys(1, "公司2025年营业收入4564.52亿元", value=4564.52)]
    result = claim_eval.match_claims(systems, golds)
    matched_records = [r for r in result.records if r.match_status == "MATCHED"]
    assert len(result.matched_gold_ids) == len(matched_records) == 1


def test_write_artifacts(tmp_path):
    golds = [_gold("G1", "公司2025年营业收入4564.52亿元")]
    systems = [_sys(1, "公司2025年营业收入4564.52亿元")]
    result = claim_eval.match_claims(systems, golds)
    run = {
        "id": 1, "mode": "mock", "provider": "mock", "model_name": None,
        "prompt_version": "v1", "candidate_claim_count": 1,
        "schema_valid_count": 1, "duplicate_removed_count": 0,
    }
    metrics = claim_eval.compute_metrics(run, result, golds, systems)
    report = claim_eval.build_report(metrics, result, golds)
    out = tmp_path / "eval"
    claim_eval.write_artifacts(out, metrics, result, report)
    for name in ["metrics.json", "matched_claims.json", "missed_gold_claims.json",
                 "unmatched_system_claims.json", "ambiguous_matches.json", "report.md"]:
        assert (out / name).exists()
    data = json.loads((out / "metrics.json").read_text())
    assert data["precision"] == 1.0
    assert "Precision" in (out / "report.md").read_text()
