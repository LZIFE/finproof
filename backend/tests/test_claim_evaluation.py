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
    assert score >= 0.80
    assert "text_overlap" in reasons and "metric" in reasons and "value" in reasons


def test_quote_normalization_for_overlap():
    """引号（全角/弯引号）差异不影响文本重叠判定。"""
    g = _gold("G1", "公司持续深化\u201c国内高端品牌和海外OBM优先\u201d战略")
    s = _sys(1, '公司持续深化"国内高端品牌和海外OBM优先"战略', code=None, value=None,
             period=None, claim_type="BUSINESS_FACT", metric=None)
    score, reasons = claim_eval.match_score(g, s)
    assert "text_overlap" in reasons
    assert score >= claim_eval.W_TEXT  # 文本重叠本身足够贡献基础分


def test_period_conflict_penalty():
    """同值同文本但期间明显冲突（2025Q1 vs 2025FY）→ 高额惩罚，不得抢占。"""
    gold_fy = _gold("G_FY", "归母净利润同比增长38.02%", metric="yoy_growth_net_profit",
                    value=38.02, period="2025FY", claim_type="calculated_financial_metric")
    gold_q1 = _gold("G_Q1", "归母净利润同比增长38.02%", metric="yoy_growth_net_profit",
                    value=38.02, period="2025Q1", claim_type="calculated_financial_metric")
    sys_q1 = _sys(1, "归母净利润同比增长38.02%", code="yoy_growth_net_profit",
                  value=38.02, period="2025Q1", claim_type="GROWTH_RATE")
    # 对自身期间（2025Q1）得分显著高于对冲突期间（2025FY）
    score_own, _ = claim_eval.match_score(gold_q1, sys_q1)
    score_conflict, _ = claim_eval.match_score(gold_fy, sys_q1)
    assert "period" in claim_eval.match_score(gold_q1, sys_q1)[1]
    assert "period_conflict" in claim_eval.match_score(gold_fy, sys_q1)[1]
    assert score_own - score_conflict >= claim_eval.PENALTY_CONFLICT


def test_metric_conflict_penalty():
    """同值同文本但指标明显冲突（收入 vs 净利润）→ 惩罚。"""
    gold_rev = _gold("G_REV", "2025年收入为100亿元", metric="revenue",
                     value=100.0, period="2025FY")
    sys_profit = _sys(1, "2025年收入为100亿元", code="net_profit",
                      value=100.0, period="2025FY", metric="净利润")
    # 系统中文指标"净利润"不在金标准原文"2025年收入为100亿元"中 → 冲突惩罚
    score, reasons = claim_eval.match_score(gold_rev, sys_profit)
    assert "metric_conflict" in reasons
    # 正确指标版本不受惩罚
    sys_correct = _sys(2, "2025年收入为100亿元", code="revenue",
                       value=100.0, period="2025FY", metric="收入")
    score_ok, reasons_ok = claim_eval.match_score(gold_rev, sys_correct)
    assert "metric_conflict" not in reasons_ok
    assert score_ok > score


def test_semantic_claim_clears_threshold():
    """无数字语义主张（文本+类型+性质+主体）应达到匹配阈值。"""
    g = _gold("G1", "公司持续深化OBM优先战略", metric="overseas_obm_strategy",
              value=None, period="2025H1", claim_type="business_fact")
    s = _sys(1, "公司持续深化OBM优先战略", code=None, value=None, period="2025",
             claim_type="BUSINESS_FACT", metric=None)
    s["claim_nature"] = "FACT"
    s["entity_name"] = "美的集团"
    g["entity"] = "美的集团"
    score, reasons = claim_eval.match_score(g, s)
    assert score >= claim_eval.MATCH_THRESHOLD
    assert "text_overlap" in reasons and "nature" in reasons


def test_no_steal_between_same_value_different_period():
    """规格示例：2025Q1收入38.02% 与 2025全年归母净利38.02% 不得互相抢占。"""
    gold_q1_rev = _gold("G1", "2025Q1收入同比增长38.02%", metric="revenue",
                        value=38.02, period="2025Q1", claim_type="raw_number")
    gold_fy_profit = _gold("G2", "2025全年归母净利润同比增长38.02%",
                           metric="yoy_growth_net_profit", value=38.02,
                           period="2025FY", claim_type="calculated_financial_metric")
    sys_q1 = _sys(1, "2025Q1收入同比增长38.02%", code="revenue", value=38.02,
                  period="2025Q1", claim_type="GROWTH_RATE")
    sys_fy = _sys(2, "2025全年归母净利润同比增长38.02%", code="yoy_growth_net_profit",
                  value=38.02, period="2025FY", claim_type="GROWTH_RATE")
    result = claim_eval.match_claims([sys_q1, sys_fy], [gold_q1_rev, gold_fy_profit])
    assert result.matched_gold_ids == {"G1", "G2"}
    matched_golds = {r.gold_claim_id for r in result.records if r.match_status == "MATCHED"}
    assert matched_golds == {"G1", "G2"}


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
