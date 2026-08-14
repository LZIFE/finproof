"""backend/tests/test_generic_verification/test_extraction_provider.py"""
import json

import pytest

from app.core.exceptions import AppError
from app.services.generic_verification.claim_extraction import (
    GenericClaimExtractionResult,
    GenericClaimExtractor,
    load_generic_prompt,
)


def test_load_generic_prompt_missing_version():
    with pytest.raises(AppError):
        load_generic_prompt("does_not_exist")


def test_mock_when_no_llm_config(monkeypatch):
    monkeypatch.setattr("app.core.config.get_settings", lambda: _FakeSettings())
    extractor = GenericClaimExtractor()
    blocks = [
        {"index": 0, "text": "营收 1.2 亿元", "block_type": "paragraph"},
        {"index": 1, "text": "普通段落", "block_type": "paragraph"},
    ]
    result = extractor.extract(blocks, "generic_claim_extraction_v1")
    assert isinstance(result, GenericClaimExtractionResult)
    assert result.is_mock is True
    assert len(result.claims) >= 1
    assert result.claims[0].claim_kind == "NUMERIC"


def test_llm_parse_response():
    extractor = GenericClaimExtractor()
    content = json.dumps([
        {"source_text": "营收 1.2 亿元", "claim_kind": "NUMERIC", "page_number": 1,
         "block_index": 0, "entities": ["公司A"], "numbers": [{"value": 1.2, "unit": "亿", "context": "营收"}],
         "dates": [], "cross_refs": [], "confidence": 0.9},
    ], ensure_ascii=False)
    items = extractor._parse_response(content)
    assert items[0]["claim_kind"] == "NUMERIC"


def test_to_claim_sanitizes_malformed_llm_fields():
    """畸形 LLM 字段（不可信边界输入）不得抛异常（P2 回归）。"""
    extractor = GenericClaimExtractor()
    claim = extractor._to_claim(
        {
            "source_text": "营收 1.2 亿元",
            "claim_kind": "NUMERIC",
            "page_number": "第3页",       # 畸形 int
            "block_index": "0 (first)",    # 畸形 int
            "entities": "公司A",           # 非 list
            "confidence": "high",          # 畸形 float
        },
        {"page_number": 7},
        index=2,
    )
    assert claim.page_number == 7          # 回退到块页码
    assert claim.block_index == 2          # 回退到索引
    assert claim.entities == []            # 非 list → 空列表
    assert claim.confidence == 0.8         # 回退到默认值


def test_to_claim_keeps_zero_confidence():
    """confidence=0 是合法值，不得被 or 误判为缺失（P2 回归）。"""
    extractor = GenericClaimExtractor()
    claim = extractor._to_claim(
        {"source_text": "x", "claim_kind": "FACT", "confidence": 0},
        {"page_number": 1},
        index=0,
    )
    assert claim.confidence == 0.0


class _FakeSettings:
    claim_extraction_base_url = ""
    claim_extraction_api_key = ""
    claim_extraction_model = ""
    claim_extraction_timeout_seconds = 10
    claim_extraction_max_retries = 0
