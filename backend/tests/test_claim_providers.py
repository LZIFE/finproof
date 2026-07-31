"""Provider 单元测试：Mock 明确标识 / LLM 非法JSON / 空列表 / 超时重试 / 部分Schema失败。"""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.exceptions import AppError
from app.services.claims.providers import (
    DocumentContext,
    LLMClaimExtractionProvider,
    MockClaimExtractionProvider,
    load_prompt,
)


def _block(text: str, block_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=block_id, block_type="paragraph", text=text,
        page_number=1, heading_level=None,
    )


def _ctx(**kw) -> DocumentContext:
    base = dict(
        document_id=4, company_name="美的集团", stock_code="000333",
        report_year=2025, prompt_version="v1",
    )
    base.update(kw)
    return DocumentContext(**base)


# ---------- Mock ----------

def test_mock_provider_marked_and_no_gold():
    blocks = [
        _block("公司2025年实现营业收入4564.52亿元，同比增长12.11%。"),
        _block("归母净利润439.45亿元。"),
    ]
    result = MockClaimExtractionProvider().extract_claims(_ctx(), blocks)
    assert result.is_mock is True
    assert result.provider == "mock"
    assert result.claim_dicts
    assert all(d["extraction_method"] == "MOCK" for d in result.claim_dicts)
    # Mock 输出不包含金标准字段（claim_id / gold_verdict 等）
    for d in result.claim_dicts:
        assert "claim_id" not in d
        assert "gold_verdict" not in d


# ---------- LLM ----------

def test_llm_invalid_json():
    llm = LLMClaimExtractionProvider()
    with pytest.raises(AppError) as ei:
        llm._parse_response("{not valid json")
    assert ei.value.code == "INVALID_LLM_JSON"


def test_llm_empty_list():
    llm = LLMClaimExtractionProvider()
    assert llm._parse_response("[]") == []
    assert llm._parse_response('{"claims": []}') == []


def test_llm_partial_schema_failure():
    llm = LLMClaimExtractionProvider()
    items = [
        {"source_text": "有效主张", "normalized_claim": "有效主张", "claim_type": "GROWTH_RATE"},
        {"source_text": "非法枚举", "normalized_claim": "非法", "claim_type": "NOT_A_TYPE"},
        {"source_text": "", "normalized_claim": "", "claim_type": "GROWTH_RATE"},
    ]
    valid, failed = llm._to_claim_dicts(items)
    assert len(valid) == 1
    assert failed == 2
    assert valid[0]["extraction_method"] == "LLM"


def test_llm_extract_claims_with_fake_call():
    llm = LLMClaimExtractionProvider()

    def fake_call(messages):
        content = json.dumps({
            "claims": [{
                "source_text": "公司2025年营业收入4564.52亿元",
                "normalized_claim": "美的集团2025年营业收入4564.52亿元",
                "claim_type": "ABSOLUTE_FINANCIAL_VALUE",
                "reported_value": 4564.52,
                "unit": "亿元",
                "period": "2025FY",
                "period_type": "YEAR",
                "risk_level": "HIGH",
                "confidence": 0.95,
            }]
        })
        return content, {"total_tokens": 99}

    llm._call_model = fake_call  # type: ignore[method-assign]
    result = llm.extract_claims(_ctx(), [_block("公司2025年营业收入4564.52亿元")])
    assert result.is_mock is False
    assert len(result.claim_dicts) == 1
    assert result.claim_dicts[0]["claim_type"] == "ABSOLUTE_FINANCIAL_VALUE"
    assert result.raw_response_hash  # 原始响应哈希已记录
    assert result.token_usage == {"total_tokens": 99}


def test_llm_timeout_retries_then_fails(monkeypatch):
    import app.services.claims.providers as providers_mod

    calls = {"n": 0}

    def timeout_post(*args, **kwargs):
        calls["n"] += 1
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(providers_mod.httpx, "post", timeout_post)
    cfg = SimpleNamespace(
        claim_extraction_base_url="http://x", claim_extraction_model="m",
        claim_extraction_api_key="k", claim_extraction_timeout_seconds=1,
        claim_extraction_max_retries=2, claim_extraction_provider="openai_compatible",
        claim_extraction_prompt_version="v1",
    )
    llm = LLMClaimExtractionProvider(settings=cfg)
    with pytest.raises(AppError) as ei:
        llm._call_model([{"role": "user", "content": "x"}])
    assert ei.value.code == "LLM_CALL_FAILED"
    assert calls["n"] == 3  # max_retries=2 → 共 3 次尝试


# ---------- Prompt ----------

def test_prompt_version_management():
    prompt = load_prompt("v1")
    assert "可核验金融主张" in prompt
    assert "JSON" in prompt
    with pytest.raises(AppError) as ei:
        load_prompt("v99")
    assert ei.value.code == "PROMPT_NOT_FOUND"
