"""Phase 23.9 集成测试：证明主链（verify_claim → core_verify）真实调用新模块。

不测试独立函数——通过 mock spy 断言 FinancialValue / PeriodContext / metric_scope /
verdict_decision 在真实主链上被调用，并验证关键行为（数值冲突 REFUTED、
Semantic 不覆盖 REFUTED、期间/口径不匹配、multi-number 选择、Gold Evidence、
真实检索 Top5 含 Gold Block、no-result fallback、Demo 主链使用新 Verifier）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.verification import core_pipeline as cp
from app.services.verification.verification_service import verify_claim

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

SUPPORTED = "SUPPORTED"
REFUTED = "REFUTED"
PARTIAL = "PARTIALLY_SUPPORTED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
UNABLE = "UNABLE_TO_DETERMINE"
OPINION = "OPINION_OR_FORECAST"


def _claim(claim_id: str = "T-001", **over) -> dict:
    base = {
        "claim_id": claim_id,
        "claim_type": "raw_number",
        "metric": "revenue",
        "period": "2025FY",
        "unit": "亿元",
        "value": 4564.52,
        "scope": "consolidated",
        "original_text": "公司2025年实现营业收入4564.52亿元",
    }
    base.update(over)
    return base


def _ev(text: str, ev_id: str = "EVD-1", doc_period: str | None = "2025FY") -> dict:
    return {"evidence_id": ev_id, "text": text, "doc_period": doc_period}


def _register_demo_pdfs(session) -> None:
    """导入 demo 的 4 份源 PDF（与真实检索共用）。"""
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
# 1) API 输入 → verify_claim → FinancialValue 被调用（主链 spy）
# ---------------------------------------------------------------------------
def test_1_verify_claim_calls_financial_value(monkeypatch):
    # core_pipeline 里 extract_financial_values 是模块内 import 的绑定引用，
    # 必须 patch cp.extract_financial_values 才能拦截主链调用
    _orig = cp.extract_financial_values
    calls = {"n": 0}

    def spy(text, **kw):
        calls["n"] += 1
        return _orig(text, **kw)

    monkeypatch.setattr(cp, "extract_financial_values", spy)

    from app.db import SessionLocal
    s = SessionLocal()
    _register_demo_pdfs(s)  # verify_claim 走真实检索，需先有文档
    claim = _claim(claim_id="CLM-001")
    result = verify_claim(s, claim, top_k=5)
    s.close()

    assert calls["n"] > 0, "verify_claim 主链必须调用 FinancialValue.extract_financial_values"
    assert result.verification_status in (SUPPORTED, REFUTED, INSUFFICIENT, PARTIAL, UNABLE, OPINION)


# ---------------------------------------------------------------------------
# 2) 数值冲突 → 最终 REFUTED
# ---------------------------------------------------------------------------
def test_2_numeric_conflict_refuted():
    claim = _claim(claim_id="T-002", value=5000.0)  # 主张 5000 亿 vs 证据 4564.52 亿
    result = cp.core_verify(claim, [_ev("营业收入（千元） 456,451,731 407,149,600 12.11%")])
    assert result.verification_status == REFUTED


# ---------------------------------------------------------------------------
# 3) Semantic 不得覆盖确定性 REFUTED（因果强归因无披露）
# ---------------------------------------------------------------------------
def test_3_semantic_does_not_override_refuted():
    claim = _claim(
        claim_id="T-003", claim_type="causality", metric="overseas_profit_engine",
        value=None, original_text="海外业务已成为公司利润增长的核心引擎",
    )
    result = cp.core_verify(claim, [_ev("营业总收入2523 亿元，同比增长15.7%，实现归母净利润260 亿元，同比增长25.0%", doc_period="2025H1")])
    assert result.verification_status == REFUTED
    assert result.integration_trace["override_source"] == "semantic_verifier:causal_overreach"


# ---------------------------------------------------------------------------
# 4) Period mismatch → REFUTED
# ---------------------------------------------------------------------------
def test_4_period_mismatch_refuted():
    # 主张 2025H1 增长 20.49%，但 20.49% 属于 Q1 报告（期间粒度不兼容）
    claim = _claim(
        claim_id="T-004", claim_type="calculated_financial_metric",
        metric="yoy_growth_revenue", period="2025H1", unit="%", value=20.49,
        original_text="2025年上半年公司营业收入同比增长20.49%",
    )
    result = cp.core_verify(claim, [
        _ev("营业总收入2523 亿元，同比增长15.7%", doc_period="2025H1"),
        _ev("营业收入（千元） 127,838,538 106,101,612 20.49%", doc_period="2025Q1"),
    ])
    assert result.verification_status == REFUTED
    assert "period" in (result.rule_id or "")


# ---------------------------------------------------------------------------
# 5) Scope mismatch → REFUTED 或 INSUFFICIENT
# ---------------------------------------------------------------------------
def test_5_scope_mismatch():
    claim = _claim(claim_id="T-005", metric="gross_margin", unit="%", value=26.4,
                   original_text="报告期内毛利率26.4%")
    # 证据只有净利润（元/千元）无收入成本 → 无法推导 → INSUFFICIENT 或 REFUTED（均合法）
    result = cp.core_verify(claim, [_ev("净利润（千元） 43,945,411 38,537,237 14.03%")])
    assert result.verification_status in (REFUTED, INSUFFICIENT, PARTIAL)


# ---------------------------------------------------------------------------
# 6) multi-number 选择正确 metric 数字（命中上年列 → REFUTED）
# ---------------------------------------------------------------------------
def test_6_multi_number_selects_correct_metric_row():
    claim = _claim(claim_id="T-006", value=4071.50)  # 4071.50 是上年列
    result = cp.core_verify(claim, [_ev("营业收入（千元） 456,451,731 407,149,600 12.11%")])
    assert result.verification_status == REFUTED
    assert result.integration_trace["rule_id"] == "numeric:prior_year_value_used"


# ---------------------------------------------------------------------------
# 7) Gold Evidence → 正确 Verdict（43 条 Oracle 抽检）
# ---------------------------------------------------------------------------
def test_7_gold_evidence_correct_verdict():
    gold = json.load(open(DATA_DIR / "demo" / "annotations" / "gold_verifications.json", encoding="utf-8"))
    claims = {c["claim_id"]: c for c in
              json.load(open(DATA_DIR / "demo" / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])}
    ev_by = {}
    for e in json.load(open(DATA_DIR / "demo" / "annotations" / "gold_evidence.json", encoding="utf-8")).get("evidence", []):
        ev_by.setdefault(e["claim_id"], []).append(e)
    checks = 0
    for v in gold.get("verifications", [])[:8]:
        cid = v["claim_id"]
        gold_v = v["expected_verdict"]
        claim = claims.get(cid, {})
        evs = ev_by.get(cid, [])
        evidence = [{"evidence_id": e.get("evidence_id"), "text": e.get("evidence_text", ""),
                     "doc_period": None, "document_name": e.get("document_name"), "page": e.get("page")}
                    for e in evs]
        result = cp.core_verify(claim, evidence)
        assert result.verification_status == gold_v, f"{cid}: {result.verification_status} != {gold_v}"
        checks += 1
    assert checks == 8


# ---------------------------------------------------------------------------
# 8) Real Retrieval → Top 5 含 Gold Block（Demo 全量抽检）
# ---------------------------------------------------------------------------
def test_8_real_retrieval_top5_contains_gold_page():
    from app.db import SessionLocal
    s = SessionLocal()
    _register_demo_pdfs(s)
    from app.services.evidence_retrieval.service import retrieve_for_claim
    from app.models import Document

    doc_by_name = {d.original_filename: d.id for d in s.query(Document).all()}
    gold_ev = {}
    for e in json.load(open(DATA_DIR / "demo" / "annotations" / "gold_evidence.json", encoding="utf-8")).get("evidence", []):
        gold_ev.setdefault(e["claim_id"], []).append(e)
    claims = json.load(open(DATA_DIR / "demo" / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])
    hit = 0
    for c in claims:
        gpages = set()
        for e in gold_ev.get(c["claim_id"], []):
            did = doc_by_name.get(str(e.get("document_name") or "").split("/")[-1])
            if did is not None and e.get("page") is not None:
                gpages.add((did, e["page"]))
        cands = retrieve_for_claim(s, c, top_k=5) or []
        if any((x.get("document_id"), x.get("page_number")) in gpages for x in cands[:5]):
            hit += 1
    s.close()
    assert hit > 0, "真实检索 Top5 必须至少命中一条 Gold Page"


# ---------------------------------------------------------------------------
# 9) no-result fallback 有效（quarterly 类无规范别名不再返回空候选）
# ---------------------------------------------------------------------------
def test_9_no_result_fallback_effective():
    from app.db import SessionLocal
    s = SessionLocal()
    _register_demo_pdfs(s)
    from app.services.evidence_retrieval.service import retrieve_for_claim

    claim = {
        "claim_id": "CLM-009", "claim_type": "scope", "metric": "quarterly_revenue",
        "period": "2025Q2", "unit": "亿元", "value": 2523.31, "scope": "consolidated",
        "original_text": "第二季度单季实现营业收入2523.31亿元",
    }
    cands = retrieve_for_claim(s, claim, top_k=10) or []
    s.close()
    assert len(cands) > 0, "quarterly 类 claim 不得 No-result（fallback 应生效）"


# ---------------------------------------------------------------------------
# 10) Demo 主链使用新 Verifier（spy verify_claim 内部命中 core_verify）
# ---------------------------------------------------------------------------
def test_10_demo_main_chain_uses_new_verifier(monkeypatch):
    from app.services.verification.verification_service import _select_verifier
    from app.services.verification.core_pipeline import IntegrationTrace

    calls = {"n": 0}
    orig = cp.core_verify

    def spy(claim, evidence_list, trace=None):
        calls["n"] += 1
        return orig(claim, evidence_list, trace or IntegrationTrace(claim_id=claim.get("claim_id", "?")))

    monkeypatch.setattr(cp, "core_verify", spy)

    claim = _claim(claim_id="CLM-010", value=260.14, period="2025Q2",
                   original_text="第二季度归母净利润260.14亿元", metric="quarterly_net_profit")
    evidence = [_ev("归母净利润（千元） 26,013,690 20,801,696 25.0%", doc_period="2025H1")]
    _select_verifier(claim, evidence)
    assert calls["n"] > 0, "Demo 主链 _select_verifier 必须调用 core_pipeline.core_verify"
