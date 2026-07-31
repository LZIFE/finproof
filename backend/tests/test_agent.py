"""Phase 5 Agent Workflow 专项测试：完整流程/多 claim/verification 调用/report 生成/异常处理。"""

import json

import pytest

from app.core.exceptions import AppError
from app.db import SessionLocal
from app.models.audit import AuditReport
from app.services.agent.executor import run_audit
from app.services.agent.tools import extract_claims, require_report_to_verify

MINI_REPORT = """# 测试研报（Agent 审计用）

公司2025年实现营业收入4564.52亿元，同比增长12.11%。
归母净利润439.45亿元，同比增长38.02%，盈利能力增强。
全年经营活动现金流量净额533.46亿元。
2025年第一季度营业收入1278.39亿元，同比增长20.49%。
海外业务已成为公司利润增长的核心引擎。
公司竞争优势领先行业。
"""


@pytest.fixture()
def audit_doc():
    """注册一份 REPORT_TO_VERIFY 研报（conftest 每测试清库）。"""
    from app.services import document_service as dsvc

    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="audit_report.md",
            data=MINI_REPORT.encode("utf-8"),
            document_role="REPORT_TO_VERIFY",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        return doc.id


def test_agent_full_workflow(audit_doc):
    """完整流程运行：4 步执行日志 + 审计报告 + 入库。"""
    with SessionLocal() as s:
        result = run_audit(s, audit_doc, mode="mock")
    steps = [st["name"] for st in result["plan"]["log"]]
    assert steps == ["extract_claims", "retrieve_evidence", "verify_claims", "generate_report"]
    rep = result["report"]
    assert rep["summary"]["total_claims"] > 0
    assert rep["summary"]["supported_count"] + rep["summary"]["refuted_count"] >= 0
    with SessionLocal() as s:
        row = s.get(AuditReport, result["audit_id"])
        assert row is not None and row.report_json and row.plan_json


def test_agent_multi_claim(audit_doc):
    """多 claim 处理：提取多条主张并逐一核验。"""
    with SessionLocal() as s:
        claims = extract_claims(s, audit_doc, mode="mock")
        assert len(claims) >= 3  # 迷你研报至少 3 条主张
        result = run_audit(s, audit_doc, mode="mock")
    assert result["report"]["summary"]["total_claims"] >= 3
    assert len(result["report"]["verification_results"]) == result["report"]["summary"]["total_claims"]


def test_agent_verification_called(audit_doc):
    """verification 调用正确：每条主张都有状态/类型/原因。"""
    with SessionLocal() as s:
        result = run_audit(s, audit_doc, mode="mock")
    for v in result["report"]["verification_results"]:
        assert v["verification_status"] in (
            "SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "UNABLE_TO_DETERMINE",
        )
        assert v["verification_type"] and v["reason"]


def test_agent_report_structure(audit_doc):
    """report 生成正确：Summary + Risk Findings（Claim/Evidence/Calculation/Conclusion）+ Evidence Chain。"""
    with SessionLocal() as s:
        result = run_audit(s, audit_doc, mode="mock")
    rep = result["report"]
    for k in ("summary", "findings", "evidence_chain", "verification_results"):
        assert k in rep
    for k in ("total_claims", "supported_count", "refuted_count", "partially_supported_count",
              "insufficient_count", "unknown_count"):
        assert k in rep["summary"]
    for f in rep["findings"]:
        for k in ("claim", "evidence", "calculation", "conclusion", "reason"):
            assert k in f
    for c in rep["evidence_chain"]:
        for k in ("claim", "evidence", "verification", "conclusion"):
            assert k in c


def test_agent_exception_handling(audit_doc):
    """异常处理：非 REPORT_TO_VERIFY 文档拒绝；不存在的文档 404。"""
    from app.services import document_service as dsvc

    with SessionLocal() as s:
        # 注册一个 SOURCE_DOCUMENT 角色文档 → 审计应拒绝
        src, _ = dsvc.register_document(
            s,
            filename="source.md",
            data="# 源文档\n\n收入数据 100 亿元".encode("utf-8"),
            document_role="SOURCE_DOCUMENT",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        with pytest.raises(AppError) as ei:
            require_report_to_verify(s, src.id)
        assert ei.value.code == "INVALID_DOCUMENT_ROLE"
        with pytest.raises(AppError) as ei2:
            require_report_to_verify(s, 99999)
        assert ei2.value.code == "DOCUMENT_NOT_FOUND"
