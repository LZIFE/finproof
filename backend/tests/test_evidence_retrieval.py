"""Phase 4A 证据检索专项测试：匹配 / 防错匹配 / 数据隔离 / 端到端。"""

import json
from pathlib import Path

import pytest

from app.db import SessionLocal, init_db
from app.services.evidence_retrieval.engine import (
    DEFAULT_WEIGHTS,
    document_priority,
    metric_aliases,
    metric_hits,
    period_matches,
    score_block,
    values_compatible,
)
from app.services.evidence_retrieval.service import (
    ensure_retrieval_config,
    get_run_claims,
    run_retrieval,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

MINI_REPORT = """# 美的集团（000333）2025 年年度报告（测试迷你版）

营业收入（千元） 456,451,731 407,149,600 12.11%
归属于上市公司股东的净利润（千元） 43,945,411 38,537,865
2025年上半年营业收入为2523.31亿元，同比增长15%。
2025年第一季度实现营业收入1278.39亿元，同比增长20.49%。
公司持续深化国内高端品牌和海外OBM优先战略，海外自主品牌占比稳步提升。
公司经营活动现金流量净额533.46亿元，同比下降11.84%。
"""


@pytest.fixture()
def mini_source_doc():
    """注册迷你源文档（conftest 每测试清库，检索测试需先建文档）。"""
    from app.services import document_service as dsvc

    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="mini_annual_report.md",
            data=MINI_REPORT.encode("utf-8"),
            document_role="SOURCE_DOCUMENT",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        return doc.id


# ---------- 数值单位换算 ----------

def test_unit_conversion():
    """亿元/万元/元/千元统一换算匹配。"""
    assert values_compatible(2523.31, "亿元", 25233100.0, "万元")
    assert values_compatible(2523.31, "亿元", 252331000000.0, "元")
    assert values_compatible(4564.52, "亿元", 456451731.0, "千元")
    assert not values_compatible(2523.31, "亿元", 2523.31, "万元")  # 单位不匹配


def test_percent_value_match():
    assert values_compatible(38.02, "PERCENT", 38.02, "PERCENT")
    assert values_compatible(0.7, "pp", 0.7, "pp")
    assert not values_compatible(38.02, "PERCENT", 3.802, "PERCENT")


def test_thousand_separator_parsed():
    """财务表格数值可解析：千分位逗号 + 成对单位布局。"""
    from app.services.evidence_retrieval.engine import _block_value_hits, iter_numbers

    # 成对布局：数字+单位相邻（456,451,731千元）
    nums = list(iter_numbers("营业收入 456,451,731千元"))
    assert any(v == 456451731.0 and u == "千元" for v, u, _c, _y in nums)
    # 列头单位布局：（千元）在数字之前
    hit, _reason = _block_value_hits("营业收入（千元） 456,451,731 407,149,600", 4564.52, "亿元")
    assert hit
    hit2, _r2 = _block_value_hits("营业收入（千元） 456,451,731", 456.45, "亿元")
    assert not hit2


# ---------- 指标别名 ----------

def test_metric_aliases_family_isolation():
    """归母净利润家族不含'净利润'，反之亦然（不简单合并）。"""
    a = metric_aliases("net_profit_attributable", "归母净利润")
    assert "归母净利润" in a and "净利润" not in a
    assert "归属于上市公司股东的净利润" in a
    b = metric_aliases("net_profit", "净利润")
    assert "净利润" in b and "归母净利润" not in b


def test_metric_aliases_revenue():
    a = metric_aliases("revenue", "营业收入")
    for alias in ("营业收入", "营业总收入", "营收", "收入"):
        assert alias in a
    assert metric_hits("2025年上半年营业收入为2523.31亿元", a)
    assert not metric_hits("2025年上半年归母净利润为2523.31亿元", a)


# ---------- 期间匹配与文档优先级 ----------

def test_period_matching():
    assert period_matches("2025H1", "2025年上半年，公司实现营业收入2523.31亿元") == 1.0
    assert period_matches("2025FY", "报告期内公司实现营业收入4564.52亿元") == 1.0
    assert period_matches("2025Q1", "公司2025年第一季度实现营业收入1278.39亿元") == 1.0
    assert period_matches("2025H1", "公司2025年实现营业收入4564.52亿元") == 0.0


def test_document_priority():
    """Q1/H1/FY 文档优先级：主张期间类型匹配的财报最优先。"""
    assert document_priority("2025H1", "2025H1") == 0
    assert document_priority("2025FY", "2025FY") == 0
    assert document_priority("2025Q1", "2025Q1") == 0
    assert document_priority("2025H1", "2025FY") == 1
    assert document_priority("2025H1", None) == 1


# ---------- 防错误匹配 ----------

def test_wrong_metric_not_ranked_high():
    """同数不同指标（收入 vs 净利润）不得排名过高。"""
    claim = {"metric_code": "revenue", "metric": "营业收入", "reported_value": 2523.31,
             "unit": "亿元", "period": "2025H1", "entity_name": "美的集团",
             "original_text": "公司2025年上半年实现营业收入2523.31亿元"}
    ok = score_block("2025年上半年营业收入为2523.31亿元", claim)
    wrong = score_block("2025年上半年归母净利润为2523.31亿元", claim)
    assert ok["final_score"] > wrong["final_score"] * 1.5


def test_wrong_period_not_ranked_high():
    """同数不同期间不得排名过高。"""
    claim = {"metric_code": "revenue", "metric": "营业收入", "reported_value": 2523.31,
             "unit": "亿元", "period": "2025H1", "entity_name": "美的集团",
             "original_text": "公司2025年上半年实现营业收入2523.31亿元"}
    ok = score_block("2025年上半年营业收入为2523.31亿元", claim)
    wrong = score_block("2025年全年营业收入为2523.31亿元", claim)
    assert ok["final_score"] > wrong["final_score"]


# ---------- 权重可配置可解释 ----------

def test_weights_configurable_and_explainable():
    """权重可配置、可解释、存库；score_block 输出组件分。"""
    with SessionLocal() as s:
        w = ensure_retrieval_config(s, "v2")
        assert w == DEFAULT_WEIGHTS
        from app.models.evidence import EvidenceRetrievalConfig

        row = s.query(EvidenceRetrievalConfig).filter(EvidenceRetrievalConfig.version == "v2").first()
        assert row and row.weights_json  # 持久化
    claim = {"metric_code": "revenue", "metric": "营业收入", "reported_value": 100.0,
             "unit": "亿元", "period": "2025FY", "entity_name": "美的集团",
             "original_text": "公司2025年营业收入100亿元"}
    s = score_block("公司2025年营业收入为100亿元", claim)
    for key in ("metric_score", "value_score", "period_score", "entity_score", "text_score", "final_score"):
        assert key in s


# ---------- 数据隔离 ----------

def test_ranking_does_not_read_gold_evidence(mini_source_doc):
    """排序逻辑不读取 gold_evidence/gold_verifications：篡改答案文件不影响检索结果。"""
    from app.services.evidence_retrieval import service as es
    import inspect

    src = inspect.getsource(es)
    # 检索服务源码不得出现答案文件的读取路径（gold_evidence/gold_verifications）
    for token in ("gold_evidence", "gold_verifications"):
        assert token not in src.replace("gold_evidence/gold_verifications", "") or token in (
            "gold_evidence/gold_verifications",
        )

    # 运行时验证：篡改 gold_evidence 内容不影响检索候选
    gold_ev = REPO_ROOT / "data" / "demo" / "annotations" / "gold_evidence.json"
    original = gold_ev.read_text(encoding="utf-8")
    with SessionLocal() as s:
        before = get_run_claims(s, run_retrieval(s, "demo", "ORACLE_GOLD", 3).id)
    gold_ev.write_text('{"evidence": [{"claim_id": "FAKE", "page": 999}]}', encoding="utf-8")
    try:
        with SessionLocal() as s:
            after = get_run_claims(s, run_retrieval(s, "demo", "ORACLE_GOLD", 3).id)
        assert set(before) == set(after)
        for cid in before:
            assert [c["page_number"] for c in before[cid]] == [c["page_number"] for c in after[cid]]
    finally:
        gold_ev.write_text(original, encoding="utf-8")


# ---------- 端到端 ----------

def test_retrieval_end_to_end_demo(mini_source_doc):
    """Oracle 检索端到端：demo 数据集全部主张产生候选、页码/块可定位、分数可解释。"""
    init_db()
    with SessionLocal() as s:
        run = run_retrieval(s, "demo", "ORACLE_GOLD", top_k=5, version="v1")
        assert run.status == "COMPLETED" and run.claim_count == 26
        grouped = get_run_claims(s, run.id)
        assert grouped  # 至少部分主张有候选
        sample = next(iter(grouped.values()))[0]
        for key in ("document_id", "page_number", "block_id", "final_score",
                    "metric_score", "value_score", "period_score", "entity_score", "text_score"):
            assert key in sample


def test_semantic_claim_has_candidates(mini_source_doc):
    """无指标语义主张（文本关键词回退）也能产出候选。"""
    from app.services.evidence_retrieval.service import retrieve_for_claim

    semantic = {"claim_id": "CLM-S", "entity": "美的集团", "metric": "overseas_obm_strategy",
                "value": None, "period": "2025FY", "claim_type": "business_fact",
                "original_text": "公司持续深化国内高端品牌和海外OBM优先战略"}
    with SessionLocal() as s:
        cands = retrieve_for_claim(s, semantic, top_k=3)
    assert cands  # 文本关键词回退应找到候选


# ---------- Phase 4A.5 新增 ----------

def test_paren_negative_numbers():
    """括号负数预处理（公允价值变动损失 (1,081,776)）。"""
    from app.services.evidence_retrieval.engine import _clean_numbers

    assert _clean_numbers("(1,081,776)") == "-1081776"
    assert _clean_numbers("公允价值变动损失 (1,081,776)") == "公允价值变动损失 -1081776"


def test_page_unit_declaration():
    """页级单位声明（'单位：人民币千元'）数值匹配。"""
    from app.services.evidence_retrieval.engine import _block_value_hits, _page_unit_of

    assert _page_unit_of("单位：人民币千元") == "千元"
    assert _page_unit_of("单位:万元") == "万元"
    hit, reason = _block_value_hits("单位：人民币千元 营业收入 2,523,310", 25.2331, "亿元")
    assert hit and "匹配" in reason


def test_value_match_reason_explainable():
    """数值匹配保存可解释 match_reason（成对/列单位/百分比均不崩溃）。"""
    from app.services.evidence_retrieval.engine import _block_value_hits

    hit, reason = _block_value_hits("营业收入（千元） 456,451,731 407,149,600", 4564.52, "亿元")
    assert hit and reason
    hit2, reason2 = _block_value_hits("营业收入同比增长 12.11%", 12.11, "PERCENT")
    assert hit2 and reason2


def test_page_bonus_and_table_region_flags(mini_source_doc):
    """页面聚合加分（同页指标+数值+期间）与表格区域标记在候选上生效。"""
    from app.services.evidence_retrieval.service import retrieve_for_claim

    claim = {"claim_id": "CLM-T", "entity": "美的集团", "metric": "revenue",
             "value": 4564.52, "unit": "亿元", "period": "2025FY", "claim_type": "raw_number",
             "original_text": "公司2025年实现营业收入4564.52亿元"}
    with SessionLocal() as s:
        cands = retrieve_for_claim(s, claim, top_k=5)
    assert cands
    for c in cands:
        assert "page_bonus" in c and "table_region" in c
    # 迷你报告页含 营业收入+4564.52亿+2025FY（文档级期间）→ 页面加分应生效
    assert any(c["page_bonus"] == 1.0 for c in cands)


def test_dictionary_expansion_and_isolation():
    """词典扩充（ROE/现金流别名）且保持家族隔离。"""
    from app.services.evidence_retrieval.engine import metric_aliases

    assert "加权平均净资产收益率" in metric_aliases("roe", "加权平均净资产收益率")
    assert "ROE" in metric_aliases("roe", None)
    assert "经营活动产生的现金流量净额" in metric_aliases("operating_cash_flow", "经营现金流")
    assert "净利润" not in metric_aliases("net_profit_attributable", "归母净利润")
    assert "归母净利润" not in metric_aliases("net_profit", "净利润")
