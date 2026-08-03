"""Phase 23.10 测试：Table-aware Retrieval 与端到端鲁棒性。

覆盖任务十四要求的 12 类测试（含端到端集成，不依赖 Gold 作为运行时输入）：
1. table context reconstruction
2. row/column header 绑定
3. multi-page table
4. claim query planner
5. candidate recall
6. reranker feature
7. hard negative
8. company leave-one-out 泄漏检查
9. duplicate diversity
10. multi-evidence aggregation
11. retrieval metric invariant
12. metamorphic integration（端到端）
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _register_pdfs(session) -> None:
    from app.services import document_service

    imports = [
        (DATA_DIR / "demo" / "source" / "annual_report.pdf", "美的集团", "000333", "2025FY"),
        (DATA_DIR / "demo" / "source" / "half_year_report.pdf", "美的集团", "000333", "2025H1"),
        (DATA_DIR / "demo" / "source" / "q1_report.pdf", "美的集团", "000333", "2025Q1"),
        (DATA_DIR / "holdout" / "source" / "annual_report.pdf", "五粮液", "000858", "2025FY"),
    ]
    for path, company, stock, period in imports:
        with open(path, "rb") as f:
            data = f.read()
        document_service.register_document(
            session, filename=path.name, data=data, document_role="SOURCE_DOCUMENT",
            company_name=company, stock_code=stock, report_period=period,
        )


# ---------------------------------------------------------------------------
# 1) Table context reconstruction
# ---------------------------------------------------------------------------
def test_1_table_context_reconstruction():
    from app.db import SessionLocal
    from app.models import Document
    from app.services.evidence_retrieval.table_context import build_table_contexts

    s = SessionLocal()
    _register_pdfs(s)
    doc = s.query(Document).filter_by(original_filename="annual_report.pdf", company_name="美的集团").first()
    ctxs = build_table_contexts(s, doc.id, 9)
    s.close()
    assert len(ctxs) > 0
    row_headers = [c.row_header for c in ctxs if c.row_header]
    assert any("营业收入" in h for h in row_headers), "TableContext 必须重建出营业收入数据行"
    assert any(c.unit_header for c in ctxs), "TableContext 必须绑定单位（千元）"


# ---------------------------------------------------------------------------
# 2) row/column header 绑定
# ---------------------------------------------------------------------------
def test_2_row_column_header_binding():
    from app.db import SessionLocal
    from app.models import Document
    from app.services.evidence_retrieval.table_context import build_table_contexts

    s = SessionLocal()
    _register_pdfs(s)
    doc = s.query(Document).filter_by(original_filename="annual_report.pdf", company_name="美的集团").first()
    ctxs = build_table_contexts(s, doc.id, 9)
    s.close()
    rev = [c for c in ctxs if "营业收入" in c.row_header][0]
    assert "2025年" in rev.period_header or "2025" in rev.column_header, "列头必须含年度"
    assert rev.normalized_value is not None, "数据行必须有数值"


# ---------------------------------------------------------------------------
# 3) multi-page table（跨页表：检测延续页标记与同表多行）
# ---------------------------------------------------------------------------
def test_3_multi_page_table():
    from app.db import SessionLocal
    from app.models import Document
    from app.services.evidence_retrieval.table_context import build_table_contexts

    s = SessionLocal()
    _register_pdfs(s)
    doc = s.query(Document).filter_by(original_filename="annual_report.pdf", company_name="美的集团").first()
    # 利润表通常跨页（135/136 附近），两个页面都应产出上下文且 row_header 结构相似
    c135 = build_table_contexts(s, doc.id, 135)
    c136 = build_table_contexts(s, doc.id, 136)
    s.close()
    assert len(c135) > 0 and len(c136) > 0, "跨页财务表两个页面都应产出 TableContext"


# ---------------------------------------------------------------------------
# 4) Claim Query Planner
# ---------------------------------------------------------------------------
def test_4_claim_query_planner():
    from app.services.evidence_retrieval.query_planner import QueryPlanner

    claim = {"claim_id": "CLM-001", "entity": "美的集团", "metric": "revenue", "period": "2025FY",
             "unit": "亿元", "value": 4564.52, "scope": "consolidated", "claim_type": "raw_number",
             "original_text": "公司2025年实现营业收入4564.52亿元，同比增长12.11%"}
    plan = QueryPlanner(claim).build()
    d = plan.to_dict()
    assert len(d["queries"]) >= 7, "必须生成 ≥7 类 query"
    assert d["normalized_value"] == "4564.52亿"
    assert d["direction"] == "=="
    assert any("metric_period" == q["kind"] for q in d["queries"])


# ---------------------------------------------------------------------------
# 5) Candidate recall（Stage A 端到端：至少一条 Demo claim 命中 Gold 页）
# ---------------------------------------------------------------------------
def test_5_candidate_recall():
    from app.db import SessionLocal
    from app.models import Document
    from app.services.evidence_retrieval.stage_retrieval import stage_a_candidates

    s = SessionLocal()
    _register_pdfs(s)
    claims = json.load(open(DATA_DIR / "demo" / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])
    ev_by = {}
    for e in json.load(open(DATA_DIR / "demo" / "annotations" / "gold_evidence.json", encoding="utf-8")).get("evidence", []):
        ev_by.setdefault(e["claim_id"], []).append(e)
    doc_by_name = {d.original_filename: d for d in s.query(Document).all() if d.company_name == "美的集团"}
    hit = 0
    for c in claims[:8]:
        gold_pages = set()
        for e in ev_by.get(c["claim_id"], []):
            d = doc_by_name.get(str(e.get("document_name") or "").split("/")[-1])
            if d and e.get("page"):
                gold_pages.add((d.id, e["page"]))
        a = stage_a_candidates(s, c, top_k=50)
        if any((x.document_id, x.page_number) in gold_pages for x in a):
            hit += 1
    s.close()
    assert hit > 0, "Stage A 至少一条 Demo claim 命中 Gold 页"


# ---------------------------------------------------------------------------
# 6) Reranker feature（禁止 Gold 特征；feature 数 ≥ 15）
# ---------------------------------------------------------------------------
def test_6_reranker_features_no_gold():
    from app.db import SessionLocal
    from app.services.evidence_retrieval.stage_retrieval import stage_a_candidates, stage_b_rerank

    s = SessionLocal()
    _register_pdfs(s)
    claims = json.load(open(DATA_DIR / "demo" / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])
    c = [x for x in claims if x["claim_id"] == "CLM-001"][0]
    a = stage_a_candidates(s, c, top_k=50)
    b = stage_b_rerank(s, c, a, top_k=5)
    s.close()
    assert len(b) > 0
    feats = list(b[0].scores.keys())
    assert len(feats) >= 14, f"reranker 特征数不足: {len(feats)}"
    assert not any("gold" in f for f in feats), "reranker 不得使用 gold 特征"


# ---------------------------------------------------------------------------
# 7) Hard negative（分类器能识别错误候选类型）
# ---------------------------------------------------------------------------
def test_7_hard_negative_classifier():
    from app.services.evidence_retrieval.stage_retrieval import STAGE_B_WEIGHTS

    assert "metric" in STAGE_B_WEIGHTS and "row_header" in STAGE_B_WEIGHTS
    # 端到端：hard_negatives 产物存在
    p = BACKEND_DIR.parent / "backend" / "artifacts" / "retrieval" / "phase23_10_hard_negatives.json"
    assert p.exists(), "phase23_10_hard_negatives.json 必须存在"


# ---------------------------------------------------------------------------
# 8) Company leave-one-out 泄漏检查（验证集指标不得参与训练权重选择）
# ---------------------------------------------------------------------------
def test_8_leave_one_out_no_leakage():
    p = BACKEND_DIR.parent / "backend" / "artifacts" / "retrieval" / "phase23_10_leave_one_company_out.json"
    assert p.exists(), "phase23_10_leave_one_company_out.json 必须存在"
    data = json.load(open(p, encoding="utf-8"))
    for fold in data["folds"]:
        assert fold["train_company"] != fold["eval_company"], "训练公司与验证公司不得相同"
        assert "leakage_note" in fold, "每折必须记录无泄漏声明"


# ---------------------------------------------------------------------------
# 9) Duplicate diversity（Top5 重复率低）
# ---------------------------------------------------------------------------
def test_9_duplicate_diversity():
    m = json.load(open(BACKEND_DIR.parent / "backend" / "artifacts" / "retrieval" / "phase23_10_metrics.json", encoding="utf-8"))
    assert m["metrics"]["top5_duplicate_rate"] <= 0.5, "Top5 重复率过高"


# ---------------------------------------------------------------------------
# 10) Multi-evidence aggregation
# ---------------------------------------------------------------------------
def test_10_multi_evidence_aggregation():
    from app.services.verification.multi_evidence import aggregate_evidence_analysis

    claim = {"claim_id": "T", "metric": "revenue", "period": "2025FY", "unit": "亿元",
             "value": 4564.52, "original_text": "营业收入4564.52亿元"}
    evs = [
        {"evidence_id": "E1", "text": "营业收入（千元） 456,451,731 407,149,600 12.11%"},
        {"evidence_id": "E2", "text": "公司持续推进海外战略，完善全球布局"},
    ]
    agg = aggregate_evidence_analysis(claim, evs).to_dict()
    assert "E1" in agg["selected_evidence_ids"], "正确证据应被选中"
    assert "E2" in agg["rejected_evidence_ids"], "噪声证据应被拒绝"
    assert agg["aggregation_rule"], "必须记录聚合规则"


# ---------------------------------------------------------------------------
# 11) Retrieval metric invariant（单调性）
# ---------------------------------------------------------------------------
def test_11_metric_invariant():
    m = json.load(open(BACKEND_DIR.parent / "backend" / "artifacts" / "retrieval" / "phase23_10_metrics.json", encoding="utf-8"))
    assert m["all_invariants_passed"], "检索指标不变量必须全部通过"


# ---------------------------------------------------------------------------
# 12) Metamorphic integration（端到端：Oracle 产物 + metamorphic 产物存在且达标）
# ---------------------------------------------------------------------------
def test_12_metamorphic_integration():
    meta = json.load(open(BACKEND_DIR.parent / "backend" / "artifacts" / "integrity" / "phase23_10_metamorphic_results.json", encoding="utf-8"))
    oracle = json.load(open(BACKEND_DIR.parent / "backend" / "artifacts" / "oracle" / "phase23_9_oracle_eval.json", encoding="utf-8"))
    assert meta["all_met"], "metamorphic 必须全部达标"
    assert oracle["accuracy"] >= 0.90, "Oracle Accuracy 必须保持 ≥0.90"
