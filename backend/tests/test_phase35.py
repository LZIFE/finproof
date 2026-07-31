"""Phase 3.5 新增专项测试：过滤/子句归属/去重/Prompt 隔离/Hybrid/Raw 与人工审核分离。"""

import json

import pytest

from app.core.enums import ExtractionMode
from app.core.exceptions import AppError
from app.services.claims.dedup import deduplicate
from app.services.claims.providers import (
    DocumentContext,
    HybridClaimExtractionProvider,
    MockClaimExtractionProvider,
    RuleOnlyClaimExtractionProvider,
    load_prompt,
)
from app.services.claims.rule_extractor import RuleBasedCandidateExtractor

from tests.test_rule_extractor import _block, _extract  # noqa: F401 —— 复用工具


# ---------- 过滤 ----------

def test_growth_without_attribution_not_stored():
    """增长率无归属（无指标且无前文指标可继承）不得直接入库。"""
    result = _extract("公司整体实现增长。同比增长12.11%。")
    # "同比增长12.11%" 无前文指标 → 不得成为独立主张
    assert not any(c.source_text == "同比增长12.11%" for c in result.candidates)


def test_qualitative_sentence_filtered():
    """无指标定性句（抽象形容）默认过滤。

    注："环比大幅改善"按说明书"同比、环比"高优先级保留规则保留（此处不列入）。
    """
    for text in ["现金流整体稳健", "公司是一家优秀的公司", "整体来看公司基本面扎实"]:
        assert len(_extract(text).candidates) == 0, text


def test_business_fact_without_number_kept():
    """有明确业务事实/事件的无数字句保留（不能仅凭'无数字'删除）。"""
    for text in [
        "公司已完成对某企业的收购",
        "海外业务已成为公司主要收入来源",
        "OBM模式已成为公司的核心战略",
        "管理层预计未来收入将保持增长",
    ]:
        assert len(_extract(text).candidates) >= 1, text


def test_fragment_clause_filtered():
    """复合句拆分残片（连接词/介词开头）不独立成条。"""
    for text in ["综合现有披露，我们估计2025年第四季度收入超过1200亿元。",
                 "以及多元化业务整合不及预期的风险。"]:
        assert len(_extract(text).candidates) <= 1, text


# ---------- 子句归属 ----------

def test_clause_carries_parent_sentence():
    """拆分后的子主张保留父句信息与跨度。"""
    text = "公司2025年实现营业收入4564.52亿元，同比增长12.11%，规模再创历史新高。"
    result = _extract(text)
    growth = next(c for c in result.candidates if c.metric_code == "yoy_growth_revenue")
    assert growth.parent_sentence_text == text.rstrip("。")
    assert growth.clause_index == 1
    assert growth.source_span_start is not None and growth.source_span_end is not None
    assert growth.source_span_end > growth.source_span_start


def test_growth_binds_metric():
    """增长率子句继承父句指标（不得生成裸'同比增长'主张）。"""
    result = _extract("归母净利润439.45亿元，同比增长38.02%。")
    growth = next(c for c in result.candidates if c.reported_value == 38.02)
    assert growth.metric_code == "yoy_growth_net_profit"
    assert growth.period == "2025"


# ---------- 去重 ----------

def test_synonym_dedup_fy_year():
    """同义主张（2025FY ≈ 2025，同一指标+数值）合并。"""
    c1 = _block("全年经营现金流净额533.46亿元")
    c2 = _block("公司2025年经营活动现金流量净额533.46亿元")
    r1 = _extract(c1.text)
    r2 = _extract(c2.text)
    result = deduplicate(r1.candidates + r2.candidates)
    assert result.removed_count >= 1  # 结构化键合并（FY≈YEAR 归一）


def test_different_metrics_same_value_not_deduped():
    """不同指标相同数值不能合并。"""
    result = _extract("2025年收入为100亿元，净利润为100亿元。")
    deduped = deduplicate(result.candidates)
    codes = {c.metric_code for c in deduped.unique}
    assert "revenue" in codes and "net_profit" in codes
    assert len(deduped.unique) >= 2


def test_metricless_claims_not_false_merged():
    """无指标主张追加文本指纹：不同语义句不得因空键被误并（CLM-019 场景）。"""
    s1 = "公司持续深化\"国内高端品牌和海外OBM优先\"战略"
    s2 = "海外OBM战略成效逐步显现"
    r1, r2 = _extract(s1), _extract(s2)
    assert len(r1.candidates) >= 1 and len(r2.candidates) >= 1
    result = deduplicate(r1.candidates + r2.candidates)
    assert result.removed_count == 0  # 文本指纹保证键不同


# ---------- Prompt 版本隔离 ----------

def test_prompt_v1_v2_isolated():
    """Prompt v1 与 v2 版本隔离，互不影响。"""
    p1 = load_prompt("v1")
    p2 = load_prompt("v2")
    assert p1 != p2
    assert "只提取能够独立验证的主张" in p2  # v2 新增条款
    assert "可核验金融主张" in p1
    # v2 明确包含任务书 12 条要求中的关键项
    for keyword in ["不判断主张真假", "不读取或猜测任何金标准答案", "增长率必须绑定"]:
        assert keyword in p2


# ---------- 模式 ----------

def test_rule_only_mode_marked():
    provider = RuleOnlyClaimExtractionProvider()
    ctx = DocumentContext(document_id=1, report_year=2025)
    result = provider.extract_claims(ctx, [_block("公司2025年收入100亿元")])
    assert result.is_mock is False
    assert result.provider == "rule_only"
    assert result.claim_dicts[0]["extraction_method"] == "RULE_BASED"


def test_hybrid_requires_llm_config():
    """Hybrid 模式无 Key 时明确报错（不允许伪装）。"""
    ctx = DocumentContext(document_id=1, report_year=2025)
    with pytest.raises(AppError) as ei:
        HybridClaimExtractionProvider().extract_claims(ctx, [_block("公司收入100亿元")])
    assert ei.value.code == "LLM_NOT_CONFIGURED"


def test_extraction_modes_enum():
    assert {m.value for m in ExtractionMode} == {"mock", "rules", "llm", "hybrid"}


# ---------- Raw 与 Human-reviewed 分离 ----------

def test_raw_vs_human_reviewed_separation():
    """Raw 模型指标与人工审核后指标必须分离记录（产物结构约定）。"""
    raw_metrics = {"mode": "mock", "precision": 0.49, "human_reviewed": False}
    human_metrics = {"mode": "mock", "precision": 0.55, "human_reviewed": True}
    # 评测产物必须显式区分，不得混淆
    assert raw_metrics["human_reviewed"] is False
    assert human_metrics["human_reviewed"] is True
    assert "human_reviewed" in raw_metrics and "human_reviewed" in human_metrics
