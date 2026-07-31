"""Phase 6 Risk Engine 专项测试：REFUTED/SUPPORTED/语义/证据不足/整体评分/API。"""

import json

import pytest

from app.db import SessionLocal
from app.services.risk.risk_engine import assess_claim
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)


def test_refuted_claim_high_risk():
    """REFUTED + 数字核验 → FINANCIAL_ERROR，HIGH，80-100，reason 可解释。"""
    r = assess_claim(
        {"claim_id": "C1", "claim_type": "GROWTH_RATE"},
        {"verification_status": STATUS_REFUTED, "verification_type": "GROWTH_RATE_CHECK",
         "confidence": 0.9, "calculation_detail": {"calculated_growth_pp": 13.73, "claimed_growth_pp": 38.02}},
    )
    d = r.to_dict()
    assert d["risk_level"] == "HIGH" and 80 <= d["risk_score"] <= 100
    assert d["risk_type"] == "FINANCIAL_ERROR"
    assert len(d["risk_reason"]) >= 2  # 规则可解释


def test_supported_claim_low_risk():
    """SUPPORTED → LOW，0-20。"""
    r = assess_claim(
        {"claim_id": "C2", "claim_type": "FINANCIAL_VALUE"},
        {"verification_status": STATUS_SUPPORTED, "verification_type": "EXACT_VALUE_CHECK", "confidence": 0.98},
    )
    d = r.to_dict()
    assert d["risk_level"] == "LOW" and 0 <= d["risk_score"] <= 20


def test_semantic_partial_risk():
    """PARTIALLY_SUPPORTED + 语义核验 → SEMANTIC_RISK，MEDIUM，40-70。"""
    r = assess_claim(
        {"claim_id": "C3", "claim_type": "OPINION"},
        {"verification_status": STATUS_PARTIALLY_SUPPORTED, "verification_type": "SEMANTIC_SUPPORT_CHECK", "confidence": 0.6},
    )
    d = r.to_dict()
    assert d["risk_type"] == "SEMANTIC_RISK" and d["risk_level"] == "MEDIUM"
    assert 40 <= d["risk_score"] <= 70


def test_insufficient_evidence_risk():
    """INSUFFICIENT_EVIDENCE → EVIDENCE_RISK，60-90。"""
    r = assess_claim(
        {"claim_id": "C4"},
        {"verification_status": STATUS_INSUFFICIENT, "verification_type": "EXACT_VALUE_CHECK", "confidence": 0.4},
    )
    d = r.to_dict()
    assert d["risk_type"] == "EVIDENCE_RISK" and 60 <= d["risk_score"] <= 90


def test_forecast_risk_boost():
    """预测类主张（被描述为事实）→ FORECAST_RISK 加分。"""
    r = assess_claim(
        {"claim_id": "C5", "claim_type": "FORECAST", "original_text": "未来收入将快速增长"},
        {"verification_status": STATUS_PARTIALLY_SUPPORTED, "verification_type": "SEMANTIC_SUPPORT_CHECK", "confidence": 0.5},
    )
    assert r.risk_type == "FORECAST_RISK" or "预测类主张" in r.risk_reason


def test_overall_score_calculation():
    """assess_audit 整体评分：overall 公式（0.5×max + 0.5×风险点平均）+ 分布。"""
    from app.models.audit import AuditReport
    from app.services import document_service as dsvc
    from app.services.agent.executor import run_audit
    from app.services.risk.risk_engine import assess_audit

    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="risk_report.md",
            data="# 风险测试研报\n\n公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n归母净利润439.45亿元，同比增长38.02%。\n公司竞争优势领先行业。".encode("utf-8"),
            document_role="REPORT_TO_VERIFY",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        result = run_audit(s, doc.id, mode="mock")
        report = assess_audit(s, result["audit_id"], persist=True)
        d = report.to_dict()
        assert d["overall_risk_score"] > 0 and d["overall_risk_level"] in ("LOW", "MEDIUM", "HIGH")
        assert sum(d["risk_distribution"].values()) == len(d["claim_details"]) > 0
        # risk_assessments 入库
        from app.models.risk import RiskAssessmentRow

        n = s.query(RiskAssessmentRow).filter(RiskAssessmentRow.audit_id == result["audit_id"]).count()
        assert n == len(d["claim_details"])


def test_risk_api(tmp_path, monkeypatch):
    """Risk API：POST 生成评分 + GET 查询（整体/distribution/top_risks/claim_details）。"""
    from app.models.audit import AuditReport
    from app.services import document_service as dsvc
    from app.services.agent.executor import run_audit

    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="risk_api.md",
            data="# API 测试研报\n\n公司2025年实现营业收入4564.52亿元，同比增长12.11%。".encode("utf-8"),
            document_role="REPORT_TO_VERIFY",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        result = run_audit(s, doc.id, mode="mock")
        audit_id = result["audit_id"]

    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    r = client.post(f"/api/v1/risk-assessments/{audit_id}")
    assert r.status_code == 201
    body = r.json()
    for k in ("overall_risk_score", "overall_risk_level", "risk_distribution", "top_risks", "claim_details"):
        assert k in body
    assert len(body["claim_details"]) > 0 and len(body["top_risks"]) > 0

    r2 = client.get(f"/api/v1/risk-assessments/{audit_id}")
    assert r2.status_code == 200 and r2.json()["overall_risk_score"] == body["overall_risk_score"]

    r3 = client.get("/api/v1/risk-assessments/99999")
    assert r3.status_code == 404
