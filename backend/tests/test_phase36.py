"""Phase 3.6 专项测试（第一批：金标准泄漏防护；其余随实现批次补充）。"""

import importlib
import inspect
from pathlib import Path

import pytest

import app.services.claims.guard as guard_mod
from app.services.claims.guard import assert_extraction_isolated


def test_extraction_service_cannot_read_gold():
    """提取服务源码不得引用 gold/holdout/artifacts 路径（运行时防护断言）。"""
    assert_extraction_isolated()  # 不抛异常即通过


def test_guard_detects_injected_gold_reference(tmp_path):
    """注入含 gold_claims 引用的文件应被防护检出。"""
    evil = tmp_path / "_leak_evil.py"
    evil.write_text("x = 'data/demo/annotations/gold_claims.json'\n", encoding="utf-8")
    orig = list(guard_mod.SCAN_ROOTS)
    guard_mod.SCAN_ROOTS = orig + [evil]
    try:
        with pytest.raises(RuntimeError) as ei:
            guard_mod.assert_extraction_isolated()
        assert "gold_claims" in str(ei.value)
    finally:
        guard_mod.SCAN_ROOTS = orig


def test_gold_file_changes_do_not_affect_extraction(tmp_path):
    """gold 文件内容变化不影响提取结果（提取链路不读金标准）。"""
    from app.db import SessionLocal
    from app.services import document_service as dsvc
    from app.services.claim_service import _get_document_blocks
    from app.services.claims.rule_extractor import RuleBasedCandidateExtractor

    # conftest 每测试清空数据库，需先注册报告文档
    report = Path(__file__).resolve().parents[2] / "data" / "demo" / "reports" / "ai_report_with_errors.md"
    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s, filename=report.name, data=report.read_bytes(),
            document_role="REPORT_TO_VERIFY", company_name="美的集团",
            stock_code="000333", report_period="2025FY",
        )
        blocks = _get_document_blocks(s, doc.id)

    extractor = RuleBasedCandidateExtractor(report_year=2025)
    before = [(c.metric_code, c.reported_value, c.period) for c in extractor.extract(blocks).candidates]

    # 模拟金标准被"篡改"（临时备份-覆盖-恢复）
    gold_path = (
        Path(__file__).resolve().parents[2]
        / "data" / "demo" / "annotations" / "gold_claims.json"
    )
    original = gold_path.read_text(encoding="utf-8")
    gold_path.write_text('{"claims": [{"claim_id": "FAKE", "original_text": "伪造"}]}', encoding="utf-8")
    try:
        after = [(c.metric_code, c.reported_value, c.period) for c in extractor.extract(blocks).candidates]
        assert before == after  # 提取结果与金标准内容无关
    finally:
        gold_path.write_text(original, encoding="utf-8")
        assert gold_path.read_text(encoding="utf-8") == original  # 恢复冻结文件


def test_provider_signatures_have_no_gold_input():
    """Provider 输入仅含文档上下文与文本块，不含金标准参数。"""
    from app.services.claims import providers

    for cls in (
        providers.MockClaimExtractionProvider,
        providers.RuleOnlyClaimExtractionProvider,
        providers.LLMClaimExtractionProvider,
        providers.HybridClaimExtractionProvider,
    ):
        params = " ".join(inspect.signature(cls.extract_claims).parameters)
        assert "gold" not in params.lower()
